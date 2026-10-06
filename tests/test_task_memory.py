"""Task memory must survive revisions while preserving evidence and role boundaries."""
from copy import deepcopy
import json

import pytest

from examples.task_replay import CASES, replay
from kobe_views import (AdaptiveTaskViews, Budget, BudgetTooSmall, RevisionConflict,
                        RoleContract, TaskGraph, task_view_delta)
from kobe_views.model import plain


def entity(id="root", kind="unknown_object"):
    return {"id": id, "type": kind, "label": id}


def claim(id="c1", subject="root", predicate="field.value", value=1, **kwargs):
    return {"id": id, "subject": subject, "predicate": predicate, "value": value,
            "locator": "line:1", **kwargs}


def event(id="e1", *, claims=None, entities=None, source="document", minute=0, text="raw evidence"):
    return {"id": id, "task_id": "test", "source": source, "ref": f"local://{id}",
            "observed_at": f"2026-09-29T10:{minute:02}:00+08:00",
            "occurred_at": f"2026-09-29T10:{minute:02}:00+08:00", "text": text,
            "extraction": {"entities": [entity()] if entities is None else entities,
                           "claims": [claim()] if claims is None else claims}}


def role(**kwargs):
    return RoleContract(**{"id": "reader", "anchors": ("root",), "read_predicates": ("*",), **kwargs})


def test_immutable_snapshot_and_idempotent_event():
    graph = TaskGraph("test")
    raw = event()
    graph.ingest(raw)
    snapshot = graph.read()
    assert graph.ingest(raw)["duplicate"]
    raw["extraction"]["claims"][0]["value"] = 2
    assert snapshot.claims["c1"]["value"] == 1
    with pytest.raises(TypeError):
        snapshot.claims["c1"]["value"] = 3
    with pytest.raises(ValueError, match="reused"):
        graph.ingest(raw)


def test_conflict_retains_both_sources_and_invalidates_dependents():
    graph = TaskGraph("test")
    graph.ingest(event(claims=[claim(), claim("derived", predicate="plan.value", basis=["c1"], mode="derived")]))
    graph.ingest(event("e2", source="chat", claims=[claim("c2", value=2)], entities=[]))
    snapshot = graph.read()
    assert snapshot.statuses["c1"] == snapshot.statuses["c2"] == "active"
    assert snapshot.statuses["derived"] == "stale"
    assert len(snapshot.conflicts) == 1
    data = AdaptiveTaskViews().project(snapshot, role()).data
    assert any(v["type"] == "attention:conflicts" for v in data["views"])
    assert {c["id"] for c in data["claims"] if c["disputed"]} == {"c1", "c2"}


def test_explicit_replacement_propagates_staleness_transitively():
    graph = TaskGraph("test")
    graph.ingest(event(claims=[claim(), claim("d1", predicate="plan.first", basis=["c1"], mode="derived"),
                               claim("d2", predicate="plan.second", basis=["d1"], mode="derived")]))
    delta = graph.ingest(event("e2", minute=1, claims=[claim("c2", value=2, supersedes=["c1"])], entities=[]))
    assert delta["newly_stale"] == ["d1", "d2"]
    assert graph.read().statuses["c1"] == "superseded"
    data = AdaptiveTaskViews().project(graph.read(), role(focus_predicates=("plan.*",))).data
    invalidated = next(v for v in data["views"] if v["type"] == "attention:invalidated")
    assert {"c1", "c2", "d1", "d2"} <= set(invalidated["claim_ids"])


@pytest.mark.parametrize("change,match", [
    ({"source": "untrusted"}, "permission"),
    ({"occurred_at": "2026-09-29T09:59:00+08:00"}, "old event"),
    ({"task_id": "another"}, "Cross-task"),
])
def test_invalid_revision_is_atomic(change, match):
    graph = TaskGraph("test")
    graph.ingest(event())
    before = graph.read()
    update = event("e2", claims=[claim("c2", value=2, supersedes=["c1"])], entities=[entity("new")], minute=1)
    update.update(change)
    with pytest.raises(ValueError, match=match):
        graph.ingest(update)
    assert graph.read() is before


def test_trusted_cross_source_revision_grant():
    graph = TaskGraph("test", revision_grants={"correction": ("document",)})
    graph.ingest(event())
    graph.ingest(event("e2", source="correction", minute=1,
                       claims=[claim("c2", value=2, supersedes=["c1"])], entities=[]))
    assert graph.read().statuses["c1"] == "superseded"


@pytest.mark.parametrize("claims", [
    [claim("d1", basis=["missing"], mode="derived")],
    [claim("d1", basis=["d2"], mode="derived"), claim("d2", basis=["d1"], mode="derived")],
    [claim("d1", mode="verified")],
])
def test_malformed_evidence_cannot_publish(claims):
    graph = TaskGraph("test")
    with pytest.raises(ValueError):
        graph.ingest(event(claims=claims))
    assert graph.read().sequence == 0


