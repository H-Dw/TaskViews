"""Recovery operates on verified effects/contracts, not reversed GUI clicks."""
from copy import deepcopy

import pytest

from kobe_views.recovery import RecoveryConflict, RecoveryJournal


def observation(version="v0", *, value=0, resource="browser://task", **facts):
    return {"source": "trusted-observer", "ref": f"screenshots/{version}.png", "version": version,
            "resource": resource, "facts": {"task": "test", "value": value, **facts}}


def proof(state):
    return {k: state[k] for k in ("source", "ref", "version")}


def make_journal(path=None):
    journal = RecoveryJournal("test", path)
    journal.checkpoint("stage-ready", observation(), prerequisites={"facts": {"task": "test"}}, verified=True)
    return journal


def verified_action(journal, aid, before, after, *, barrier=None, compensation=True, action=None):
    journal.record_action(aid, action if action is not None else {"type": "press", "key": "enter"},
                          before, barrier=barrier)
    journal.receipt(aid, {"status": "success", "returncode": 0}, confirmed=True)
    journal.observe_effect(aid, after, verified=True)
    if compensation:
        journal.register_compensation(aid, {"type": "hotkey", "keys": ["ctrl", "z"]},
                                      guard={"resource": after["resource"], "facts": {"value": after["facts"]["value"]}},
                                      postcondition={"resource": before["resource"],
                                                     "facts": {"value": before["facts"]["value"]}},
                                      evidence=proof(after), verified=True)


def test_receipt_does_not_verify_actual_effect():
    journal = make_journal()
    journal.record_action("a1", {"type": "click", "x": 10, "y": 20}, observation())
    journal.receipt("a1", {"status": "success", "returncode": 0}, confirmed=True)
    assert journal.action("a1")["status"] == "transport_confirmed"
    assert not journal.action("a1")["effect_verified"]
    assert "effect_unverified:a1" in journal.plan_recovery(observation("v1"))["reasons"]
    with pytest.raises(ValueError, match="unverified"):
        journal.checkpoint("unproven-stage", observation("v1"), verified=True)


def test_inverse_order_and_one_at_a_time_verified_progress():
    journal = make_journal()
    s0, s1, s2 = observation(), observation("v1", value=1), observation("v2", value=2)
    verified_action(journal, "a1", s0, s1)
    verified_action(journal, "a2", s1, s2)
    assert journal.plan_recovery(s2)["action_ids"] == ["a2", "a1"]
    inverse = journal.next_compensation(s2)
    assert inverse["original_action_id"] == "a2"
    assert inverse["action"] == {"type": "hotkey", "keys": ["ctrl", "z"]}
    journal.compensation_receipt(inverse["id"], {"status": "success"}, confirmed=True)
    # Controller success still cannot advance to the next inverse.
    assert journal.next_compensation(s2)["status"] == "blocked"
    journal.observe_compensation(inverse["id"], observation("v3", value=1), verified=True)
    inverse2 = journal.next_compensation(observation("v3", value=1))
    assert inverse2["original_action_id"] == "a1"
    journal.observe_compensation(inverse2["id"], observation("v4"), verified=True)
    assert journal.state()["recovery"]["status"] == "complete"
    assert journal.action("a1")["compensated"] and journal.action("a2")["compensated"]


def test_raw_clicks_have_no_implicit_reverse():
    journal = make_journal()
    verified_action(journal, "a1", observation(), observation("v1", value=1), compensation=False,
                    action={"type": "click", "x": 10, "y": 20})
    plan = journal.plan_recovery(observation("v1", value=1))
    assert plan["status"] == "blocked"
    assert plan["reasons"] == ["no_verified_compensation:a1"]
    assert journal.next_compensation(observation("v1", value=1))["action"] is None


@pytest.mark.parametrize("barrier", ["message_sent", "submitted", "external_approval"])
def test_irreversible_barrier_blocks_older_stage(barrier):
    journal = make_journal()
    verified_action(journal, "a1", observation(), observation("v1", value=1), barrier=barrier)
    plan = journal.plan_recovery(observation("v1", value=1))
    assert any(barrier in r for r in plan["reasons"])
    assert journal.next_compensation(observation("v1", value=1))["action"] is None


