"""Persistent core facts must outlive the screenshot/control projection window."""
from copy import deepcopy
import hashlib
import json

import pytest

from kobe_views.model import dumps, plain
from kobe_views.task_memory import TaskMemory, literal_urls
from kobe_views import AdaptiveTaskViews, Budget, RoleContract


URL = "http://teamchat.127.0.0.1.nip.io:21280/channel/general"


def evidence(text=URL, box=None):
    return {"summary": "Browser page", "elements": [
        {"text": text, "role": "addressbar", "bbox": box or [10, 10, 600, 40]}]}


def initialized(tmp_path, instruction="Read the purchasing request and save the requested file."):
    memory = TaskMemory("task035", tmp_path)
    memory.initialize(instruction, constraints=["GUI actions only", "500 action limit"],
                      delivery_files=["/home/user/Documents/purchase.xlsx"], key_semantics=["Ctrl+L selects the address bar"])
    return memory


def fact_values(packet, category):
    return [fact["value"] for fact in packet["facts"] if fact["category"] == category]


def test_literal_url_preserves_original_scheme_domain_port_and_path():
    original = f"Use `{URL}` and teamchat.127.0.0.1.nip.io:21280/channel/general."
    result = literal_urls(original)
    assert [item["original"] for item in result] == [URL, URL.removeprefix("http://")]
    assert all(item["port"] == 21280 for item in result)
    for item in result:
        assert original[item["start"]:item["end"]] == item["original"]


def test_no_default_port_or_guessed_domain_is_created(tmp_path):
    memory = initialized(tmp_path, "Open the supplied TeamChat page.")
    assert fact_values(memory.core_packet(32000), "url") == []
    memory.observe("frame-1", b"image-one", evidence("about:blank"))
    packet = memory.core_packet(32000)
    assert fact_values(packet, "url") == []
    assert any(gap["category"] == "url" for gap in packet["gaps"])
    memory.observe("frame-2", b"image-two", evidence("https://example.org/orders"))
    packet = memory.core_packet(32000)
    assert fact_values(packet, "port") == []
    assert {"category": "port", "code": "not_explicitly_provided"} in packet["gaps"]
    memory.close()


def test_original_instruction_and_contract_values_are_persisted_without_paraphrase(tmp_path):
    instruction = "目标：保留网址原文，按 Enter；交付 /home/user/report.csv。"
    memory = initialized(tmp_path, instruction)
    assert memory.snapshot.entities["task"]["type"] == "task"
    stored = json.loads((tmp_path / "instruction.json").read_text(encoding="utf-8"))
    assert stored["instruction"] == instruction
    packet = memory.core_packet(32000)
    assert fact_values(packet, "goal") == [instruction]
    assert fact_values(packet, "constraint") == [["GUI actions only", "500 action limit"]]
    assert not memory.snapshot.conflicts  # Lists are not conflicting single-value slots.
    assert "/home/user/report.csv" in fact_values(packet, "delivery_file")[0]
    memory.close()


def test_core_memory_survives_frame_eviction_restart_and_binds_screenshot_version(tmp_path):
    memory = initialized(tmp_path)
    first = memory.observe("frame-0001", b"first screenshot bytes", evidence())
    for index in range(2, 28):
        memory.observe(f"frame-{index:04}", f"image-{index}".encode(), evidence("about:blank", [index, 1, index + 10, 4]))
    packet = memory.core_packet(32000)
    url = next(fact for fact in packet["facts"] if fact["category"] == "url")
    assert url["value"] == URL
    assert url["grade"] == "candidate"
    assert url["provenance"]["frame_id"] == "frame-0001"
    assert url["provenance"]["sha256"] == hashlib.sha256(b"first screenshot bytes").hexdigest()
    assert url["provenance"]["source_version"] == first["sha256"]
    assert url["provenance"]["ref"] == first["screenshot_ref"]
    before = plain(memory.snapshot)
    memory.close()
    reopened = initialized(tmp_path)
    assert plain(reopened.snapshot) == before
    assert fact_values(reopened.core_packet(32000), "url") == [URL]
    assert reopened.current_observation is None  # Restart does not reactivate old geometry.
    reopened.close()


