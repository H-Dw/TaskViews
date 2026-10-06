"""UI-KOBE JSON / live DiGraph and explicit aligned-observation adapters."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote
from .model import Assertion, Edge, EvidenceRef, Grade, Node, Snapshot, digest


def page_id(app: str, raw_id: str) -> str:
    return f"{quote(app, safe='')}/page/{quote(str(raw_id), safe='')}"


def control_id(page: str, local_id: str) -> str:
    return f"{page}/control/{quote(str(local_id), safe='')}"


class UIKobeAdapter:
    def convert(self, source: Any, app: str = "app") -> Snapshot:
        """Copies facts only; no VLM/embedding imports or guessed geometry."""
        if isinstance(source, dict):
            if not isinstance(source.get("nodes"), list) or not isinstance(source.get("edges"), list):
                raise ValueError("Expected UI-KOBE nodes and edges lists")
            raw_nodes, raw_edges = source["nodes"], source["edges"]
        else:
            graph = source if hasattr(source, "nodes") else source.graph
            raw_nodes = [dict(attrs, id=n) for n, attrs in graph.nodes(data=True)]
            raw_edges = [dict(attrs, source=s, target=t) for s, t, attrs in graph.edges(data=True)]
        nodes, edges = [], []
        for raw in raw_nodes:
            pid = page_id(app, raw["id"])
            ref = EvidenceRef("ui_kobe", f"node:{raw['id']}")
            fs = {}
            for key, default in {"page_description": "", "activity": "", "state_schema": {}, "visit_count": 0}.items():
                grade = Grade.CANDIDATE if key == "page_description" else Grade.OBSERVED
                fs[key] = (Assertion(raw.get(key, default), grade, (ref,)),)
            for key, value in raw.get("last_detail_snapshot", {}).items():
                fs[f"state.{key}"] = (Assertion(value, Grade.OBSERVED, (ref,)),)
            nodes.append(Node(pid, "page", pid, fs))
            seen = set()
            for elem in raw.get("interactable_elements", []):
                local_id = str(elem.get("id") or digest([elem.get("description"), elem.get("position")]))
                cid = control_id(pid, local_id)
                if cid in seen:
                    continue
                seen.add(cid)
                cref = EvidenceRef("ui_kobe", f"node:{raw['id']}/element:{local_id}")
                fields = {k: (Assertion(elem[k], Grade.CANDIDATE, (cref,)),)
                          for k in ("description", "position", "role", "bbox", "text", "explored") if k in elem}
                nodes.append(Node(cid, "control", pid, fields))
                edges.append(Edge(f"contains:{cid}", pid, cid, "contains", evidence=(cref,)))
        for raw in raw_edges:
            src, dst = page_id(app, raw["source"]), page_id(app, raw["target"])
            ref = EvidenceRef("ui_kobe", f"edge:{raw['source']}->{raw['target']}")
            # Upstream appends optional arrays independently. Keep aggregates; do not zip them.
            fields = {k: raw.get(k, []) for k in ("actions", "instructions", "instruction_templates",
                      "target_observations", "schema_deltas", "num_steps")}
            fields["visit_count"] = raw.get("visit_count", 0)
            fields["metadata_alignment"] = "aggregate_unpaired"
            edges.append(Edge(f"transition:{digest([src, dst])}", src, dst, "transition", fields,
                              Grade(raw.get("grade", "observed")), (ref,),
                              bool(raw.get("failed", False)), bool(raw.get("high_risk", False))))
        return Snapshot.create(nodes, edges)


def observation_nodes(data: dict, app: str) -> tuple[list[Node], list[Edge]]:
    """Explicit normalized input; callers own entity alignment and source grading.

    fields: {name: value} or {name: {value, grade, source, ref}}.
    Controls use local stable ids; relationships explicitly name local endpoints.
    """
    oid = data["id"]
    if not isinstance(oid, str) or not oid:
        raise ValueError("Observation needs a nonempty string id")
    pid = page_id(app, data["page"])

    def fields(raw, default_source):
        result = {}
        for key, entry in raw.items():
            entries = entry.get("assertions") if isinstance(entry, dict) and "assertions" in entry else [entry]
            assertions = []
            for item in entries:
                spec = item if isinstance(item, dict) and "value" in item else {"value": item}
                ref = EvidenceRef(spec.get("source", default_source), spec.get("ref", f"observation:{oid}"), oid)
                assertions.append(Assertion(spec["value"], Grade(spec.get("grade", "observed")), (ref,), oid))
            result[key] = tuple(assertions)
        return result

    nodes = [Node(pid, "page", pid, fields(data.get("fields", {}), "observation"))]
    edges = []
    for control in data.get("controls", []):
        cid = control_id(pid, control["id"])
        nodes.append(Node(cid, control.get("kind", "control"), pid,
                          fields(control.get("fields", {}), "structure")))
        parent = control_id(pid, control["parent"]) if control.get("parent") else pid
        edges.append(Edge(f"contains:{cid}", parent, cid, "contains",
                          evidence=(EvidenceRef("structure", f"observation:{oid}", oid),)))
    for rel in data.get("relations", []):
        src, dst = control_id(pid, rel["source"]), control_id(pid, rel["target"])
        edges.append(Edge(rel.get("id", f"relation:{digest([src, dst, rel['kind']])}"), src, dst, rel["kind"],
                          rel.get("fields", {}), Grade(rel.get("grade", "observed")),
                          (EvidenceRef(rel.get("source_type", "structure"), rel.get("ref", f"observation:{oid}"), oid),)))
    return nodes, edges
