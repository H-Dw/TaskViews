from dataclasses import replace
import copy
import json
from pathlib import Path

import pytest

from kobe_views import (Assertion, Budget, BudgetTooSmall, Edge, GraphStore,
                       Node, ProjectionService, Request, RuntimeBridge, Snapshot, StaleHandle,
                       UIKobeAdapter, ViewKind as K, control_id, page_id)
from kobe_views.model import Bundle
from kobe_views.routing import CapabilityRouter

FIXTURES = Path(__file__).parents[1] / "examples" / "graphs"


@pytest.fixture
def raw():
    return json.loads((FIXTURES / "settings.json").read_text(encoding="utf-8"))


@pytest.fixture
def observations():
    return json.loads((FIXTURES / "observations.json").read_text(encoding="utf-8"))


def service(raw):
    store = GraphStore()
    store.replace(UIKobeAdapter().convert(raw, "demo"))
    return ProjectionService(store)


def request(kind, **kw):
    return Request("通知设置 notifications", kinds=(kind,), current_page=page_id("demo", "home"),
                   budget=Budget(max_tokens=60000), **kw)


def assert_closed(view):
    ids = {n["id"] for n in view["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in view["edges"])
    assert all(n["page_id"] in ids for n in view["nodes"])


def test_directed_planning_keeps_bridge_and_self_loop(raw):
    svc = service(raw)
    req = request(K.PLANNING, seed_ids=(page_id("demo", "settings"),))
    view = svc.project(req)[K.PLANNING].data
    path = next(c for c in view["closures"] if c.get("goal") == page_id("demo", "settings"))
    assert len(path["path"]) == 2
    assert page_id("demo", "menu") in {n["id"] for n in view["nodes"]}
    assert_closed(view)
    loop = svc.project(replace(req, current_page=page_id("demo", "settings")))[K.PLANNING].data
    assert any(e["source"] == e["target"] for e in loop["edges"])
    backward = svc.project(replace(req, current_page=page_id("demo", "settings"), seed_ids=(page_id("demo", "home"),)))[K.PLANNING].data
    assert "target_unreachable_or_hop_limit" in backward["gaps"]


@pytest.mark.parametrize("grade,failed,risk,allowed", [
    ("candidate", False, False, False), ("contradicted", False, False, False),
    ("observed", True, False, False), ("observed", False, True, False),
    ("corroborated", False, True, True), ("interaction_verified", False, True, True),
])
def test_planning_trust_gate(raw, grade, failed, risk, allowed):
    raw["edges"][1].update(grade=grade, failed=failed, high_risk=risk)
    view = service(raw).project(request(K.PLANNING, seed_ids=(page_id("demo", "settings"),)))[K.PLANNING].data
    assert any(c.get("goal") == page_id("demo", "settings") for c in view["closures"]) is allowed


def test_hop_bound_does_not_discard_shorter_feasible_prefix():
    nodes = [Node(n, "page", n, {"description": (Assertion(n),)}) for n in "abcxz"]
    edges = [Edge("ab", "a", "b", "transition", {"num_steps": [1]}),
             Edge("bx", "b", "x", "transition", {"num_steps": [1]}),
             Edge("ax", "a", "x", "transition", {"num_steps": [5]}),
             Edge("xz", "x", "z", "transition", {"num_steps": [1]})]
    store = GraphStore()
    store.replace(Snapshot.create(nodes, edges))
    view = ProjectionService(store).project(Request("z", current_page="a", kinds=(K.PLANNING,),
        seed_ids=("z",), max_hops=2))[K.PLANNING].data
    assert next(c for c in view["closures"] if c.get("goal") == "z")["path"] == ["ax", "xz"]


def test_adapter_preserves_unpaired_aggregates_and_source(raw):
    before = copy.deepcopy(raw)
    raw["edges"][0]["actions"].append({"action": "swipe"})
    snapshot = UIKobeAdapter().convert(raw, "demo")
    edge = next(e for e in snapshot.edges.values() if e.source == page_id("demo", "home") and e.target == page_id("demo", "menu"))
    assert len(edge.fields["actions"]) == 2
    assert len(edge.fields["instructions"]) == 1
    assert edge.fields["metadata_alignment"] == "aggregate_unpaired"
    assert raw["nodes"] == before["nodes"]
    assert snapshot.nodes[page_id("demo", "settings")].fields["state.notifications"][0].observation_id == ""


def prepared(raw, observations):
    bridge = RuntimeBridge({"enabled": True, "max_tokens": 60000})
    for obs in observations:
        bridge.prepare(raw, app="demo", current_page=obs["page"], observation=obs)
    return bridge


def test_grounding_keeps_parent_label_and_current_bbox(raw, observations):
    bridge = prepared(raw, observations)
    toggle = control_id(bridge.current_page, "toggle")
    req = replace(request(K.GROUNDING, seed_ids=(toggle,)), current_page=bridge.current_page, observation_id="frame:2")
    view = bridge.service.project(req)[K.GROUNDING].data
    ids = {n["id"] for n in view["nodes"]}
    assert {toggle, control_id(bridge.current_page, "panel"), control_id(bridge.current_page, "label"), bridge.current_page} <= ids
    assert next(c for c in view["closures"] if c["seed"] == toggle)["current_visible"] is True
    assert any(e["kind"] == "label-for" for e in view["edges"])
    assert_closed(view)


def test_historical_candidates_never_claim_current_visibility(raw):
    svc = service(raw)
    req = replace(request(K.GROUNDING), current_page=page_id("demo", "settings"))
    view = svc.project(req)[K.GROUNDING].data
    assert view["closures"] and all(not c["current_visible"] for c in view["closures"])
    assert "current_bbox_missing_or_uncertain" in view["gaps"]
    assert all(not a["observation_id"] for n in view["nodes"] for values in n["fields"].values() for a in values)


def test_hidden_current_control_is_not_a_grounding_seed(raw, observations):
    observations[-1]["controls"][-1]["fields"]["visible"] = False
    bridge = prepared(raw, observations)
    toggle = control_id(bridge.current_page, "toggle")
    view = bridge.service.project(replace(request(K.GROUNDING, seed_ids=(toggle,)), current_page=bridge.current_page,
                                          observation_id="frame:2"))[K.GROUNDING].data
    assert toggle not in [c["seed"] for c in view["closures"]]


def test_verification_compares_frames_not_historical_schema(raw, observations):
    bridge = prepared(raw, observations)
    req = replace(request(K.VERIFICATION, target_fields=("state.notifications",)), current_page=bridge.current_page,
                  observation_id="frame:2")
    view = bridge.service.project(req)[K.VERIFICATION].data
    current = next(c for c in view["closures"] if c["seed"] == bridge.current_page)
    assert current["field_comparisons"] == [{"field": "state.notifications", "status": "changed"}]
    assert "verdict" not in view and "success" not in view
    only_history = service(raw).project(req)[K.VERIFICATION].data
    assert "target_fields_missing_current_evidence" in only_history["gaps"]
    observations[-1]["fields"]["state.notifications"]["value"] = False
    same = prepared(raw, observations).service.project(req)[K.VERIFICATION].data
    assert next(c for c in same["closures"] if c["seed"] == bridge.current_page)["field_comparisons"][0]["status"] == "unchanged"


def test_verification_preserves_conflicts_and_missing_conditions(raw, observations):
    observations[-1]["fields"]["state.notifications"] = {"assertions": [
        {"value": True, "source": "dom"}, {"value": False, "source": "ocr", "grade": "contradicted"}]}
    bridge = prepared(raw, observations)
    req = replace(request(K.VERIFICATION, target_fields=("state.notifications", "missing")),
                  current_page=bridge.current_page, observation_id="frame:2")
    view = bridge.service.project(req)[K.VERIFICATION].data
    node = next(n for n in view["nodes"] if n["id"] == bridge.current_page)
    assert "state.notifications" in node["conflicts"]
    assert "target_fields_missing_current_evidence" in view["gaps"]
    assert next(c for c in view["closures"] if c["seed"] == bridge.current_page)["field_comparisons"][0]["status"] == "conflict"


def test_budget_omits_whole_path_and_expands_with_revision(raw):
    svc = service(raw)
    req = replace(request(K.PLANNING, seed_ids=(page_id("demo", "settings"),)), budget=Budget(12000, 2, 10))
    view = svc.project(req)[K.PLANNING]
    assert view.token_count <= 12000
    assert len(view.data["nodes"]) <= 2
    assert not any(c.get("goal") == page_id("demo", "settings") for c in view.data["closures"])
    assert_closed(view.data)
    handle = view.data["expansion_handle"]
    full = svc.expand(handle, Budget(60000, 40, 60))
    assert any(c.get("goal") == page_id("demo", "settings") for c in full.data["closures"])
    svc.store.update(remove_nodes=(page_id("demo", "settings"),))
    with pytest.raises(StaleHandle):
        svc.expand(handle, Budget())


@pytest.mark.parametrize("limit", [500, 900, 2000, 4000, 8000])
def test_serialized_budget_is_hard_limit(raw, limit):
    svc = service(raw)
    req = replace(request(K.PLANNING), budget=Budget(limit, 40, 60))
    try:
        view = svc.project(req)[K.PLANNING]
    except BudgetTooSmall:
        assert limit < 900
    else:
        assert len(view.json.encode("utf-8")) <= limit
        assert_closed(view.data)


def test_tiny_budget_explicit_error(raw):
    with pytest.raises(BudgetTooSmall):
        service(raw).project(replace(request(K.PLANNING), budget=Budget(1, 1, 1)))


def test_snapshot_and_view_isolation(raw):
    svc = service(raw)
    snap = svc.store.read()
    with pytest.raises(TypeError):
        snap.nodes[page_id("demo", "home")].fields["new"] = ()
    view = svc.project(request(K.PLANNING))[K.PLANNING]
    decoded = view.data
    decoded["nodes"].clear()
    assert view.data["nodes"]
    svc.store.update(remove_nodes=(page_id("demo", "menu"),))
    assert page_id("demo", "menu") in snap.nodes
    assert all(e.source != page_id("demo", "menu") and e.target != page_id("demo", "menu") for e in svc.store.read().edges.values())


def test_transaction_failure_leaves_old_snapshot(raw):
    svc = service(raw)
    before = svc.store.read()
    with pytest.raises(ValueError):
        svc.store.update(edges=(Edge("bad", "missing", "also_missing", "contains"),))
    assert svc.store.read() is before


def test_one_consumer_routes_by_capability_and_action():
    router = CapabilityRouter()
    assert set(router.route(Request("fill", consumer="one_agent", action="type", capabilities=("verify",)))) == {K.GROUNDING, K.RELATION, K.VERIFICATION}
    assert router.route(Request("x", consumer="one_agent", capabilities=("navigate",))) == (K.PLANNING,)
    with pytest.raises(ValueError):
        router.route(Request("x", capabilities=("unknown",)))


def test_all_views_share_revision_and_canonical_ids(raw, observations):
    bridge = prepared(raw, observations)
    views = bridge.service.project(replace(request(K.GROUNDING), kinds=tuple(K), current_page=bridge.current_page,
                                          observation_id="frame:2"))
    assert len({v.data["revision"] for v in views.values()}) == 1
    for v in views.values():
        assert_closed(v.data)


def test_live_refresh_deletes_old_knowledge_and_resets_app(raw, observations):
    bridge = prepared(raw, observations)
    raw["nodes"] = [n for n in raw["nodes"] if n["id"] != "unrelated"]
    raw["edges"] = [e for e in raw["edges"] if e["target"] != "unrelated"]
    bridge.prepare(raw, app="demo", current_page="settings")
    assert page_id("demo", "unrelated") not in bridge.service.store.read().nodes
    assert bridge.observation_id == ""
    bridge.prepare(raw, app="another", current_page="home")
    assert not bridge._observations
    assert all(n.startswith("another/") for n in bridge.service.store.read().nodes)


def test_observation_identity_and_history_bound(raw, observations):
    bridge = prepared(raw, observations)
    before = bridge.service.store.read().revision
    bridge.prepare(raw, app="demo", current_page="settings", observation=observations[-1])
    assert bridge.service.store.read().revision == before
    with pytest.raises(ValueError, match="older"):
        bridge.prepare(raw, app="demo", current_page="settings", observation=observations[0])
    observations[-1]["fields"]["new"] = 1
    with pytest.raises(ValueError):
        bridge.prepare(raw, app="demo", current_page="settings", observation=observations[-1])
    assert bridge.service.store.read().revision == before
    observations[-1]["id"] = "frame:3"
    bridge.prepare(raw, app="demo", current_page="settings", observation=observations[-1])
    assert len(bridge._observations) == 2
    assert {o["id"] for o in bridge._observations} == {"frame:2", "frame:3"}


def test_plugin_retriever_and_policy_can_be_replaced(raw):
    class Retriever:
        def rank(self, snapshot, request, candidates):
            return [(page_id("demo", "settings"), 1)]
    svc = service(raw)
    svc.retriever = Retriever()
    view = svc.project(request(K.PLANNING))[K.PLANNING].data
    assert any(c.get("goal") == page_id("demo", "settings") for c in view["closures"])
    class Policy:
        def build(self, snapshot, request, retriever):
            return [Bundle((request.current_page,), details={"plugin": True})], []
    svc.policies[K.PLANNING] = Policy()
    assert svc.project(request(K.PLANNING))[K.PLANNING].data["closures"] == [{"plugin": True}]


def test_runtime_context_total_budget_and_disabled(raw, observations):
    assert RuntimeBridge().context("anything", consumer="x") == ""
    bridge = prepared(raw, observations)
    text = bridge.context("Notifications 通知", consumer="one", capabilities=("locate", "understand", "verify"))
    assert len(text.encode("utf-8")) <= bridge.budget.max_tokens
    assert len(bridge.last_views) == 3


def test_retriever_cannot_cross_current_page_scope(raw):
    class BadRetriever:
        def rank(self, snapshot, request, candidates):
            return [(page_id("demo", "unrelated"), 1)]
    svc = service(raw)
    svc.retriever = BadRetriever()
    with pytest.raises(ValueError, match="candidate scope"):
        svc.project(request(K.GROUNDING))
