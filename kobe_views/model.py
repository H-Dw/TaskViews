"""Framework-independent, immutable contracts for task-conditioned graph reads."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


class Grade(str, Enum):
    CANDIDATE = "candidate"
    OBSERVED = "observed"
    CORROBORATED = "corroborated"
    INTERACTION_VERIFIED = "interaction_verified"
    CONTRADICTED = "contradicted"


class ViewKind(str, Enum):
    GROUNDING = "grounding"
    RELATION = "relation"
    PLANNING = "planning"
    VERIFICATION = "verification"


def plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class EvidenceRef:
    source: str
    ref: str
    observation_id: str = ""


@dataclass(frozen=True)
class Assertion:
    value: Any
    grade: Grade = Grade.OBSERVED
    evidence: tuple[EvidenceRef, ...] = ()
    observation_id: str = ""  # Empty means historical/undated, NEVER current.

    def __post_init__(self):
        object.__setattr__(self, "value", freeze(self.value))
        object.__setattr__(self, "grade", Grade(self.grade))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        dumps(self.value)  # Reject non-JSON and NaN at the boundary.


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    page_id: str
    fields: Mapping[str, tuple[Assertion, ...]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "fields", freeze(self.fields))
        if not self.id or not self.page_id:
            raise ValueError("Node id and page_id are required")


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    kind: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    grade: Grade = Grade.OBSERVED
    evidence: tuple[EvidenceRef, ...] = ()
    failed: bool = False
    high_risk: bool = False

    def __post_init__(self):
        object.__setattr__(self, "fields", freeze(self.fields))
        object.__setattr__(self, "grade", Grade(self.grade))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        dumps(self.fields)


@dataclass(frozen=True)
class Snapshot:
    revision: str
    nodes: Mapping[str, Node]
    edges: Mapping[str, Edge]

    @classmethod
    def create(cls, nodes: list[Node], edges: list[Edge]) -> Snapshot:
        ns, es = {n.id: n for n in nodes}, {e.id: e for e in edges}
        if len(ns) != len(nodes) or len(es) != len(edges):
            raise ValueError("Duplicate canonical ids")
        for n in nodes:
            if n.page_id not in ns or ns[n.page_id].kind != "page":
                raise ValueError(f"Missing page for {n.id}")
        for e in edges:
            if e.source not in ns or e.target not in ns:
                raise ValueError(f"Dangling edge: {e.id}")
        ordered = [sorted(nodes, key=lambda n: n.id), sorted(edges, key=lambda e: e.id)]
        return cls(digest(ordered), MappingProxyType(ns), MappingProxyType(es))


@dataclass(frozen=True)
class Budget:
    max_tokens: int = 12000
    max_nodes: int = 40
    max_edges: int = 60

    def __post_init__(self):
        if min(self.max_tokens, self.max_nodes, self.max_edges) < 1:
            raise ValueError("Budget limits must be positive")


@dataclass(frozen=True)
class Request:
    task: str
    consumer: str = "custom"
    capabilities: tuple[str, ...] = ()
    action: str = ""
    current_page: str = ""
    observation_id: str = ""
    seed_ids: tuple[str, ...] = ()
    target_fields: tuple[str, ...] = ()
    kinds: tuple[ViewKind, ...] = ()
    budget: Budget = field(default_factory=Budget)
    top_k: int = 6
    max_hops: int = 6
    recent_action: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("capabilities", "seed_ids", "target_fields"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "kinds", tuple(ViewKind(k) for k in self.kinds))
        object.__setattr__(self, "recent_action", freeze(self.recent_action))
        if self.top_k < 1 or self.max_hops < 0:
            raise ValueError("top_k must be positive; max_hops cannot be negative")


@dataclass(frozen=True)
class Bundle:
    """An indivisible structural closure; budgeting must never split it."""
    nodes: tuple[str, ...]
    edges: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "details", freeze(self.details))


@dataclass(frozen=True)
class View:
    """Serialized once so callers cannot mutate another consumer's view."""
    json: str
    token_count: int

    @property
    def data(self) -> dict:
        return json.loads(self.json)
