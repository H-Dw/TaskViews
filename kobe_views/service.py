"""Snapshot-consistent projection with closure budgeting and bounded expansion."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from threading import RLock
from typing import Protocol
from .model import Budget, Grade, Request, View, ViewKind, digest, dumps, plain
from .policies import default_policies
from .retrieval import LexicalRetriever
from .routing import CapabilityRouter
from .store import GraphStore


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class Utf8BudgetCounter:
    """Conservative byte units for byte-based tokenizers; inject exact tokenizer."""
    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class BudgetTooSmall(ValueError):
    pass


class StaleHandle(ValueError):
    pass


def project_node(node, kind, request):
    fields, conflicts = {}, {}
    for key, assertions in node.fields.items():
        if kind == ViewKind.GROUNDING and key not in {
            "text", "description", "position", "role", "bbox", "visible", "enabled",
            "coordinate_space", "roi", "page_description", "activity"}:
            continue
        if kind == ViewKind.VERIFICATION and request.target_fields and key not in {
            *request.target_fields, "page_description", "text", "description", "activity"}:
            continue
        bad = [a for a in assertions if a.grade == Grade.CONTRADICTED]
        current = [a for a in assertions if request.observation_id and a.observation_id == request.observation_id]
        conflicting_current = len({dumps(a.value) for a in current}) > 1
        if bad or conflicting_current:
            conflicts[key] = plain(assertions)
            if kind != ViewKind.VERIFICATION:
                continue
        kept = list(assertions)
        # Keep semantic descriptions as candidates, but do not route guessed state into planning.
        if kind in {ViewKind.PLANNING, ViewKind.RELATION} and key not in {"page_description", "description", "text"}:
            kept = [a for a in kept if a.grade not in {Grade.CANDIDATE, Grade.CONTRADICTED}]
        if kept:
            fields[key] = plain(kept)
    return {"id": node.id, "kind": node.kind, "page_id": node.page_id,
            "fields": fields, "conflicts": conflicts}


class ProjectionService:
    def __init__(self, store=None, *, retriever=None, router=None, policies=None,
                 counter=None, handle_capacity=128):
        if handle_capacity < 1:
            raise ValueError("handle_capacity must be positive")
        self.store = store or GraphStore()
        self.retriever = retriever or LexicalRetriever()
        self.router = router or CapabilityRouter()
        self.policies = policies or default_policies()
        self.counter = counter or Utf8BudgetCounter()
        self.handle_capacity = handle_capacity
        self._handles = OrderedDict()
        self._lock = RLock()

    def project(self, request: Request) -> dict[ViewKind, View]:
        snapshot = self.store.read()  # ALL requested views share this revision.
        return {kind: self._project(snapshot, request, kind) for kind in self.router.route(request)}

    def _project(self, snapshot, request, kind):
        if kind not in self.policies:
            raise ValueError(f"No policy registered for {kind}")
        bundles, gaps = self.policies[kind].build(snapshot, request, self.retriever)
        if any(n not in snapshot.nodes for n in request.seed_ids):
            gaps.append("requested_seed_missing")
        handle = digest([snapshot.revision, request, kind])
        ns, es, details = set(), set(), []

        def payload(omitted, candidate_ns=ns, candidate_es=es, candidate_details=details):
            return {
                "schema_version": 1, "kind": kind.value, "consumer": request.consumer,
                "revision": snapshot.revision, "observation_id": request.observation_id,
                "nodes": [project_node(snapshot.nodes[n], kind, request) for n in sorted(candidate_ns)],
                "edges": [plain(snapshot.edges[e]) for e in sorted(candidate_es)],
                "closures": plain(candidate_details),
                "gaps": sorted(set(gaps + (["budget_omitted_closures"] if omitted else []))),
                "omitted_closures": omitted, "expansion_handle": handle if omitted else None,
                "budget_unit": type(self.counter).__name__,
            }

        # Reserve the final envelope/handle before admitting closure bundles.
        if self.counter.count(dumps(payload(len(bundles)))) > request.budget.max_tokens:
            raise BudgetTooSmall("Budget cannot hold the view envelope and evidence gaps")
        omitted = 0
        for item in bundles:
            candidate_ns, candidate_es = ns | set(item.nodes), es | set(item.edges)
            for eid in item.edges:
                edge = snapshot.edges[eid]
                if edge.source not in candidate_ns or edge.target not in candidate_ns:
                    raise ValueError("Projection plugin returned a dangling edge")
            candidate_details = details + [item.details]
            serialized = dumps(payload(len(bundles), candidate_ns, candidate_es, candidate_details))
            if (len(candidate_ns) > request.budget.max_nodes or len(candidate_es) > request.budget.max_edges
                    or self.counter.count(serialized) > request.budget.max_tokens):
                omitted += 1
                continue
            ns.update(item.nodes)
            es.update(item.edges)
            details.append(item.details)
        encoded = dumps(payload(omitted))
        if self.counter.count(encoded) > request.budget.max_tokens:
            raise BudgetTooSmall("Budget cannot hold serialized output")
        if omitted:
            with self._lock:
                self._handles[handle] = (snapshot.revision, request, kind)
                self._handles.move_to_end(handle)
                while len(self._handles) > self.handle_capacity:
                    self._handles.popitem(last=False)
        return View(encoded, self.counter.count(encoded))

    def expand(self, handle: str, budget: Budget) -> View:
        with self._lock:
            if handle not in self._handles:
                raise StaleHandle("Unknown or expired expansion handle")
            revision, request, kind = self._handles[handle]
        snapshot = self.store.read()
        if revision != snapshot.revision:
            raise StaleHandle("Graph changed; issue a new projection request")
        return self._project(snapshot, replace(request, budget=budget), kind)
