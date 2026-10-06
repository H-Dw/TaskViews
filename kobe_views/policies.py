"""Four overlapping projections. Every candidate is a complete closure bundle."""
from __future__ import annotations

from collections import deque
import heapq
from typing import Protocol
from .model import Bundle, Edge, Grade, Request, Snapshot, ViewKind, dumps
from .retrieval import SeedRetriever

SUPPORTED = {Grade.OBSERVED, Grade.CORROBORATED, Grade.INTERACTION_VERIFIED}
RELATIONS = {"contains", "label-for", "same-group", "spatial", "serves-function"}


class ProjectionPolicy(Protocol):
    def build(self, snapshot: Snapshot, request: Request,
              retriever: SeedRetriever) -> tuple[list[Bundle], list[str]]: ...


def ancestors(snapshot: Snapshot, seeds: set[str]) -> tuple[set[str], set[str]]:
    """Parent chains plus attached labels, including their own parent chains."""
    nodes, edges = set(seeds), set()
    pending = list(seeds)
    while pending:
        nid = pending.pop()
        page = snapshot.nodes[nid].page_id
        if page not in nodes:
            nodes.add(page)
            pending.append(page)
        for edge in snapshot.edges.values():
            if edge.grade not in SUPPORTED:
                continue
            if edge.target == nid and edge.kind in {"contains", "label-for"}:
                edges.add(edge.id)
                if edge.source not in nodes:
                    nodes.add(edge.source)
                    pending.append(edge.source)
    return nodes, edges


def bundle(nodes, edges=(), **details):
    return Bundle(tuple(sorted(nodes)), tuple(sorted(edges)), details)


def seeds(snapshot, request, retriever, candidates):
    ranked = retriever.rank(snapshot, request, candidates)
    allowed = set(candidates)
    if any(nid not in allowed for nid, _ in ranked):
        raise ValueError("Retriever returned an id outside the candidate scope")
    return list(dict.fromkeys(nid for nid, _ in ranked))[:request.top_k]


def current_value(node, key, oid):
    return [a for a in node.fields.get(key, ()) if oid and a.observation_id == oid]


class GroundingPolicy:
    def build(self, snapshot, request, retriever):
        gaps, candidates = [], []
        for nid, node in snapshot.nodes.items():
            if node.page_id != request.current_page or node.kind == "page":
                continue
            visible = current_value(node, "visible", request.observation_id)
            if visible and all(a.value is False for a in visible):
                continue
            candidates.append(nid)
        selected = seeds(snapshot, request, retriever, candidates)
        if not selected:
            gaps.append("no_semantic_grounding_match")
        bundles = []
        for nid in selected:
            node = snapshot.nodes[nid]
            ns, es = ancestors(snapshot, {nid})
            visible = current_value(node, "visible", request.observation_id)
            fresh = bool(visible) and all(a.value is True and a.grade in SUPPORTED for a in visible)
            if not fresh:
                gaps.append("current_visibility_missing")
            boxes = current_value(node, "bbox", request.observation_id)
            if not boxes or any(a.grade not in SUPPORTED for a in boxes):
                gaps.append("current_bbox_missing_or_uncertain")
            bundles.append(bundle(ns, es, seed=nid, current_visible=fresh,
                                  status="current_observation" if fresh else "historical_or_uncertain_candidate"))
        return bundles, gaps


def relation_path(snapshot, start, goal, max_hops):
    queue = deque([(start, [], {start})])
    visited = {start}
    while queue:
        nid, path, nodes = queue.popleft()
        if nid == goal:
            return nodes, set(path)
        if len(path) >= max_hops:
            continue
        for edge in sorted(snapshot.edges.values(), key=lambda e: e.id):
            if edge.kind not in RELATIONS or edge.grade not in SUPPORTED:
                continue
            neighbor = edge.target if edge.source == nid else edge.source if edge.target == nid else None
            if neighbor is not None and neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [edge.id], nodes | {neighbor}))
    return None


class RelationPolicy:
    def build(self, snapshot, request, retriever):
        candidates = [nid for nid, n in snapshot.nodes.items()
                      if n.page_id == request.current_page and n.kind != "page"]
        selected = seeds(snapshot, request, retriever, candidates)
        gaps, result = [], []
        if not selected:
            return [], ["no_semantic_relation_match"]
        for nid in selected:
            ns, es = ancestors(snapshot, {nid})
            for edge in snapshot.edges.values():
                if edge.kind in RELATIONS and edge.grade in SUPPORTED and nid in (edge.source, edge.target):
                    more, parent_edges = ancestors(snapshot, {edge.source, edge.target})
                    ns.update(more)
                    es.update(parent_edges | {edge.id})
            path = relation_path(snapshot, selected[0], nid, request.max_hops)
            if path:
                more, parent_edges = ancestors(snapshot, path[0])
                ns.update(more)
                es.update(path[1] | parent_edges)
            elif nid != selected[0]:
                gaps.append("relation_connection_missing")
            result.append(bundle(ns, es, seed=nid))
        return result, gaps


def usable_transition(edge: Edge) -> bool:
    return (edge.kind == "transition" and not edge.failed and edge.grade in SUPPORTED
            and (not edge.high_risk or edge.grade in {Grade.CORROBORATED, Grade.INTERACTION_VERIFIED}))