def test_coordinates_are_current_only_not_in_durable_graph_or_semantic_journal(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame-a", b"frame-a", evidence(URL, [17, 29, 650, 47]))
    assert memory.current_observation["evidence"]["elements"][0]["bbox"] == [17, 29, 650, 47]
    assert "bbox" not in dumps(plain(memory.snapshot))
    assert "bbox" not in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    memory.observe("frame-b", b"frame-b", evidence(URL, [22, 39, 699, 51]))
    assert memory.current_observation["evidence"]["elements"][0]["bbox"] == [22, 39, 699, 51]
    memory.close()


def test_repeated_url_deduplicates_fact_but_records_new_source(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("first", b"first", evidence())
    first_count = len([c for c in memory.snapshot.claims.values() if c["predicate"] == "resource.url_original"])
    second = memory.observe("second", b"second", evidence(URL, [5, 4, 800, 21]))
    assert len([c for c in memory.snapshot.claims.values() if c["predicate"] == "resource.url_original"]) == first_count
    assert second["recurring_claim_ids"]
    packet = memory.core_packet(32000)
    url = next(fact for fact in packet["facts"] if fact["category"] == "url")
    assert url["provenance"]["frame_id"] == "first"
    assert url["latest_provenance"]["frame_id"] == "second"
    memory.close()
    reopened = initialized(tmp_path)
    url = next(fact for fact in reopened.core_packet(32000)["facts"] if fact["category"] == "url")
    assert url["latest_provenance"]["frame_id"] == "second"
    reopened.close()


def proposal():
    return {"entities": [{"id": "customer:alice", "type": "purchase_requester", "label": "Alice"}], "claims": [
        {"id": "frame1:amount", "subject": "customer:alice", "predicate": "purchase.requested_quantity",
         "value": 3, "locator": "chat:message:1"},
        {"id": "frame1:relation", "subject": "task", "predicate": "task.requester",
         "value": "Alice", "objects": ["customer:alice"], "locator": "chat:message:1"}]}


def test_dynamic_semantic_schema_acceptance_is_candidate_and_frame_bound(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    result = memory.accept_proposals(proposal(), frame_id="frame1")
    assert result["accepted"]
    assert memory.snapshot.schema["purchase_requester"]["purchase.requested_quantity"] == ("number",)
    claim = memory.snapshot.claims["frame1:amount"]
    assert claim["mode"] == "extracted"
    assert claim["evidence"]["source"] == "visual-extractor"
    assert claim["evidence"]["ref"] == memory.current_observation["screenshot_ref"]
    rejected = memory.accept_proposals(proposal(), frame_id="old-frame")
    assert not rejected["accepted"]
    assert rejected["rejected"][0]["reason"] == "no_matching_current_frame"
    memory.close()


def test_coordinate_claim_and_dependent_are_rejected_while_semantic_fact_remains(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    proposals = proposal()
    proposals["claims"] += [
        {"id": "frame1:box", "subject": "customer:alice", "predicate": "ui.bbox", "value": [1, 2, 3, 4], "locator": "screen"},
        {"id": "frame1:plan", "subject": "task", "predicate": "plan.next", "value": "click", "mode": "derived",
         "basis": ["frame1:box"], "locator": "reasoning"}]
    result = memory.accept_proposals(proposals)
    assert result["accepted"]
    assert {entry["reason"] for entry in result["rejected"]} == {"current_frame_geometry_only", "rejected_evidence_dependency"}
    assert "frame1:box" not in memory.snapshot.claims
    assert "frame1:plan" not in memory.snapshot.claims
    assert "frame1:amount" in memory.snapshot.claims
    memory.close()


@pytest.mark.parametrize("change", [
    {"source": "user"}, {"mode": "verified"}, {"subject": "unknown"},
    {"value": float("nan")}, {"predicate": "bad predicate"},
])
def test_bad_proposal_is_atomic_and_cannot_promote_source_or_truth(tmp_path, change):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    before = memory.snapshot
    proposed = proposal()
    proposed["claims"][0].update(change)
    result = memory.accept_proposals(proposed)
    assert not result["accepted"]
    assert memory.snapshot is before
    memory.close()


def test_repeated_proposal_is_idempotent_and_conflicting_claim_identity_rejected(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    first = memory.accept_proposals(proposal())
    second = memory.accept_proposals(proposal())
    assert first["accepted"] and second["accepted"]
    assert second["accepted_claim_ids"] == []
    assert second["aliases"]["frame1:amount"] == "frame1:amount"
    changed = deepcopy(proposal())
    changed["claims"][0]["value"] = 7
    before = memory.snapshot
    assert not memory.accept_proposals(changed)["accepted"]
    assert memory.snapshot is before
    memory.close()


def test_explicit_visual_revision_and_transitive_dependency_survive_replay(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    proposed = proposal()
    proposed["claims"].append({"id": "frame1:plan", "subject": "task", "predicate": "plan.quantity",
                              "value": 3, "basis": ["frame1:amount"], "mode": "derived", "locator": "reasoning"})
    assert memory.accept_proposals(proposed)["accepted"]
    memory.observe("frame2", b"frame2", evidence("Quantity changed to 7"))
    change = {"entities": [], "claims": [{"id": "frame2:amount", "subject": "customer:alice",
              "predicate": "purchase.requested_quantity", "value": 7, "supersedes": ["frame1:amount"],
              "locator": "chat:message:2"}]}
    assert memory.accept_proposals(change)["accepted"]
    assert memory.snapshot.statuses["frame1:amount"] == "superseded"
    assert memory.snapshot.statuses["frame1:plan"] == "stale"
    before = plain(memory.snapshot)
    memory.close()
    reopened = initialized(tmp_path)
    assert plain(reopened.snapshot) == before
    reopened.close()


def test_visual_proposal_cannot_revise_user_task_contract(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    goal_id = next(cid for cid, claim in memory.snapshot.claims.items() if claim["predicate"] == "task.goal")
    proposed = {"entities": [], "claims": [{"id": "frame1:goal", "subject": "task", "predicate": "task.goal",
                 "value": "Change the user objective", "supersedes": [goal_id], "locator": "screen"}]}
    before = memory.snapshot
    assert not memory.accept_proposals(proposed)["accepted"]
    assert memory.snapshot is before
    memory.close()


def test_two_distinct_urls_do_not_create_false_resource_conflict(tmp_path):
    memory = initialized(tmp_path, f"Use {URL} and https://example.org/orders.")
    memory.observe("frame1", b"frame1", evidence())
    assert len(fact_values(memory.core_packet(32000), "url")) == 2
    assert not memory.snapshot.conflicts
    memory.close()


def test_type_and_key_semantics_are_exact_and_receipt_does_not_claim_goal_success(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    assert memory.append_action_semantics({"type": "type", "text": URL}, frame_id="frame1",
                                         receipt={"status": "success", "returncode": 0})["accepted"]
    memory.append_action_semantics({"type": "hotkey", "keys": ["ctrl", "l"]}, frame_id="frame1")
    values = fact_values(memory.core_packet(32000), "key_semantics")
    semantic = next(value for value in values if isinstance(value, dict) and value["type"] == "type")
    assert semantic["text"] == URL
    assert semantic["effect_status"] == "effect_unverified"
    assert semantic["execution_receipt"]["returncode"] == 0
    assert memory.append_action_semantics({"type": "click", "x": 20, "y": 30}, frame_id="frame1")["retained"] is False
    assert not memory.snapshot.conflicts
    memory.close()


def test_action_graph_records_every_gui_action_with_semantics_but_no_stale_coordinates(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    actions = [{"type": "move", "x": 1, "y": 2}, {"type": "click", "x": 3, "y": 4, "button": "left", "clicks": 1},
               {"type": "drag", "x": 1, "y": 2, "to_x": 8, "to_y": 9},
               {"type": "scroll", "x": 1, "y": 2, "amount": -5}, {"type": "type", "text": URL},
               {"type": "press", "key": "enter"}, {"type": "hotkey", "keys": ["ctrl", "l"]},
               {"type": "wait", "seconds": 10}, {"type": "done"}, {"type": "fail"}]
    for index, action in enumerate(actions):
        result = memory.record_action_attempt(f"action-{index}", action, f"Rationale for {action['type']}",
                                              frame_id="frame1", journal_ref="control-events.jsonl")
        assert result["accepted"]
        claim = memory.snapshot.claims[result["attempt_claim_id"]]
        assert claim["evidence"]["source"] == "agent-decision"
        assert memory.snapshot.entities[result["entity_id"]]["type"] == "action_attempt"
        semantics = claim["value"]["action_semantics"]
        assert semantics["type"] == action["type"]
        assert not set(semantics) & {"x", "y", "to_x", "to_y", "bbox"}
        assert claim["value"]["before_evidence"]["sha256"] == hashlib.sha256(b"frame1").hexdigest()
    # General actions/rationale are graph-retrievable but consume no mandatory
    # core budget.  Existing key/text core publication remains its own path.
    core = memory.core_packet(32000)
    assert not any(fact["predicate"].startswith("execution.") for fact in core["facts"])
    assert "Rationale for" not in dumps(core)
    view = AdaptiveTaskViews().project(memory.snapshot, RoleContract(
        id="execution-auditor", anchors=("task",), read_predicates=("execution.*",), max_hops=1),
        Budget(max_tokens=32000, max_nodes=32, max_edges=64))
    assert len([claim for claim in view.data["claims"] if claim["predicate"] == "execution.attempt"]) == 10
    assert not memory.snapshot.conflicts
    memory.close()


def test_action_graph_rationale_is_bounded_with_counts_and_full_raw_reference(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    reason = "原始解释" * 550
    result = memory.record_action_attempt("click-1", {"type": "click", "x": 200, "y": 300}, reason,
                                          frame_id="frame1", journal_ref="recovery/control-events.jsonl")
    assert result["accepted"]
    assert result["reason_budget"] == {"received_chars": 2200, "retained_chars": 2000, "omitted_chars": 200}
    value = memory.snapshot.claims[result["attempt_claim_id"]]["value"]
    assert value["model_rationale"] == reason[:2000]
    assert value["raw_journal_ref"] == "recovery/control-events.jsonl"
    assert "原始解释" not in dumps(memory.core_packet(32000))
    memory.close()


def test_action_graph_feedback_links_actual_receipt_to_intent_and_versions_without_goal_claim(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    attempt = memory.record_action_attempt("click-1", {"type": "click", "x": 1, "y": 2}, "Open the observed page",
                                          frame_id="frame1", journal_ref="control-events.jsonl")
    first = memory.record_action_feedback("click-1", status="success", transport_confirmed=True,
                                          effect_verified=False, evidence_ref="controller-response.json", version="receipt-v1")
    assert first["accepted"]
    claim = memory.snapshot.claims[first["feedback_claim_id"]]
    assert claim["basis"] == (attempt["attempt_claim_id"],)
    assert claim["evidence"]["source"] == "execution-feedback"
    assert claim["value"]["transport_confirmed"] is True
    assert claim["value"]["effect_status"] == "effect_unverified"
    assert "task_success" not in claim["value"]
    second = memory.record_action_feedback("click-1", status="observed", transport_confirmed=True,
                                           effect_verified=True, evidence_ref="after-frame.png", version="image-v2")
    assert second["accepted"]
    assert memory.snapshot.statuses[first["feedback_claim_id"]] == "superseded"
    assert memory.snapshot.claims[second["feedback_claim_id"]]["value"]["effect_status"] == "effect_verified"
    before = plain(memory.snapshot)
    memory.close()
    reopened = initialized(tmp_path)
    assert plain(reopened.snapshot) == before
    assert reopened.record_action_attempt("click-1", {"type": "click", "x": 1, "y": 2}, "Open the observed page",
                                          frame_id="frame1", journal_ref="control-events.jsonl")["duplicate"]
    assert reopened.record_action_feedback("click-1", status="observed", transport_confirmed=True,
                                           effect_verified=True, evidence_ref="after-frame.png", version="image-v2")["duplicate"]
    reopened.close()


def test_action_graph_rejects_unresolved_identity_and_receipt_version_reuse(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"frame1", evidence())
    assert not memory.record_action_feedback("unknown", status="unknown", transport_confirmed=False,
                                             effect_verified=False, evidence_ref="log.json", version="v1")["accepted"]
    assert not memory.record_action_attempt("x", {"type": "click", "x": 1, "y": 2}, "click",
                                            frame_id="unknown", journal_ref="log.json")["accepted"]
    assert memory.record_action_attempt("x", {"type": "click", "x": 1, "y": 2}, "click",
                                         frame_id="frame1", journal_ref="log.json")["accepted"]
    # Raw command hash guards immutable action identity without retaining or
    # reactivating the coordinates themselves in the semantic graph.
    assert not memory.record_action_attempt("x", {"type": "click", "x": 5, "y": 9}, "click",
                                            frame_id="frame1", journal_ref="log.json")["accepted"]
    assert not memory.record_action_attempt("x", {"type": "type", "text": "different action"}, "click",
                                            frame_id="frame1", journal_ref="log.json")["accepted"]
    memory.record_action_feedback("x", status="unknown", transport_confirmed=False,
                                   effect_verified=False, evidence_ref="log.json", version="v1")
    assert not memory.record_action_feedback("x", status="success", transport_confirmed=True,
                                             effect_verified=False, evidence_ref="log.json", version="v1")["accepted"]
    memory.close()


@pytest.mark.parametrize("budget", [256, 512, 2000, 8000, 32000])
def test_core_packet_accounts_utf8_bytes_and_omits_whole_facts_with_explicit_gaps(tmp_path, budget):
    instruction = "保留完整原始目标。" * 300 + URL
    memory = initialized(tmp_path, instruction)
    packet = memory.core_packet(budget)
    assert packet["used_bytes"] == len(dumps(packet).encode("utf-8")) <= budget
    goals = fact_values(packet, "goal")
    assert not goals or goals == [instruction]
    if not goals:
        assert not packet["complete"]
        assert any(gap["code"] in {"core_budget_exceeded", "core_packet_metadata_exceeds_budget"} for gap in packet["gaps"])
    memory.close()


def test_missing_contract_fields_reported_without_inventing_information(tmp_path):
    memory = TaskMemory("minimal", tmp_path)
    memory.initialize("Read the current message.")
    packet = memory.core_packet(16000)
    assert {gap["category"] for gap in packet["gaps"]} == {"url", "delivery_file", "key_semantics", "constraint"}
    assert fact_values(packet, "goal") == ["Read the current message."]
    memory.close()


def test_frame_identity_and_directory_identity_are_guarded(tmp_path):
    memory = initialized(tmp_path)
    memory.observe("frame1", b"same", evidence())
    assert memory.observe("frame1", b"same", evidence())["duplicate"]
    with pytest.raises(ValueError, match="identity"):
        memory.observe("frame1", b"different", evidence())
    with pytest.raises(ValueError, match="changed"):
        memory.initialize("Another objective")
    with pytest.raises(ValueError, match="identity"):
        TaskMemory("other-task", tmp_path)
    memory.close()


@pytest.mark.parametrize("secret", [
    "Bearer abcdefghijklmnopqrstuvwxyz1234", "sk-abcdefghijklmnopqrstuvwxyz1234",
    "https://user:password@example.org/", "https://example.org/?token=private",
])
def test_credentials_are_rejected_before_instruction_or_frame_evidence_is_written(tmp_path, secret):
    memory = TaskMemory("safe", tmp_path)
    with pytest.raises(ValueError, match="Credential"):
        memory.initialize("Use " + secret)
    assert not (tmp_path / "instruction.json").exists()
    memory.initialize("Read current information.")
    with pytest.raises(ValueError, match="Credential"):
        memory.observe("frame1", b"unsafe", evidence(secret))
    assert not list((tmp_path / "screenshots").iterdir())
    assert secret not in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    memory.close()


def test_500_frames_keep_one_url_literal_and_bounded_semantic_fact_count(tmp_path):
    memory = initialized(tmp_path)
    for index in range(500):
        memory.observe(f"frame-{index}", f"frame-{index}".encode(), evidence(URL, [index, 1, index + 10, 4]))
    assert len(memory.snapshot.entities) == 502  # task, resource, 500 observations
    assert len(memory.snapshot.claims) < 1100
    assert fact_values(memory.core_packet(32000), "url") == [URL]
    assert memory.current_observation["frame_id"] == "frame-499"
    memory.close()
