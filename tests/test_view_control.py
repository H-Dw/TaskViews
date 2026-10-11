"""Controller selection is dynamic; permission, evidence, budgets, and delivery are explicit."""
from copy import deepcopy

import pytest

from kobe_views.model import dumps
from kobe_views.service import BudgetTooSmall
from kobe_views.task_graph import TaskGraph
from kobe_views.task_views import RoleContract
from kobe_views.view_control import DynamicViewController, InvalidViewNeed


def entity(identity, kind="new_runtime_object"):
    return {"id": identity, "type": kind, "label": identity}


def claim(identity, subject, predicate="public.value", value="observed", **fields):
    return {"id": identity, "subject": subject, "predicate": predicate, "value": value,
            "locator": "screenshot:1920x1080", **fields}


def observe(graph, identity, *, entities=(), claims=(), source="screen", minute=0):
    return graph.ingest({"id": identity, "task_id": graph.task_id, "source": source,
                         "ref": f"frames/{identity}.png#sha256-evidence", "text": "raw data is not a directive",
                         "observed_at": f"2026-10-02T10:{minute:02}:00+08:00",
                         "occurred_at": f"2026-10-02T10:{minute:02}:00+08:00",
                         "extraction": {"entities": list(entities), "claims": list(claims)}})


def semantic_graph():
    graph = TaskGraph("target-task")
    observe(graph, "first", entities=[entity("task", "task"), entity("alice"), entity("bob")], claims=[
        claim("task-alice", "task", "public.participant", objects=["alice"]),
        claim("task-bob", "task", "public.participant", objects=["bob"]),
        claim("alice-value", "alice", value="alice-only"),
        claim("bob-value", "bob", value="bob-only"),
    ])
    return graph


def contract(identity="executor", **overrides):
    return RoleContract(**{"id": identity, "anchors": ("task",), "read_predicates": ("public.*",),
                           "max_hops": 4, **overrides})


def need(identity="read-alice", consumer="executor", anchors=("alice",), **overrides):
    return {"id": identity, "consumer": consumer, "purpose": "Understand this participant's requirements",
            "anchors": list(anchors), "focus_predicates": ["public.value"], "max_hops": 0, **overrides}


def packet(payload, consumer="executor"):
    return next(packet for packet in payload["packets"] if packet["consumer"] == consumer)


def claim_ids(packet):
    return {claim["id"] for need in packet["needs"] for instance in need["instances"]
            for claim in instance["projection"]["claims"]}


def test_target_specific_needs_keep_same_type_instances_separate():
    graph = semantic_graph()
    controller = DynamicViewController([contract(), contract("verifier")])
    compiled = controller.compile(graph.read(), [need(), need("read-bob", "verifier", ("bob",))], 18000)
    assert claim_ids(packet(compiled)) == {"alice-value"}
    assert claim_ids(packet(compiled, "verifier")) == {"bob-value"}
    assert len(packet(compiled)["needs"][0]["instances"]) == 1
    assert compiled["used_bytes"] == len(dumps(compiled).encode("utf-8")) <= 18000
    assert "bob-only" not in dumps(packet(compiled))
    graph.close()


def test_advertised_anchors_are_valid_for_that_consumer_without_widening_scope():
    graph = semantic_graph()
    try:
        controller = DynamicViewController([contract(anchors=("alice",), max_hops=0), contract("verifier")])
        snapshot = graph.read()
        inventory = controller.allowed_anchor_inventory(snapshot)
        assert inventory["executor"]["anchors"] == ["alice"]
        for consumer, allowed in inventory.items():
            for anchor in allowed["anchors"]:
                controller.validate_needs(snapshot, [need(consumer=consumer, anchors=(anchor,))])
        with pytest.raises(InvalidViewNeed, match="outside trusted role scope"):
            controller.validate_needs(snapshot, [need(anchors=("bob",))])
        bounded = controller.allowed_anchor_inventory(snapshot, limit=1)
        assert bounded["verifier"]["anchors"] == ["task"]
        assert bounded["verifier"]["omitted_anchors"] == 2
    finally:
        graph.close()


