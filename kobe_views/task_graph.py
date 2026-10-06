"""Task-scoped, event-sourced semantic memory, independent of UI page lifetimes.

Extraction proposes entities and claims, never roles, permissions, or a task verdict.
Semantic types/predicates are discovered from events; structural contracts stay fixed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Mapping, Protocol

from .model import digest, dumps, freeze, plain


class RevisionConflict(ValueError):
    """Extraction or a second writer used an outdated task revision."""


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    revision: str
    sequence: int
    entities: Mapping
    claims: Mapping
    statuses: Mapping
    conflicts: tuple
    schema: Mapping


class TaskExtractor(Protocol):
    def extract(self, observation: dict, snapshot: TaskSnapshot) -> dict:
        """Return {entities: [...], claims: [...]}, with source locators.

        Implementations may use a model. Output is a proposal, not verified truth.
        The caller retains authority over observation source and role contracts.
        """
        ...


def _keys(value, allowed, required):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f"Invalid fields; required={sorted(required)}, allowed={sorted(allowed)}")


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError(f"Invalid semantic name: {value!r}")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty string")
    return value


def _time(value):
    stamp = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Event timestamps must include a timezone")
    return stamp


def _ids(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError("References must be lists of nonempty ids")
    if len(set(value)) != len(value):
        raise ValueError("Duplicate reference")
    return value


def _shape(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (float, int)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _slot(claim):
    return claim["subject"], claim["predicate"]


def _dependencies_acyclic(claims):
    visited, visiting = set(), set()

    def visit(cid):
        if cid in visiting:
            raise ValueError("Cyclic claim dependencies")
        if cid in visited:
            return
        visiting.add(cid)
        for parent in claims[cid]["basis"]:
            visit(parent)
        visiting.remove(cid)
        visited.add(cid)

    for cid in claims:
        visit(cid)


def _derive(claims):
    superseded = {old for c in claims.values() for old in c["supersedes"]}
    statuses = {cid: "superseded" if cid in superseded else "active" for cid in claims}
    # Conservative invalidation reaches a fixed point, including transitive dependents.
    while True:
        slots = {}
        for cid, claim in claims.items():
            if statuses[cid] == "active":
                slots.setdefault(_slot(claim), []).append(cid)
        conflicts = {
            slot: ids for slot, ids in slots.items()
            if len({dumps([claims[c]["value"], sorted(claims[c]["objects"])]) for c in ids}) > 1
        }
        stale = [cid for cid, c in claims.items() if statuses[cid] == "active" and any(
            statuses[parent] != "active" or _slot(claims[parent]) in conflicts for parent in c["basis"])]
        if not stale:
            return statuses, tuple({"subject": s, "predicate": p, "claim_ids": tuple(ids)}
                                   for (s, p), ids in sorted(conflicts.items()))
        statuses.update((cid, "stale") for cid in stale)


class TaskGraph:
    """Append-only observations; immutable claims; atomic publication and optional SQLite replay.

    Source ids are assigned by the trusted adapter. Explicit revisions default to the
    same source; revision_grants may authorize an adapter source to revise another.
    Multiple concurrent database writers are detected, not silently merged.
    """

    def __init__(self, task_id: str, *, journal: str | Path | None = None,
                 revision_grants: dict[str, tuple[str, ...]] | None = None,
                 max_types: int = 64, max_predicates: int = 256):
        self.task_id = _text(task_id)
        if min(max_types, max_predicates) < 1:
            raise ValueError("Schema limits must be positive")
        self.max_types, self.max_predicates = max_types, max_predicates
        self.revision_grants = {k: tuple(v) for k, v in (revision_grants or {}).items()}
        self._lock = RLock()
        self._events = {}
        self._snapshot = TaskSnapshot(task_id, digest([task_id]), 0, freeze({}), freeze({}), freeze({}), (), freeze({}))
        self._closed = False
        self._db = None
        if journal is not None:
            self._db = sqlite3.connect(str(journal), check_same_thread=False)
            try:
                self._db.execute("CREATE TABLE IF NOT EXISTS task_events "
                                 "(seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)")
                self._db.commit()
                for event_id, payload in self._db.execute("SELECT event_id, payload FROM task_events ORDER BY seq"):
                    event = json.loads(payload)
                    if event["id"] != event_id:
                        raise ValueError("Journal event identity mismatch")
                    self._ingest(event, persist=False)
            except Exception:
                self._db.close()
                raise

    def close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
            self._closed = True

    def read(self) -> TaskSnapshot:
        with self._lock:
            return self._snapshot

    def event(self, event_id: str) -> dict:
        """Raw evidence retrieval for a trusted adapter/auditor, not a role-filtered API."""
        with self._lock:
            return json.loads(self._events[event_id])

    def observe(self, observation: dict, extractor: TaskExtractor) -> dict:
        """Connect a live screenshot/DOM/message extraction implementation to the graph."""
        if "extraction" in observation:
            raise ValueError("observe expects raw evidence without an extraction")
        raw = json.loads(dumps(observation))
        snapshot = self.read()
        proposal = extractor.extract(json.loads(dumps(raw)), snapshot)
        return self.ingest({**raw, "extraction": proposal}, expected_revision=snapshot.revision)

    def ingest(self, event: dict, *, expected_revision: str | None = None) -> dict:
        with self._lock:
            if self._closed:
                raise ValueError("TaskGraph is closed")
            if expected_revision is not None and expected_revision != self._snapshot.revision:
                raise RevisionConflict("Task changed during extraction; rebase the proposal")
            return self._ingest(json.loads(dumps(event)), persist=True)

    def _ingest(self, event, *, persist):
        required = {"id", "task_id", "source", "ref", "observed_at", "occurred_at", "text", "extraction"}
        _keys(event, required, required)
        for key in required - {"extraction"}:
            _text(event[key])
        if event["task_id"] != self.task_id:
            raise ValueError("Cross-task event rejected")
        _time(event["observed_at"])
        occurred = _time(event["occurred_at"])
        encoded = dumps(event)
        previous = self._events.get(event["id"])
        if previous is not None:
            if previous != encoded:
                raise ValueError("Event id reused with different contents")
            return {"revision": self._snapshot.revision, "duplicate": True, "newly_stale": []}
        patch = event["extraction"]
        _keys(patch, {"entities", "claims"}, {"entities", "claims"})
        if not isinstance(patch["entities"], list) or not isinstance(patch["claims"], list):
            raise ValueError("Extraction entities and claims must be lists")
        old = self._snapshot
        entities, claims = plain(old.entities), plain(old.claims)
        new_entities, new_claims = [], []
        for entity in patch["entities"]:
            _keys(entity, {"id", "type", "label"}, {"id", "type", "label"})
            _text(entity["id"])
            _name(entity["type"])
            _text(entity["label"])
            if entity["id"] in entities and entities[entity["id"]] != entity:
                raise ValueError("Entity identity/type is immutable; represent renames as claims")
            if entity["id"] not in entities:
                new_entities.append(entity["id"])
            entities[entity["id"]] = entity
        for proposed in patch["claims"]:
            mandatory = {"id", "subject", "predicate", "value", "locator"}
            _keys(proposed, mandatory | {"objects", "basis", "supersedes", "mode"}, mandatory)
            claim = {"objects": [], "basis": [], "supersedes": [], "mode": "extracted", **proposed}
            for key in ("id", "subject", "locator"):
                _text(claim[key])
            _name(claim["predicate"])
            for key in ("objects", "basis", "supersedes"):
                _ids(claim[key])
            if claim["mode"] not in {"extracted", "derived"}:
                raise ValueError("Extraction cannot assign a verified trust grade")
            if claim["mode"] == "derived" and not claim["basis"]:
                raise ValueError("Derived claims need explicit evidence dependencies")
            if claim["id"] in claims:
                raise ValueError("Claim ids are immutable and unique across observations")
            if claim["subject"] not in entities or any(obj not in entities for obj in claim["objects"]):
                raise ValueError("Unresolved entity reference; propose a scoped entity first")
            claim["evidence"] = {k: event[k] for k in ("source", "ref", "occurred_at", "observed_at")}
            claim["evidence"].update(event_id=event["id"], locator=claim.pop("locator"))
            claims[claim["id"]] = claim
            new_claims.append(claim["id"])
        for cid in new_claims:
            claim = claims[cid]
            if any(parent not in claims for parent in claim["basis"]):
                raise ValueError("Unresolved evidence dependency")
            for parent_id in claim["supersedes"]:
                if parent_id not in old.claims:
                    raise ValueError("Revisions must name a claim from a previously committed event")
                parent = claims[parent_id]
                if _slot(parent) != _slot(claim):
                    raise ValueError("A revision must keep the same entity and predicate")
                if occurred < _time(parent["evidence"]["occurred_at"]):
                    raise ValueError("A late-arriving old event cannot supersede newer evidence")
                source = parent["evidence"]["source"]
                if source != event["source"] and source not in self.revision_grants.get(event["source"], ()):
                    raise ValueError("Source has no permission to revise the named evidence")
        _dependencies_acyclic(claims)
        statuses, conflicts = _derive(claims)
        schema = {e["type"]: {} for e in entities.values()}
        for claim in claims.values():
            shape = "entity_relation" if claim["objects"] else _shape(claim["value"])
            fields = schema[entities[claim["subject"]]["type"]]
            fields.setdefault(claim["predicate"], set()).add(shape)
        if len(schema) > self.max_types or len({c["predicate"] for c in claims.values()}) > self.max_predicates:
            raise ValueError("Adaptive schema budget exceeded; consolidate the extraction proposal")
        schema = {kind: {key: sorted(value) for key, value in fields.items()} for kind, fields in schema.items()}
        revision = digest([old.revision, event])
        snapshot = TaskSnapshot(self.task_id, revision, old.sequence + 1, freeze(entities), freeze(claims),
                                freeze(statuses), freeze(conflicts), freeze(schema))
        if persist and self._db is not None:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                count = self._db.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
                if count != old.sequence:
                    raise RevisionConflict("Another journal writer committed; reopen TaskGraph before writing")
                self._db.execute("INSERT INTO task_events(event_id, payload) VALUES (?, ?)", (event["id"], encoded))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        self._events[event["id"]] = encoded
        self._snapshot = snapshot
        return {"revision": revision, "duplicate": False, "added_entities": new_entities,
                "added_claims": new_claims, "new_types": sorted(set(schema) - set(old.schema)),
                "changed_predicates": sorted({claims[c]["predicate"] for c in new_claims}),
                "newly_stale": sorted(c for c, s in statuses.items() if s == "stale" and old.statuses.get(c) != s),
                "superseded_claims": sorted(c for c, s in statuses.items()
                                             if s == "superseded" and old.statuses.get(c) != s),
                "conflicts": plain(conflicts)}