def test_newer_verified_stage_can_avoid_crossing_earlier_barrier():
    journal = make_journal()
    s1, s2 = observation("v1", value=1), observation("v2", value=2)
    verified_action(journal, "sent", observation(), s1, barrier="message_sent")
    journal.checkpoint("after-send", s1, prerequisites={"facts": {"task": "test"}}, verified=True)
    verified_action(journal, "a2", s1, s2)
    plan = journal.plan_recovery(s2)
    assert plan["checkpoint_id"] == "after-send"
    assert plan["action_ids"] == ["a2"] and plan["status"] == "ready"


def test_invalid_latest_checkpoint_prerequisites_select_earlier_valid_stage():
    journal = make_journal()
    s1 = observation("v1", value=1, account="A")
    verified_action(journal, "a1", observation(), s1)
    journal.checkpoint("account-A", s1, prerequisites={"facts": {"account": "A"}}, verified=True)
    plan = journal.plan_recovery(observation("v2", value=1, account="B"))
    assert plan["checkpoint_id"] == "stage-ready"
    assert plan["action_ids"] == ["a1"]


def test_changed_checkpoint_prerequisites_block_before_inverse_dispatch():
    journal = make_journal()
    verified_action(journal, "a1", observation(), observation("v1", value=1))
    journal.plan_recovery(observation("v1", value=1))
    changed = observation("v2", value=1)
    changed["facts"]["task"] = "other"
    answer = journal.next_compensation(changed)
    assert answer["status"] == "blocked"
    assert answer["reasons"] == ["checkpoint_prerequisites_changed"]
    assert journal.state()["compensation_count"] == 0


def test_exact_resource_and_expected_state_guard_before_inverse():
    journal = make_journal()
    verified_action(journal, "a1", observation(), observation("v1", value=1))
    journal.plan_recovery(observation("v1", value=1))
    answer = journal.next_compensation(observation("v2", value=1, resource="browser://other"))
    assert answer["status"] == "blocked"
    assert answer["reasons"] == ["compensation_guard_changed:a1"]
    assert journal.next_compensation(observation("v2", value=99))["status"] == "blocked"


def test_geometry_is_bound_to_registration_frame():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    journal.register_compensation("a1", {"type": "click", "x": 10, "y": 20},
                                  guard={"resource": after["resource"], "facts": {"value": 1}},
                                  postcondition={"resource": after["resource"], "facts": {"value": 0}},
                                  evidence=proof(after), verified=True)
    journal.plan_recovery(after)
    answer = journal.next_compensation(observation("v2", value=1))
    assert answer["reasons"] == ["compensation_geometry_stale:a1"]
    assert journal.next_compensation(after)["status"] == "ready"


def test_unverified_model_compensation_is_not_authority():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after, compensation=False)
    journal.register_compensation("a1", {"type": "press", "key": "esc"},
                                  guard={"resource": after["resource"]},
                                  postcondition={"resource": after["resource"]}, evidence=proof(after), verified=False)
    assert journal.plan_recovery(after)["status"] == "blocked"
    assert journal.next_compensation(after)["action"] is None


def test_revoke_compensation_authority_after_plan():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    journal.plan_recovery(after)
    journal.register_compensation("a1", {"type": "press", "key": "esc"},
                                  guard={"resource": after["resource"]},
                                  postcondition={"resource": after["resource"]}, evidence=proof(after), verified=False)
    assert journal.next_compensation(after)["reasons"] == ["compensation_authority_changed:a1"]


def test_pending_inverse_survives_restart_and_is_never_dispatched_twice(tmp_path):
    path = tmp_path / "recovery.sqlite"
    journal = make_journal(path)
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    journal.plan_recovery(after)
    inverse = journal.next_compensation(after)
    journal.close()  # Crash window: inverse may have executed, receipt was lost.
    restarted = RecoveryJournal("test", path)
    assert restarted.next_compensation(after)["status"] == "blocked"
    assert restarted.state()["compensation_count"] == 1
    assert restarted.fail_gate(after, resource_verified=True)["action"] == "replan"
    restarted.observe_compensation(inverse["id"], observation("v2"), verified=True)
    snapshot = restarted.snapshot()
    assert snapshot["recovery"]["status"] == "complete"
    assert snapshot["compensations"][inverse["id"]]["receipt"] is None