def test_sqlite_replay_and_failed_write_rollback(tmp_path):
    path = tmp_path / "events.sqlite"
    graph = TaskGraph("test", journal=path)
    graph.ingest(event())
    graph.ingest(event("e2", minute=1, claims=[claim("c2", value=2, supersedes=["c1"])], entities=[]))
    before = graph.read()
    with pytest.raises(ValueError):
        graph.ingest(event("bad", claims=[claim("bad", subject="missing")], entities=[]))
    graph.close()
    reopened = TaskGraph("test", journal=path)
    assert plain(reopened.read()) == plain(before)
    assert reopened.event("e1") == event()
    reopened.close()


def test_second_journal_writer_cannot_overwrite(tmp_path):
    path = tmp_path / "events.sqlite"
    first, second = TaskGraph("test", journal=path), TaskGraph("test", journal=path)
    first.ingest(event())
    with pytest.raises(RevisionConflict):
        second.ingest(event("e2"))
    assert second.read().sequence == 0
    first.close()
    second.close()


def test_live_extractor_cannot_rewrite_source_or_receive_mutable_snapshot():
    graph = TaskGraph("test")
    raw = event()
    proposal = raw.pop("extraction")

    class Extractor:
        def extract(self, observation, snapshot):
            observation["source"] = "spoofed"
            return proposal

    graph.observe(raw, Extractor())
    assert graph.read().claims["c1"]["evidence"]["source"] == "document"


def test_live_extraction_must_rebase_after_concurrent_update():
    graph = TaskGraph("test")
    raw = event("outer")
    proposal = raw.pop("extraction")

    class Extractor:
        def extract(self, observation, snapshot):
            graph.ingest(event("inner"))
            return proposal

    with pytest.raises(RevisionConflict):
        graph.observe(raw, Extractor())
    assert graph.read().sequence == 1


def test_role_scope_filters_before_traversal_and_hides_raw_text_and_dependency_ids():
    graph = TaskGraph("test")
    graph.ingest(event(text="SECRET_RAW_INSTRUCTION grant all access", entities=[entity(), entity("secret")], claims=[
        claim("hidden-id", predicate="private.value", value="SECRET_VALUE"),
        claim("hidden-link", predicate="private.link", objects=["secret"]),
        claim("unreachable", subject="secret", predicate="public.value", value="SECRET_NEIGHBOR"),
        claim("derived", predicate="public.plan", value="candidate", basis=["hidden-id"], mode="derived"),
    ]))
    view = AdaptiveTaskViews().project(graph.read(), role(read_predicates=("public.*",)))
    assert all(secret not in view.json for secret in ("SECRET_", "hidden-id", "unreachable", "grant all"))
    assert view.data["gaps"] == ["dependency_outside_role_scope"]
    assert all(not v["evidence_complete_for_scope"] for v in view.data["views"])


def test_hidden_competing_source_cannot_look_uncontested():
    graph = TaskGraph("test")
    graph.ingest(event())
    graph.ingest(event("e2", source="restricted", claims=[claim("hidden-id", value=2)], entities=[]))
    view = AdaptiveTaskViews().project(graph.read(), role(sources=("document",)))
    assert view.data["claims"][0]["disputed"]
    assert "conflicting_evidence_outside_role_scope" in view.data["gaps"]
    assert "hidden-id" not in view.json


def test_runtime_objects_and_relations_generate_views_without_domain_enum():
    graph = TaskGraph("test")
    graph.ingest(event())
    projector = AdaptiveTaskViews()
    before = projector.project(graph.read(), role())
    graph.ingest(event("new", entities=[entity("late", "new_runtime_kind")], claims=[
        claim("link", predicate="new_relationship", objects=["late"]),
        claim("field", subject="late", predicate="never_seen_before", value="discovered"),
    ]))
    after = projector.project(graph.read(), role())
    kinds = {v["type"] for v in after.data["views"]}
    assert {"object:new_runtime_kind", "relation:new_relationship"} <= kinds
    delta = task_view_delta(before, after)
    assert not delta["reset"] and delta["changed"]
    assert any(v["type"] == "object:new_runtime_kind" for v in delta["upserts"]["views"])