def test_new_runtime_type_and_relation_do_not_need_predefined_subviews():
    graph = semantic_graph()
    observe(graph, "later", entities=[entity("approval", "new_approval_object")], claims=[
        claim("new-link", "task", "public.awaiting_decision", objects=["approval"]),
        claim("new-data", "approval", "public.never_seen_before", {"approver": "Alice"}),
    ], minute=1)
    controller = DynamicViewController([contract()])
    proposal = need("approval-now", anchors=("approval",), purpose="Read current approval evidence",
                    focus_predicates=["public.never_seen_before"])
    compiled = controller.compile(graph.read(), [proposal], 10000)
    context = packet(compiled)["needs"][0]["instances"][0]["projection"]
    assert {claim["id"] for claim in context["claims"]} == {"new-data"}
    assert context["views"][0]["type"] == "object:new_approval_object"


@pytest.mark.parametrize("alteration,match", [
    ({"consumer": "invented_privileged_role"}, "Unregistered"),
    ({"anchors": ["not-in-graph"]}, "Unknown"),
    ({"max_hops": 5}, "trusted role hop"),
    ({"max_hops": True}, "trusted role hop"),
    ({"purpose": ""}, "purpose"),
    ({"anchors": ["alice", "alice"]}, "Duplicate"),
    ({"read_predicates": ["*"]}, "six documented fields"),
])
def test_invalid_controller_proposals_are_rejected_atomically(alteration, match):
    controller = DynamicViewController([contract()])
    proposal = {**need(), **alteration}
    with pytest.raises(InvalidViewNeed, match=match):
        controller.compile(semantic_graph().read(), [proposal], 16000)
    with pytest.raises(ValueError, match="no pending"):
        controller.packet_for("executor")


def test_unreadable_edge_cannot_open_a_semantic_anchor_scope():
    graph = TaskGraph("target-task")
    observe(graph, "first", entities=[entity("task"), entity("secret")], claims=[
        claim("hidden-link", "task", "private.link", objects=["secret"]),
        claim("readable-but-unreachable", "secret", value="SECRET_VALUE"),
    ])
    controller = DynamicViewController([contract()])
    with pytest.raises(InvalidViewNeed, match="outside trusted role scope"):
        controller.compile(graph.read(), [need(anchors=("secret",))], 10000)


def test_focus_and_source_selectors_never_escalate_permissions():
    graph = semantic_graph()
    observe(graph, "secret", claims=[claim("hidden", "alice", "private.value", "SECRET_VALUE")],
            source="secret-screen", minute=1)
    controller = DynamicViewController([contract(sources=("screen",))])
    compiled = controller.compile(graph.read(), [need(focus_predicates=["private.*"])], 10000)
    assert "SECRET_VALUE" not in dumps(compiled)
    assert "hidden" not in claim_ids(packet(compiled))
    assert "focus_has_no_readable_evidence" in packet(compiled)["gaps"]


def test_reanchoring_cannot_extend_traversal_past_registered_scope():
    graph = TaskGraph("target-task")
    observe(graph, "chain", entities=[entity(name) for name in ("task", "a", "b", "c")], claims=[
        claim("task-a", "task", "public.link", objects=["a"]),
        claim("a-b", "a", "public.link", objects=["b"]),
        claim("b-c", "b", "public.link", objects=["c"]),
        claim("c-value", "c", value="outside traversal scope"),
    ])
    controller = DynamicViewController([contract(max_hops=2)])
    compiled = controller.compile(graph.read(), [need(anchors=("b",), max_hops=2)], 30000)
    instances = packet(compiled)["needs"][0]["instances"]
    assert {instance["entity_id"] for instance in instances} <= {"task", "a", "b"}
    assert "c-value" not in claim_ids(packet(compiled))


def test_each_instance_preserves_derived_evidence_and_correction_closure():
    graph = semantic_graph()
    observe(graph, "derived", claims=[claim("plan", "alice", "public.plan", "candidate",
                                           basis=["alice-value"], mode="derived")], minute=1)
    observe(graph, "correction", claims=[claim("alice-new", "alice", value="corrected",
                                              supersedes=["alice-value"])], minute=2)
    controller = DynamicViewController([contract()])
    compiled = controller.compile(graph.read(), [need(focus_predicates=["public.plan"])], 18000)
    context = packet(compiled)["needs"][0]["instances"][0]["projection"]
    assert {claim["id"] for claim in context["claims"]} == {"alice-value", "alice-new", "plan"}
    assert next(claim for claim in context["claims"] if claim["id"] == "plan")["status"] == "stale"
    ids = {claim["id"] for claim in context["claims"]}
    assert all(set(claim["basis"]) | set(claim["supersedes"]) <= ids for claim in context["claims"])