def test_compensation_needs_fresh_matching_verified_postcondition():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    inverse = journal.next_compensation(after)
    with pytest.raises(ValueError, match="fresh verified matching"):
        journal.observe_compensation(inverse["id"], after, verified=True)
    with pytest.raises(ValueError, match="fresh verified matching"):
        journal.observe_compensation(inverse["id"], observation("v2", value=99), verified=True)
    journal.observe_compensation(inverse["id"], observation("v2", value=99), verified=False)
    assert journal.next_compensation(observation("v2", value=99))["status"] == "blocked"
    journal.observe_compensation(inverse["id"], observation("v3"), verified=True)
    with pytest.raises(ValueError, match="not the current"):
        journal.observe_compensation(inverse["id"], observation("v4"), verified=True)


def test_effect_verification_can_resolve_missing_forward_receipt():
    journal = make_journal()
    journal.record_action("a1", {"type": "press", "key": "enter"}, observation())
    journal.observe_effect("a1", observation("v1", value=1), verified=True)
    row = journal.action("a1")
    assert row["effect_verified"] and not row["transport_confirmed"] and row["receipt"] is None


def test_unknown_effect_prevents_any_recovery_dispatch():
    journal = make_journal()
    after = observation("v1", value=1)
    journal.record_action("a1", {"type": "press", "key": "enter"}, observation())
    journal.receipt("a1", None, confirmed=False)
    journal.register_compensation("a1", {"type": "press", "key": "esc"},
                                  guard={"resource": after["resource"], "facts": {"value": 1}},
                                  postcondition={"resource": after["resource"], "facts": {"value": 0}},
                                  evidence=proof(after), verified=True)
    assert journal.plan_recovery(after)["status"] == "blocked"
    assert journal.fail_gate(after, resource_verified=True)["action"] == "replan"


def test_fail_gate_checks_gaps_then_resource_then_safe_path():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    assert journal.fail_gate(after, gaps=["missing_url"], resource_verified=True)["status"] == "evidence_gap"
    assert journal.fail_gate(after)["status"] == "resource_unverified"
    gate = journal.fail_gate(after, resource_verified=True)
    assert gate["action"] == "recover" and gate["status"] == "recovery_ready"
    assert journal.state()["compensation_count"] == 0  # Gate does not execute or even dispatch an inverse.


def test_fail_gate_reports_irreversible_barrier_and_preserves_log():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "sent", observation(), after, barrier="message_sent")
    gate = journal.fail_gate(after, resource_verified=True)
    assert gate["action"] == "fail" and gate["status"] == "no_safe_recovery"
    assert "recovery_barrier:sent:message_sent" in gate["reasons"]
    assert journal.action("sent")["after_state"] == after


def test_completed_inverse_is_not_repeated_on_a_new_failure():
    journal = make_journal()
    s1 = observation("v1", value=1)
    verified_action(journal, "attempt-one", observation(), s1)
    inverse = journal.next_compensation(s1)
    journal.observe_compensation(inverse["id"], observation("v2"), verified=True)
    s3 = observation("v3", value=3)
    verified_action(journal, "attempt-two", observation("v2"), s3)
    plan = journal.plan_recovery(s3)
    assert plan["action_ids"] == ["attempt-two"]


def test_forward_actions_cannot_interleave_active_recovery():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    journal.plan_recovery(after)
    with pytest.raises(ValueError, match="active recovery"):
        journal.record_action("illegal", {"type": "wait", "seconds": 1}, after)


@pytest.mark.parametrize("value", [None, {}, {"source": "observer", "ref": "frame.png", "resource": "r"},
                                  {"source": "observer", "ref": "frame.png", "version": "v", "resource": "r",
                                   "facts": []}])
def test_unbound_observations_are_rejected(value):
    journal = RecoveryJournal("test")
    with pytest.raises(ValueError):
        journal.record_action("a1", {"type": "wait", "seconds": 1}, value)
    assert journal.state()["sequence"] == 0


def test_false_verification_is_not_coerced_from_text():
    journal = make_journal()
    journal.record_action("a1", {"type": "wait", "seconds": 1}, observation())
    with pytest.raises(ValueError):
        journal.observe_effect("a1", observation("v1"), verified="true")
    with pytest.raises(ValueError):
        journal.receipt("a1", {}, confirmed=1)