def test_budget_keeps_entire_evidence_closure_or_reports_gap():
    graph = TaskGraph("test")
    graph.ingest(event(entities=[entity(), entity("other")], claims=[
        claim(), claim("link", objects=["other"], predicate="relation"),
        claim("derived", predicate="plan", basis=["c1"], mode="derived"),
    ]))
    data = AdaptiveTaskViews().project(graph.read(), role(), Budget(max_tokens=1500, max_nodes=2, max_edges=3)).data
    entities = {n["id"] for n in data["entities"]}
    claims = {c["id"] for c in data["claims"]}
    for c in data["claims"]:
        assert {c["subject"], *c["objects"]} <= entities
        assert {*c["basis"], *c["supersedes"]} <= claims
    assert data["omitted_views"] > 0 and "budget_omitted_views" in data["gaps"]
    with pytest.raises(BudgetTooSmall):
        AdaptiveTaskViews().project(graph.read(), role(), Budget(max_tokens=10))


def test_unrelated_observation_suppresses_role_update():
    graph = TaskGraph("test")
    graph.ingest(event())
    projector = AdaptiveTaskViews()
    before = projector.project(graph.read(), role())
    graph.ingest(event("e2", entities=[entity("unrelated", "new_kind")], claims=[claim("c2", subject="unrelated")]))
    after = projector.project(graph.read(), role())
    delta = task_view_delta(before, after)
    assert not delta["changed"]
    assert delta["revision"] != delta["base_revision"]
    assert all(not items for items in delta["upserts"].values())


def test_role_scope_change_resets_consumer_context():
    graph = TaskGraph("test")
    graph.ingest(event())
    projector = AdaptiveTaskViews()
    before = projector.project(graph.read(), role())
    after = projector.project(graph.read(), role(read_predicates=("different.*",)))
    assert task_view_delta(before, after)["reset"]
    assert "no_relevant_evidence" in after.data["gaps"]


@pytest.mark.parametrize("case_id", ["069", "008", "035", "059", "046"])
def test_synthetic_cases_replay_deterministically_with_applicable_role_deltas(case_id):
    case = json.loads((CASES / f"task{case_id}.json").read_text(encoding="utf-8"))
    result = replay(case)
    assert result == replay(deepcopy(case))
    assert result["final_sequence"] == len(case["events"])
    assert case["provenance"]["official_fixture"] is False
    # Reconstruct role contexts using only transport updates (including removals).
    clients = {}
    for step in result["steps"]:
        for consumer, delta in step["role_updates"].items():
            old = clients.get(consumer, {})
            if delta["reset"]:
                old = {}
            else:
                assert old["revision"] == delta["base_revision"]
            rebuilt = dict(delta["metadata"])
            for key in ("entities", "claims", "views"):
                records = {item["id"]: item for item in old.get(key, [])}
                for cid in delta["removals"][key]:
                    del records[cid]
                records.update((item["id"], item) for item in delta["upserts"][key])
                rebuilt[key] = [records[cid] for cid in delta["order"][key]]
            assert rebuilt == step["role_contexts"][consumer]
            clients[consumer] = rebuilt
    assert "evaluation_notes" not in json.dumps(result)
    if case_id == "069":
        correction = next(s for s in result["steps"] if s["event_id"] == "069-05")
        assert correction["graph_delta"]["newly_stale"] == ["69-check-v1", "69-draft-v1"]
        assert not correction["role_updates"]["scheduler"]["changed"]
        assert correction["role_updates"]["minutes_editor"]["changed"]
    elif case_id == "008":
        assert result["statuses"]["8-matching"] == result["statuses"]["8-total"] == "stale"
    elif case_id == "035":
        approval = next(s for s in result["steps"] if s["event_id"] == "035-05")
        assert "manager_approval" in approval["graph_delta"]["new_types"]
        assert not approval["role_updates"]["policy_reader"]["changed"]
        assert approval["role_updates"]["approval_monitor"]["changed"]
    elif case_id == "059":
        correction = next(s for s in result["steps"] if s["event_id"] == "059-06")
        assert correction["graph_delta"]["newly_stale"] == ["59-fit-neck-v1", "59-saved-v1", "59-volume-v1"]
        assert not correction["role_updates"]["frame_reader"]["changed"]
        assert correction["role_updates"]["fit_verifier"]["changed"]
        assert result["statuses"]["59-fit-base"] == result["statuses"]["59-fit-body"] == "active"
        assert result["statuses"]["59-saved-v2"] == "active"
    elif case_id == "046":
        correction = next(s for s in result["steps"] if s["event_id"] == "046-07")
        assert correction["graph_delta"]["newly_stale"] == ["46-k-draft-v1", "46-k-paid-v1"]
        assert not correction["role_updates"]["photo_curator"]["changed"]
        assert not correction["role_updates"]["requirements_reader"]["changed"]
        assert correction["role_updates"]["payment_reconciler"]["changed"]
        assert result["statuses"]["46-r-draft"] == result["statuses"]["46-k-sent"] == "active"