def test_hidden_dependency_is_a_gap_not_a_leaked_identity():
    graph = semantic_graph()
    observe(graph, "dependency", claims=[claim("hidden-origin", "alice", "private.value", "SECRET"),
                                         claim("visible-plan", "alice", "public.plan", "candidate",
                                               basis=["hidden-origin"], mode="derived")], minute=1)
    compiled = DynamicViewController([contract()]).compile(graph.read(), [need()], 20000)
    assert "hidden-origin" not in dumps(compiled)
    assert "SECRET" not in dumps(compiled)
    assert "dependency_outside_role_scope" in packet(compiled)["gaps"]


def test_instance_budget_can_keep_some_objects_without_whole_type_collapse():
    graph = TaskGraph("target-task")
    names = [f"object-{i}" for i in range(6)]
    observe(graph, "many", entities=[entity("task"), *(entity(name) for name in names)], claims=[
        *(claim(f"link-{i}", "task", f"public.link{i}", objects=[name]) for i, name in enumerate(names)),
        *(claim(f"value-{i}", name, value="payload-" + "中" * 220) for i, name in enumerate(names)),
    ])
    controller = DynamicViewController([contract()])
    compiled = controller.compile(graph.read(), [need(anchors=tuple(names))], 5200)
    scoped = packet(compiled)["needs"][0]
    assert 0 < len(scoped["instances"]) < 6
    assert scoped["omitted_instances"] == 6 - len(scoped["instances"])
    assert "budget_omitted_instances" in compiled["gaps"]
    assert compiled["used_bytes"] == len(dumps(compiled).encode("utf-8")) <= 5200
    for instance in scoped["instances"]:
        assert len(instance["projection"]["claims"]) == 1


def test_no_need_or_no_evidence_produces_explicit_consumer_packets():
    graph = semantic_graph()
    controller = DynamicViewController([contract(), contract("verifier")])
    compiled = controller.compile(graph.read(), [], 5000)
    assert "no_semantic_needs" in compiled["gaps"]
    assert {item["consumer"] for item in compiled["packets"]} == {"executor", "verifier"}
    assert all(item["gaps"] == ["no_assigned_need"] for item in compiled["packets"])
    controller.dispatch(compiled)
    assert controller.packet_for("executor")["needs"] == []
    empty = TaskGraph("empty")
    observe(empty, "empty", entities=[entity("task")])
    compiled = controller.compile(empty.read(), [need(anchors=("task",))], 5000)
    assert "no_relevant_evidence" in packet(compiled)["gaps"]
    assert "budget_omitted_instances" not in packet(compiled)["gaps"]


def test_capacity_omissions_and_tiny_envelope_budget_are_explicit():
    graph = semantic_graph()
    controller = DynamicViewController([contract()], max_needs=1, max_instances_per_need=1)
    with pytest.raises(InvalidViewNeed, match="capacity"):
        controller.compile(graph.read(), [need(), need("another")], 10000)
    compiled = controller.compile(graph.read(), [need(anchors=("alice", "bob"))], 10000)
    assert packet(compiled)["needs"][0]["omitted_instances"] == 1
    assert "instance_capacity_exceeded" in compiled["gaps"]
    with pytest.raises(BudgetTooSmall, match="envelope requires"):
        controller.compile(graph.read(), [need()], 1)