@pytest.mark.parametrize("action", [{"type": "macro", "actions": []}, {"type": "click", "actions": []},
                                    {"type": "done"}, {"type": "fail"}])
def test_multi_action_or_terminal_compensations_are_rejected(action):
    journal = make_journal()
    journal.record_action("a1", {"type": "wait", "seconds": 1}, observation())
    with pytest.raises(ValueError):
        journal.register_compensation("a1", action, guard={"resource": "browser://task"},
                                      postcondition={"resource": "browser://task"}, evidence=proof(observation()),
                                      verified=True)


def test_caller_mutation_cannot_change_journal_or_returned_snapshot():
    journal = make_journal()
    before = observation()
    action = {"type": "hotkey", "keys": ["ctrl", "a"]}
    journal.record_action("a1", action, before)
    action["keys"].append("z")
    before["facts"]["value"] = 99
    copied = journal.snapshot()
    copied["actions"][0]["action"]["keys"].append("z")
    assert journal.action("a1")["action"]["keys"] == ["ctrl", "a"]
    assert journal.action("a1")["before_state"]["facts"]["value"] == 0


def test_journal_is_task_bound_and_duplicate_ids_are_atomic(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = make_journal(path)
    journal.record_action("a1", {"type": "wait", "seconds": 1}, observation())
    before = deepcopy(journal.snapshot())
    with pytest.raises(ValueError, match="already recorded"):
        journal.record_action("a1", {"type": "wait", "seconds": 1}, observation())
    assert journal.snapshot() == before
    journal.close()
    with pytest.raises(ValueError, match="another task"):
        RecoveryJournal("other", path)


def test_cross_writer_conflict_does_not_mutate_memory(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = RecoveryJournal("test", path)
    second = RecoveryJournal("test", path)
    first.record_action("a1", {"type": "wait", "seconds": 1}, observation())
    with pytest.raises(RecoveryConflict):
        second.record_action("a2", {"type": "wait", "seconds": 1}, observation())
    assert second.state()["action_count"] == 0


def test_action_and_payload_budgets_are_explicit_and_atomic():
    journal = RecoveryJournal("test", max_actions=1)
    journal.record_action("a1", {"type": "wait", "seconds": 1}, observation())
    with pytest.raises(ValueError, match="budget exhausted"):
        journal.record_action("a2", {"type": "wait", "seconds": 1}, observation())
    before = journal.state()["sequence"]
    with pytest.raises(ValueError, match="byte budget"):
        journal.receipt("a1", {"payload": "x" * 70000}, confirmed=True)
    assert journal.state()["sequence"] == before


def test_absent_or_unverified_checkpoint_has_no_recovery_path():
    journal = RecoveryJournal("test")
    assert journal.plan_recovery(observation())["status"] == "unavailable"
    journal.checkpoint("candidate", observation(), verified=False)
    assert journal.plan_recovery(observation())["status"] == "unavailable"


def test_only_current_compensation_can_receive_effect_verification():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    inverse = journal.next_compensation(after)
    with pytest.raises(ValueError, match="not the current"):
        journal.observe_compensation("unknown", observation("v2"), verified=True)
    assert journal.state()["recovery"]["pending"] == inverse["id"]


def test_individual_inverses_do_not_prove_target_stage_automatically(tmp_path):
    path = tmp_path / "recovery.sqlite"
    journal = make_journal(path)
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    # This inverse has a weaker postcondition than the complete stage checkpoint.
    journal.register_compensation("a1", {"type": "press", "key": "esc"},
                                  guard={"resource": after["resource"], "facts": {"value": 1}},
                                  postcondition={"resource": after["resource"], "facts": {"dialog_closed": True}},
                                  evidence=proof(after), verified=True)
    inverse = journal.next_compensation(after)
    journal.observe_compensation(inverse["id"], observation("v2", value=1, dialog_closed=True), verified=True)
    assert journal.state()["recovery"]["status"] == "awaiting_checkpoint_verification"
    assert journal.fail_gate(observation("v2", value=1), resource_verified=True)["action"] == "replan"
    journal.close()
    journal = RecoveryJournal("test", path)
    assert journal.next_compensation(observation("v2", value=1))["action"] is None
    with pytest.raises(ValueError, match="matching stage"):
        journal.verify_recovery_checkpoint(observation("v3", value=1), verified=True)
    journal.verify_recovery_checkpoint(observation("v4"), verified=True)
    assert journal.state()["recovery"]["status"] == "complete"


@pytest.mark.parametrize("weak", ["guard", "postcondition"])
def test_resource_identity_alone_cannot_authorize_semantic_undo(weak):
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after, compensation=False)
    guards = {"guard": {"resource": after["resource"], "facts": {"value": 1}},
              "postcondition": {"resource": after["resource"], "facts": {"value": 0}}}
    guards[weak].pop("facts")
    with pytest.raises(ValueError, match="nonempty semantic"):
        journal.register_compensation("a1", {"type": "hotkey", "keys": ["ctrl", "z"]},
                                      evidence=proof(after), verified=True, **guards)
    assert journal.action("a1")["compensation"] is None


def test_fail_gate_rechecks_current_guard_before_claiming_recovery_ready():
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after)
    gate = journal.fail_gate(observation("v2", value=99), resource_verified=True)
    assert gate["action"] == "replan" and gate["status"] == "recovery_blocked"
    assert gate["reasons"] == ["compensation_guard_changed:a1"]
    assert journal.state()["compensation_count"] == 0


