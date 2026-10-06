"""Compile role-scoped views from discovered task objects and relation predicates.

There is no meeting/expense/purchase switch and no domain-specific ViewKind enum.
Role contracts come from the caller, never from an extracted webpage or message.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase

from .model import Budget, View, digest, dumps, plain
from .service import BudgetTooSmall, Utf8BudgetCounter
from .task_graph import TaskSnapshot


@dataclass(frozen=True)
class RoleContract:
    id: str
    anchors: tuple[str, ...]
    read_predicates: tuple[str, ...]  # Positive allowlist; relevance never grants access.
    focus_predicates: tuple[str, ...] = ()
    sources: tuple[str, ...] = ("*",)
    facets: tuple[str, ...] = ("objects", "relations", "attention")
    max_hops: int = 2
    include_history: bool = False

    def __post_init__(self):
        for field in ("anchors", "read_predicates", "focus_predicates", "sources", "facets"):
            raw = getattr(self, field)
            if not isinstance(raw, (tuple, list)):
                raise ValueError("Role selectors must be lists or tuples")
            value = tuple(raw)
            if any(not isinstance(x, str) or not x for x in value):
                raise ValueError("Role selectors must be nonempty strings")
            object.__setattr__(self, field, value)
        if (not isinstance(self.id, str) or not self.id or not self.anchors or not self.read_predicates
                or not isinstance(self.max_hops, int) or self.max_hops < 0):
            raise ValueError("Role needs an identity, anchors, an explicit read scope and nonnegative hops")
        if set(self.facets) - {"objects", "relations", "attention"}:
            raise ValueError("Unsupported structural facet")

    def can_read(self, claim):
        return (any(fnmatchcase(claim["predicate"], pattern) for pattern in self.read_predicates)
                and any(fnmatchcase(claim["evidence"]["source"], pattern) for pattern in self.sources))


class AdaptiveTaskViews:
    def __init__(self, *, counter=None):
        self.counter = counter or Utf8BudgetCounter()

    def project(self, snapshot: TaskSnapshot, role: RoleContract, budget: Budget = Budget()) -> View:
        readable = {cid: c for cid, c in snapshot.claims.items() if role.can_read(c)}
        anchors = set(role.anchors) & snapshot.entities.keys()
        reached, frontier = set(anchors), set(anchors)
        # Filter before traversal: an unreadable edge cannot open another object's view.
        for _ in range(role.max_hops):
            nearby = set()
            for cid, c in readable.items():
                if snapshot.statuses[cid] != "active":
                    continue
                ends = {c["subject"], *c["objects"]}
                if ends & frontier:
                    nearby.update(ends)
            frontier = nearby - reached
            reached.update(frontier)
        selected = {cid: c for cid, c in readable.items() if c["subject"] in reached
                    and (role.include_history or snapshot.statuses[cid] != "superseded")}
        conflicts = {cid for group in snapshot.conflicts for cid in group["claim_ids"]}
        candidates = []
        if "objects" in role.facets:
            for kind in sorted({snapshot.entities[n]["type"] for n in reached}):
                ids = {cid for cid, c in selected.items() if snapshot.entities[c["subject"]]["type"] == kind}
                if ids:
                    candidates.append((f"object:{kind}", ids))
        if "relations" in role.facets:
            for predicate in sorted({c["predicate"] for c in selected.values() if c["objects"]}):
                candidates.append((f"relation:{predicate}",
                                   {cid for cid, c in selected.items() if c["predicate"] == predicate and c["objects"]}))
        if "attention" in role.facets:
            for label, ids in (("conflicts", set(selected) & conflicts),
                               ("invalidated", {c for c in selected if snapshot.statuses[c] == "stale"})):
                if ids:
                    candidates.append((f"attention:{label}", ids))

        def priority(item):
            kind, ids = item
            relevant = sum(any(fnmatchcase(selected[c]["predicate"], p) for p in role.focus_predicates) for c in ids)
            return (not kind.startswith("attention:"), -relevant, kind)

        candidates.sort(key=priority)
        entity_ids, claim_ids, views = set(), set(), []
        gaps = {"unknown_anchor"} if len(anchors) != len(set(role.anchors)) else set()
        if not selected:
            gaps.add("no_relevant_evidence")
        replacements = {}
        for cid, claim in snapshot.claims.items():
            for parent in claim["supersedes"]:
                replacements.setdefault(parent, []).append(cid)

        def closure(ids):
            kept, pending, missing = set(), list(ids), set()
            while pending:
                cid = pending.pop()
                if cid in kept:
                    continue
                if cid not in readable:
                    missing.add("dependency_outside_role_scope")
                    continue
                kept.add(cid)
                pending.extend(readable[cid]["basis"])
                # Superseded evidence is retained when needed to explain invalidation.
                pending.extend(readable[cid]["supersedes"])
                # Show the correction that made a dependency stale, or expose a scope gap.
                pending.extend(replacements.get(cid, ()))
                if cid in conflicts:
                    for group in snapshot.conflicts:
                        if cid in group["claim_ids"]:
                            for other in group["claim_ids"]:
                                if other in readable:
                                    pending.append(other)
                                else:
                                    missing.add("conflicting_evidence_outside_role_scope")
            ns = {n for cid in kept for n in (readable[cid]["subject"], *readable[cid]["objects"])}
            return kept, ns, missing

        def payload(omitted, ns=entity_ids, cs=claim_ids, specs=views, missing=gaps):
            records = []
            for cid in sorted(cs):
                record = plain(readable[cid])
                # Avoid leaking hidden dependency identities through reference lists.
                for key in ("basis", "supersedes"):
                    record[key] = [parent for parent in record[key] if parent in cs]
                record.update(status=snapshot.statuses[cid], disputed=cid in conflicts)
                records.append(record)
            return {"schema_version": 1, "task_id": snapshot.task_id, "revision": snapshot.revision,
                    "consumer": role.id, "contract_revision": digest(role),
                    "entities": [plain(snapshot.entities[n]) for n in sorted(ns)], "claims": records,
                    "views": specs, "gaps": sorted(missing | ({"budget_omitted_views"} if omitted else set())),
                    "omitted_views": omitted, "budget_unit": type(self.counter).__name__,
                    "interpretation": "extracted_or_derived_evidence_not_a_task_verdict"}

        if self.counter.count(dumps(payload(len(candidates)))) > budget.max_tokens:
            raise BudgetTooSmall("Task view envelope exceeds budget")
        omitted = 0
        for kind, roots in candidates:
            cs, ns, missing = closure(roots)
            next_ns, next_cs, next_gaps = entity_ids | ns, claim_ids | cs, gaps | missing
            spec = {"id": digest([role.id, role.anchors, kind]), "type": kind,
                    "root_claim_ids": sorted(roots), "claim_ids": sorted(cs),
                    "evidence_complete_for_scope": not missing}
            next_views = views + [spec]
            encoded = dumps(payload(len(candidates), next_ns, next_cs, next_views, next_gaps))
            if (len(next_ns) > budget.max_nodes or len(next_cs) > budget.max_edges
                    or self.counter.count(encoded) > budget.max_tokens):
                omitted += 1
                continue
            entity_ids.update(ns)
            claim_ids.update(cs)
            gaps.update(missing)
            views.append(spec)
        encoded = dumps(payload(omitted))
        if self.counter.count(encoded) > budget.max_tokens:
            raise BudgetTooSmall("Task context exceeds budget")
        return View(encoded, self.counter.count(encoded))


def task_view_delta(previous: View | None, current: View) -> dict:
    """Pure, role-scoped delta. Advance the caller's baseline only after delivery.

    Apply a reset by discarding the old projection; otherwise check base_revision,
    remove ids, upsert records, restore collection order, and replace metadata.
    This is an incremental transport payload, not a separate model prompt budget.
    """
    now = current.data
    before = previous.data if previous is not None else {}
    reset = not before or any(before[k] != now[k] for k in ("task_id", "consumer", "contract_revision"))
    upserts, removals = {}, {}
    for key in ("entities", "claims", "views"):
        old = {} if reset else {item["id"]: item for item in before[key]}
        new = {item["id"]: item for item in now[key]}
        upserts[key] = [item for cid, item in sorted(new.items()) if old.get(cid) != item]
        removals[key] = sorted(set(old) - set(new))
    meta = {k: v for k, v in now.items() if k not in upserts}
    old_meta = {k: v for k, v in before.items() if k not in upserts and k != "revision"}
    semantic_meta = {k: v for k, v in meta.items() if k != "revision"}
    changed = reset or any(upserts.values()) or any(removals.values()) or old_meta != semantic_meta
    return {"reset": reset, "base_revision": None if reset else before["revision"],
            "revision": now["revision"], "changed": changed, "upserts": upserts,
            "removals": removals, "order": {k: [item["id"] for item in now[k]] for k in upserts},
            "metadata": meta}