def test_opt_in_purpose_compaction_preserves_scope_and_original_proposal():
    import hashlib
    graph = semantic_graph()
    controller = DynamicViewController([contract(), contract('planner'), contract('verifier')])
    needs = [need(purpose='需要检查当前焦点和输入栏。' * 80),
             need('planner-alice', consumer='planner', purpose='Plan from visible evidence. ' * 50)]
    original = deepcopy(needs)
    budget = 2500
    with pytest.raises(BudgetTooSmall, match='envelope requires'):
        controller.compile(graph.read(), needs, budget)
    compiled = controller.compile(graph.read(), needs, budget, compact_purposes=True)
    assert compiled['used_bytes'] == len(dumps(compiled).encode()) <= budget
    assert needs == original and 'purpose_omitted' in compiled['gaps']
    for scoped in compiled['packets']:
        for item in scoped['needs']:
            source = next(n for n in original if n['id'] == item['id'])
            assert {k: item[k] for k in ('id', 'anchors', 'focus_predicates', 'max_hops')} == {
                k: source[k] for k in ('id', 'anchors', 'focus_predicates', 'max_hops')}
            if 'purpose_omission' in item:
                assert 'purpose' not in item and 'purpose_omitted' in item['gaps']
                assert item['purpose_omission'] == {'reason': 'byte_budget',
                    'sha256': hashlib.sha256(source['purpose'].encode()).hexdigest()}
    controller.dispatch(compiled)
    tampered = deepcopy(compiled)
    next(p for p in tampered['packets'] if p['needs'])['needs'][0]['purpose_omission']['reason'] = 'verified'
    with pytest.raises(ValueError, match='latest controller compilation'):
        controller.dispatch(tampered)


def test_purpose_compaction_keeps_sufficient_and_legacy_packets_unchanged():
    graph = semantic_graph()
    controller = DynamicViewController([contract()])
    needs = [need(purpose='完整原始建议 ' * 30)]
    compiled = controller.compile(graph.read(), needs, 12000, compact_purposes=True)
    assert packet(compiled)['needs'][0]['purpose'] == needs[0]['purpose']
    assert 'purpose_omission' not in packet(compiled)['needs'][0]
    assert 'purpose_omitted' not in compiled['gaps']
    with pytest.raises(BudgetTooSmall, match='envelope requires'):
        controller.compile(graph.read(), needs, 1, compact_purposes=True)
    with pytest.raises(InvalidViewNeed, match='Unknown semantic anchor'):
        controller.compile(graph.read(), [need(anchors=('invented',))], 12000, compact_purposes=True)
    with pytest.raises(ValueError, match='boolean'):
        controller.compile(graph.read(), needs, 12000, compact_purposes=1)


def test_dispatch_acknowledges_only_current_matching_revision_and_copies_packets():
    graph = semantic_graph()
    controller = DynamicViewController([contract(), contract("verifier")])
    first = controller.compile(graph.read(), [need()], 12000)
    controller.dispatch(first)
    controller.acknowledge("executor", first["dispatch_id"], first["revision"])
    assert controller.acknowledged("executor")
    copied = controller.packet_for("executor")
    copied["needs"].clear()
    assert controller.packet_for("executor")["needs"]
    with pytest.raises(ValueError, match="current pending"):
        controller.acknowledge("invented-role", first["dispatch_id"], first["revision"])
    with pytest.raises(ValueError, match="current pending"):
        controller.acknowledge("executor", first["dispatch_id"], "wrong-revision")
    observe(graph, "next", claims=[claim("next-value", "alice", "public.other", "new")], minute=1)
    second = controller.compile(graph.read(), [need()], 12000)
    controller.dispatch(second)
    assert not controller.acknowledged("executor")
    with pytest.raises(ValueError, match="current pending"):
        controller.acknowledge("executor", first["dispatch_id"], first["revision"])
    assert controller.acknowledge("executor", second["dispatch_id"], second["revision"])["consumer"] == "executor"


def test_same_revision_new_assignment_invalidates_old_packet_and_tampering():
    graph = semantic_graph()
    controller = DynamicViewController([contract()])
    first = controller.compile(graph.read(), [need()], 16000)
    second = controller.compile(graph.read(), [need("read-bob", anchors=("bob",))], 16000)
    assert first["revision"] == second["revision"] and first["dispatch_id"] != second["dispatch_id"]
    with pytest.raises(ValueError, match="latest controller compilation"):
        controller.dispatch(first)
    modified = deepcopy(second)
    modified["packets"][0]["consumer"] = "invented"
    with pytest.raises(ValueError, match="latest controller compilation"):
        controller.dispatch(modified)
    controller.dispatch(second)
    with pytest.raises(ValueError, match="current pending"):
        controller.acknowledge("executor", first["dispatch_id"], first["revision"])