def test_trusted_proof_can_classify_unknown_effect_as_reversible(tmp_path):
    path = tmp_path / "recovery.sqlite"
    journal = make_journal(path)
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after, barrier="unclassified_or_external_effect")
    assert journal.plan_recovery(after)["status"] == "blocked"
    classified = journal.attest_reversible("a1", proof(after))
    assert classified["barrier"] is None
    assert classified["initial_barrier"] == "unclassified_or_external_effect"
    assert classified["classification_evidence"] == proof(after)
    sequence = journal.state()["sequence"]
    journal.attest_reversible("a1", proof(after))
    assert journal.state()["sequence"] == sequence  # Idempotent exact attestation.
    journal.close()
    reopened = RecoveryJournal("test", path)
    assert reopened.action("a1")["initial_barrier"] == "unclassified_or_external_effect"
    assert reopened.fail_gate(after, resource_verified=True)["action"] == "recover"


@pytest.mark.parametrize("barrier", ["message_sent", "submitted", "external_approval", "unknown_remote_effect"])
def test_irreversible_classification_cannot_be_erased_even_with_inverse_contract(barrier):
    journal = make_journal()
    after = observation("v1", value=1)
    verified_action(journal, "a1", observation(), after, barrier=barrier)
    with pytest.raises(ValueError, match="irreversible barriers remain"):
        journal.attest_reversible("a1", proof(after))
    assert journal.action("a1")["barrier"] == barrier


def test_reversibility_requires_effect_receipt_contract_and_same_proof():
    journal = make_journal()
    after = observation("v1", value=1)
    journal.record_action("a1", {"type": "press", "key": "enter"}, observation(),
                          barrier="unclassified_or_external_effect")
    with pytest.raises(ValueError, match="confirmed transport"):
        journal.attest_reversible("a1", proof(after))
    journal.receipt("a1", {"status": "success"}, confirmed=True)
    journal.observe_effect("a1", after, verified=True)
    with pytest.raises(ValueError, match="verified compensation"):
        journal.attest_reversible("a1", proof(after))
    journal.register_compensation("a1", {"type": "press", "key": "esc"},
                                  guard={"resource": after["resource"], "facts": {"value": 1}},
                                  postcondition={"resource": after["resource"], "facts": {"value": 0}},
                                  evidence=proof(after), verified=True)
    with pytest.raises(ValueError, match="must match"):
        journal.attest_reversible("a1", proof(observation("v2", value=1)))
    assert journal.action("a1")["barrier"] == "unclassified_or_external_effect"


def test_changing_verifier_name_does_not_make_before_image_a_fresh_after_state():
    journal = make_journal()
    before = observation()
    journal.record_action("a1", {"type": "press", "key": "enter"}, before)
    forged_freshness = deepcopy(before)
    forged_freshness["source"] = "second-verifier"
    with pytest.raises(ValueError, match="fresh observation"):
        journal.observe_effect("a1", forged_freshness, verified=True)