def reachable_paths(snapshot, request):
    # State includes hop count: a cheaper long route must not suppress a shorter
    # prefix which can still reach a goal within the hop bound.
    queue = [(0.0, 0, request.current_page, ())]
    best = {(request.current_page, 0): 0.0}
    paths = {}
    outgoing = {}
    for edge in sorted(snapshot.edges.values(), key=lambda e: e.id):
        if usable_transition(edge):
            outgoing.setdefault(edge.source, []).append(edge)
    while queue:
        cost, hops, nid, path = heapq.heappop(queue)
        if cost > best.get((nid, hops), float("inf")):
            continue
        paths.setdefault(nid, path)
        if hops >= request.max_hops:
            continue
        for edge in outgoing.get(nid, []):
            if edge.source == edge.target:
                continue
            steps = edge.fields.get("num_steps", (1,))
            valid = [s for s in steps if isinstance(s, (int, float)) and s > 0] if isinstance(steps, (tuple, list)) else []
            step_cost = min(valid, default=1)
            trust = 0 if edge.grade == Grade.INTERACTION_VERIFIED else 0.1 if edge.grade == Grade.CORROBORATED else 0.2
            new_cost = cost + step_cost + trust
            key = (edge.target, hops + 1)
            if new_cost < best.get(key, float("inf")):
                best[key] = new_cost
                heapq.heappush(queue, (new_cost, hops + 1, edge.target, path + (edge.id,)))
    return paths


class PlanningPolicy:
    def build(self, snapshot, request, retriever):
        if request.current_page not in snapshot.nodes:
            return [], ["current_page_unknown"]
        candidates = [nid for nid, n in snapshot.nodes.items() if n.kind == "page"]
        selected = seeds(snapshot, request, retriever, candidates)
        # Explicit control seeds are interpreted as their page for navigation.
        selected = list(dict.fromkeys([snapshot.nodes[n].page_id for n in request.seed_ids if n in snapshot.nodes] + selected))
        paths = reachable_paths(snapshot, request)
        result, gaps = [], []
        for target in selected:
            if target not in paths:
                gaps.append("target_unreachable_or_hop_limit")
                continue
            path = paths[target]
            ns = {request.current_page, target}
            for eid in path:
                ns.update((snapshot.edges[eid].source, snapshot.edges[eid].target))
            result.append(bundle(ns, path, goal=target, path=list(path)))
        if not selected:
            gaps.append("no_semantic_planning_match")
        # Local affordances stay available even when the requested goal is unknown.
        for edge in sorted(snapshot.edges.values(), key=lambda e: e.id):
            if edge.source == request.current_page and usable_transition(edge):
                result.append(bundle({edge.source, edge.target}, {edge.id}, local_affordance=True))
        if not result:
            result.append(bundle({request.current_page}))
        return result, gaps


class VerificationPolicy:
    def build(self, snapshot, request, retriever):
        selected = list(dict.fromkeys(
            [n for n in request.seed_ids if n in snapshot.nodes]
            + ([request.current_page] if request.current_page in snapshot.nodes else [])
            + seeds(snapshot, request, retriever, list(snapshot.nodes))))
        result, gaps = [], []
        if not request.target_fields:
            gaps.append("completion_conditions_unspecified")
        if not request.observation_id:
            gaps.append("current_observation_missing")
        found_current = set()
        for nid in selected:
            node = snapshot.nodes[nid]
            changes = []
            keys = request.target_fields or tuple(k for k in node.fields if k.startswith("state."))
            for key in keys:
                values = node.fields.get(key, ())
                current = [a for a in values if request.observation_id and a.observation_id == request.observation_id]
                previous = [a for a in values if a.observation_id and a.observation_id != request.observation_id]
                if current:
                    found_current.add(key)
                if not current:
                    status = "missing_current_evidence"
                elif any(a.grade == Grade.CONTRADICTED for a in current) or len({dumps(a.value) for a in current}) > 1:
                    status = "conflict"
                elif not previous:
                    status = "before_observation_missing"
                else:
                    prev_id = previous[-1].observation_id
                    before = [a for a in previous if a.observation_id == prev_id]
                    if any(a.grade == Grade.CONTRADICTED for a in before) or len({dumps(a.value) for a in before}) > 1:
                        status = "conflict"
                    else:
                        status = "unchanged" if dumps(before[-1].value) == dumps(current[-1].value) else "changed"
                if status in {"missing_current_evidence", "before_observation_missing"}:
                    gaps.append(status)
                changes.append({"field": key, "status": status})
            ns, es = ancestors(snapshot, {nid})
            result.append(bundle(ns, es, seed=nid, field_comparisons=changes,
                                  recent_action=request.recent_action,
                                  interpretation="observation_comparison_only_not_causality_or_task_verdict"))
        if set(request.target_fields) - found_current:
            gaps.append("target_fields_missing_current_evidence")
        if not result:
            gaps.append("verification_entities_missing")
        return result, gaps


def default_policies():
    return {ViewKind.GROUNDING: GroundingPolicy(), ViewKind.RELATION: RelationPolicy(),
            ViewKind.PLANNING: PlanningPolicy(), ViewKind.VERIFICATION: VerificationPolicy()}
