from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from ui_kobe.osworld.agent import OSWorldAgent
from ui_kobe.osworld.feedback import action_owner, effect_feedback, install_feedback_hooks
from ui_kobe.osworld.task_control import TaskControlBlocked


URL = "http://example.test:21280/channel/general"


def screenshot(color="white"):
    buffer = BytesIO()
    Image.new("RGB", (800, 600), color).save(buffer, format="PNG")
    return buffer.getvalue()


def config(path, **settings):
    return {"agent": {"context_bytes": 64000, "retained_frames": 2,
            "task_control": {"enabled": True, "memory_dir": str(path), **settings}}}


class RoleClient:
    def __init__(self, *, fail=False):
        self.stats = {"requests": 0}
        self.requests = []
        self.fail = fail
        self.verifier_failed = False
        self.action = {"type": "move", "x": 10, "y": 20}

    def create(self, **kwargs):
        self.requests.append(kwargs)
        self.stats["requests"] += 1
        prompt = kwargs["messages"][0]["content"]
        if "Extract visible evidence" in prompt:
            request = json.loads(kwargs["messages"][1]["content"][0]["text"])
            frame = request["role_evidence"]["frame_id"]
            body = {"summary": "Task resources visible", "elements": [], "semantics": {
                "entities": [{"id": "buyer", "type": "person", "label": "buyer"},
                             {"id": "quote", "type": "target_specific_document", "label": "quote.csv"}],
                "claims": [{"id": frame + ":buyer", "subject": "buyer", "predicate": "person.task",
                            "value": "buyer", "objects": ["task"], "locator": "visible buyer"},
                           {"id": frame + ":quote", "subject": "quote", "predicate": "quote.amount",
                            "value": "10", "objects": ["task"], "locator": "visible quote"}]}}
        elif "You are the task controller" in prompt:
            body = {"stage": "collect quotes", "needs": [
                {"id": "who", "consumer": "planner", "purpose": "buyer requirements", "anchors": ["buyer"],
                 "focus_predicates": ["person.*"], "max_hops": 0},
                {"id": "price", "consumer": "verifier", "purpose": "quote price", "anchors": ["quote"],
                 "focus_predicates": ["quote.*"], "max_hops": 0},
                {"id": "operate", "consumer": "executor", "purpose": "next GUI step", "anchors": ["task"],
                 "focus_predicates": ["task.*"], "max_hops": 0}]}
        elif "subordinate task planner" in prompt:
            body = {"advice": "Check the buyer requirements", "needed_evidence": []}
        elif "subordinate visual verifier" in prompt:
            body = {"assessment": "failed" if self.verifier_failed else "verified",
                    "quotes": ["Task resources visible"], "gaps": []}
        else:
            body = {"reason": "next step", "action": {"type": "fail"} if self.fail
                    else self.action}
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
                        message=SimpleNamespace(content=json.dumps(body)))])

    def close(self):
        pass


def test_live_path_distributes_target_specific_role_views_and_core_first(tmp_path):
    client = RoleClient()
    agent = OSWorldAgent(config(tmp_path), client=client)
    response, actions = agent.predict(f"Read quotes at {URL}", {"screenshot": screenshot()})
    assert "moveTo" in actions[0] and json.loads(response)["action"]["type"] == "move"
    assert len(client.requests) == 5
    role_inputs = [json.loads(r["messages"][1]["content"][0]["text"]) for r in client.requests[2:4]]
    planner, verifier = role_inputs
    assert planner["assigned_views"]["consumer"] == "planner"
    assert planner["assigned_views"]["needs"][0]["anchors"] == ["buyer"]
    assert verifier["assigned_views"]["needs"][0]["anchors"] == ["quote"]
    assert all(URL in json.dumps(r["mandatory_core"]) for r in role_inputs)
    trace = agent.last_trace["task_control"]
    assert trace["subagents"]["verifier"]["grade"] == "model_proposal"
    assert agent.control.views.acknowledged("executor")
    assert agent.control.recovery.state()["checkpoint_count"] == 1
    assert not agent.control.recovery.snapshot()["checkpoints"][0]["verified"]
    agent.close()


def test_missing_optional_core_does_not_prevent_first_observation(tmp_path):
    client = RoleClient()
    agent = OSWorldAgent(config(tmp_path), client=client)
    agent.predict("Read the current quote", {"screenshot": screenshot()})
    assert len(client.requests) == 5
    assert any(g["code"] == "not_explicitly_provided" for g in agent.control.last_trace["core"]["gaps"])
    agent.close()


def test_url_beyond_control_budget_still_enters_mandatory_core(tmp_path):
    class OverflowClient(RoleClient):
        def create(self, **kwargs):
            reply = super().create(**kwargs)
            if "Extract visible evidence" in kwargs["messages"][0]["content"]:
                body = json.loads(reply.choices[0].message.content)
                body["elements"] = [{"text": "button", "role": "button", "bbox": [1, 1, 20, 20]} for _ in range(26)]
                body["elements"].append({"text": URL.removeprefix("http://"), "role": "addressbar", "bbox": [1, 1, 700, 25]})
                reply.choices[0].message.content = json.dumps(body)
            return reply
    agent = OSWorldAgent(config(tmp_path), client=OverflowClient())
    agent.predict("Read the quote", {"screenshot": screenshot()})
    assert len(agent.last_trace["evidence"]["elements"]) == 24
    core = agent.control.memory.core_packet(64000)
    assert any(f["category"] == "url" and f["value"] == URL.removeprefix("http://") for f in core["facts"])
    assert any(f["category"] == "port" and f["value"] == 21280 for f in core["facts"])
    agent.close()


def test_receipt_is_durable_but_model_verifier_cannot_promote_effect(tmp_path):
    agent = OSWorldAgent(config(tmp_path), client=RoleClient())
    agent.predict(f"Read {URL}", {"screenshot": screenshot()})
    pending = agent.control.pending["id"]
    agent.feedback({"controller_result": {"status": "success", "returncode": 0}, "screenshot": screenshot("blue")})
    row = agent.control.recovery.action(pending)
    assert row["transport_confirmed"] and not row["effect_verified"]
    assert row["after_state"]["ref"].endswith(".png")
    assert agent.control.trace_path.exists()
    snapshot = agent.control.memory.read()
    intent = next(c for c in snapshot.claims.values() if c["predicate"] == "execution.attempt")
    receipt = next(c for c in snapshot.claims.values() if c["predicate"] == "execution.feedback")
    assert intent["value"]["action_semantics"] == {"type": "move"}
    assert intent["value"]["model_rationale"] == "next step"
    assert intent["value"]["raw_journal_ref"] == str(agent.control.trace_path)
    assert list(receipt["basis"]) == [intent["id"]]
    assert receipt["value"]["transport_confirmed"] and not receipt["value"]["effect_verified"]
    assert all(not f["predicate"].startswith("execution.")
               for f in agent.control.memory.core_packet(64000)["facts"])
    agent.close()


def test_core_survives_eviction_reset_and_process_restart(tmp_path):
    original = f"Read {URL} and save quote.csv"
    agent = OSWorldAgent(config(tmp_path, delivery_files=["quote.csv"], constraints=["GUI only"]), client=RoleClient())
    for _ in range(4):
        agent.predict(original, {"screenshot": screenshot()})
        agent.feedback({"controller_result": {"status": "success", "returncode": 0}, "screenshot": screenshot()})
    assert len(agent.frames) == 2
    old_frame = agent.control.memory.current_observation["frame_id"]
    path = agent.control.memory.directory
    agent.reset()
    agent.predict(original, {"screenshot": screenshot()})
    assert agent.control.memory.directory == path
    assert agent.control.memory.current_observation["frame_id"] != old_frame
    core = agent.control.memory.core_packet(64000)
    assert any(f["category"] == "port" and f["value"] == 21280 for f in core["facts"])
    assert any(f["category"] == "delivery_file" and "quote.csv" in f["value"] for f in core["facts"])
    agent.close()


def test_fail_checks_resource_and_evidence_with_bounded_review(tmp_path):
    client = RoleClient(fail=True)
    agent = OSWorldAgent(config(tmp_path), client=client)
    for _ in range(2):
        response, actions = agent.predict(f"Read {URL}", {"screenshot": screenshot()})
        assert json.loads(response)["action"]["type"] == "wait" and actions != ["FAIL"]
        assert agent.last_trace["task_control"]["original_decision"]["action"]["type"] == "fail"
        agent.feedback({"controller_result": {"status": "success", "returncode": 0}, "screenshot": screenshot()})
    agent.reset()  # The review limit is persistent, not a fresh limit per worker.
    with pytest.raises(TaskControlBlocked, match="FAIL review limit"):
        agent.predict(f"Read {URL}", {"screenshot": screenshot()})
    assert agent.last_trace["task_control"]["status"] == "blocked_evidence_or_recovery"
    agent.close()


def test_hard_core_overflow_stops_before_api_and_records_gap(tmp_path):
    client = RoleClient()
    data = config(tmp_path)
    data["agent"]["context_bytes"] = 8000
    agent = OSWorldAgent(data, client=client)
    with pytest.raises(TaskControlBlocked, match="Mandatory task facts"):
        agent.predict("长" * 10000, {"screenshot": screenshot()})
    assert not client.requests
    assert "core_budget_exceeded" in agent.control.trace_path.read_text()
    agent.close()


def test_restart_without_execution_receipt_blocks_repeat_predictions(tmp_path):
    agent = OSWorldAgent(config(tmp_path), client=RoleClient())
    instruction = f"Read {URL}"
    agent.predict(instruction, {"screenshot": screenshot()})
    agent.reset()  # Simulate losing a worker before execution confirmation.
    for _ in range(2):
        with pytest.raises(TaskControlBlocked, match="intent without receipt"):
            agent.predict(instruction, {"screenshot": screenshot()})
    agent.close()


def test_missing_feedback_blocks_same_process_next_dispatch(tmp_path):
    client = RoleClient()
    agent = OSWorldAgent(config(tmp_path), client=client)
    agent.predict("Read quote", {"screenshot": screenshot()})
    calls = len(client.requests)
    with pytest.raises(TaskControlBlocked, match="intent without receipt"):
        agent.predict("Read quote", {"screenshot": screenshot()})
    assert len(client.requests) == calls
    agent.close()


def test_verifier_callback_cannot_replace_raw_execution_or_screenshot():
    with pytest.raises(ValueError, match="Invalid adapter"):
        effect_feedback(lambda *_: {"controller_result": {"status": "success"}}, {}, {"screenshot": b"png"}, None)
    report = effect_feedback(lambda *_: {"effect_verified": False}, {}, {"screenshot": b"png"}, None)
    assert report["controller_result"] is None and report["screenshot"] == b"png"


def test_official_feedback_hook_is_scoped_and_preserves_results():
    received = []
    class Controller:
        def execute_python_command(self, command):
            return {"status": "success", "returncode": 0}
    class Env:
        def step(self, action):
            self.controller.execute_python_command(action)
            return {"screenshot": b"image"}, 0, False, {"unchanged": True}
    install_feedback_hooks(Env, Controller)
    env = Env()
    env.controller = Controller()
    owner = SimpleNamespace(_execution_result=None, worker=SimpleNamespace(feedback=received.append))
    token = action_owner.set(owner)
    try:
        result = env.step("command")
        assert result[-1] == {"unchanged": True}
        assert received[0]["controller_result"]["returncode"] == 0
        assert received[0]["screenshot"] == b"image"
        env.step("unrelated")
        assert len(received) == 1
    finally:
        action_owner.reset(token)


@pytest.mark.parametrize("trigger", ["executor_fail", "verifier_subtask_failure"])
def test_runtime_fail_executes_one_attested_inverse_and_verifies_checkpoint(tmp_path, trigger):
    client = RoleClient()
    client.action = {"type": "type", "text": "local draft"}
    agent = OSWorldAgent(config(tmp_path), client=client)
    instruction = f"Read {URL}"
    control = agent.control
    control.initialize(instruction)
    s0 = {"source": "independent-fixture-observer", "ref": "before.png", "version": "before",
          "resource": URL, "facts": {"task": "fixture", "draft": ""}}
    s1 = {**s0, "ref": "after.png", "version": "after", "facts": {"task": "fixture", "draft": "local draft"}}
    control.recovery.checkpoint("verified-draft-ready", s0, prerequisites={"facts": {"task": "fixture"}}, verified=True)
    agent.predict(instruction, {"screenshot": screenshot()})
    action_id = control.pending["id"]
    agent.feedback({"controller_result": {"status": "success", "returncode": 0},
        "screenshot": screenshot("blue"), "verified_state": s1, "effect_verified": True,
        "compensation": {"action": {"type": "hotkey", "keys": ["ctrl", "z"]},
            "guard": {"resource": URL, "facts": {"draft": "local draft"}},
            "postcondition": {"resource": URL, "facts": {"draft": ""}},
            "evidence": {k: s1[k] for k in ("source", "ref", "version")}, "verified": True}})
    assert control.recovery.action(action_id)["barrier"] is None
    client.fail = trigger == "executor_fail"
    client.verifier_failed = trigger == "verifier_subtask_failure"
    response, actions = agent.predict(instruction, {"screenshot": screenshot("blue")})
    assert json.loads(response)["action"] == {"type": "hotkey", "keys": ["ctrl", "z"]}
    assert len(actions) == 1 and "hotkey" in actions[0]
    assert control.pending["compensation_id"]
    assert control.last_trace["failure_trigger"] == trigger
    agent.feedback({"controller_result": {"status": "success", "returncode": 0},
        "screenshot": screenshot("white"), "verified_state": {**s0, "ref": "restored.png", "version": "restored"},
        "effect_verified": True})
    assert control.recovery.state()["recovery"]["status"] == "complete"
    assert control.recovery.action(action_id)["compensated"]
    agent.close()


def test_independently_confirmed_review_wait_is_not_subtask_progress(tmp_path):
    class MissingPostconditionClient(RoleClient):
        def create(self, **kwargs):
            response = super().create(**kwargs)
            if "subordinate task planner" in kwargs["messages"][0]["content"]:
                response.choices[0].message.content = json.dumps({
                    "advice": "Observe the draft", "needed_evidence": ["draft postcondition absent"]})
            return response
    client = MissingPostconditionClient()
    agent = OSWorldAgent(config(tmp_path), client=client)
    instruction = f"Read {URL}"
    agent.predict(instruction, {"screenshot": screenshot()})
    state = {"source": "trusted-fixture", "ref": "step0.png", "version": "v0",
             "resource": URL, "facts": {"draft": "unchanged"}}
    agent.feedback({"controller_result": {"status": "success", "returncode": 0},
                    "screenshot": screenshot(), "verified_state": state, "effect_verified": True})
    client.verifier_failed = True
    for number in range(1, 3):
        response, actions = agent.predict(instruction, {"screenshot": screenshot()})
        assert json.loads(response)["action"]["type"] == "wait" and actions != ["FAIL"]
        assert agent.control.last_trace["failure_scope"]["need_ids"] == ["price"]
        agent.feedback({"controller_result": {"status": "success", "returncode": 0},
                        "screenshot": screenshot(), "effect_verified": True,
                        "verified_state": {**state, "ref": f"step{number}.png", "version": f"v{number}"}})
        assert agent.control.fail_reviews == number
    with pytest.raises(TaskControlBlocked, match="FAIL review limit"):
        agent.predict(instruction, {"screenshot": screenshot()})
    assert agent.control.pending is None
    assert agent.control.last_trace["subagents"]["verifier"]["grade"] == "model_proposal"
    agent.close()


def test_graph_action_admission_gap_stops_before_execution(tmp_path, monkeypatch):
    agent = OSWorldAgent(config(tmp_path), client=RoleClient())
    agent.control.initialize("Read quote")
    monkeypatch.setattr(agent.control.memory, "record_action_attempt", lambda *_args, **_kwargs: {
        "accepted": False, "reason": "semantic_index_capacity_exceeded"})
    with pytest.raises(TaskControlBlocked, match="semantic graph"):
        agent.predict("Read quote", {"screenshot": screenshot()})
    assert agent.control.last_trace["status"] == "action_graph_gap"
    assert "semantic_index_capacity_exceeded" in agent.control.trace_path.read_text()
    agent.close()


def test_subtask_failure_without_checkpoint_cannot_dispatch_forward_or_global_fail(tmp_path):
    client = RoleClient()
    agent = OSWorldAgent(config(tmp_path), client=client)
    instruction = f"Read {URL}"
    agent.predict(instruction, {"screenshot": screenshot()})
    agent.feedback({"controller_result": {"status": "success", "returncode": 0},
                    "screenshot": screenshot(), "effect_verified": True,
                    "verified_state": {"source": "trusted-fixture", "ref": "after.png", "version": "v1",
                                       "resource": URL, "facts": {"draft": "present"}}})
    client.verifier_failed = True
    with pytest.raises(TaskControlBlocked, match="Subtask failure"):
        agent.predict(instruction, {"screenshot": screenshot()})
    trace = agent.control.last_trace
    assert trace["status"] == "blocked_subtask_recovery"
    assert trace["original_decision"]["action"]["type"] == "move"
    assert trace["fail_review"]["status"] == "no_safe_recovery"
    assert agent.control.pending is None
    assert agent.control.recovery.state()["action_count"] == 1
    agent.close()


def test_controller_core_claim_anchor_uses_exact_subject_without_mutating_proposal(tmp_path):
    class FactClient(RoleClient):
        def create(self, **kwargs):
            reply = super().create(**kwargs)
            if "You are the task controller" in kwargs["messages"][0]["content"]:
                context = json.loads(kwargs["messages"][1]["content"][0]["text"])
                goal = next(f for f in context["mandatory_core"]["facts"] if f["category"] == "goal")
                body = json.loads(reply.choices[0].message.content)
                body["needs"][2]["anchors"] = ["task", goal["id"]]
                self.original = json.loads(json.dumps(body))
                reply.choices[0].message.content = json.dumps(body)
            return reply
    client = FactClient()
    agent = OSWorldAgent(config(tmp_path), client=client)
    _, actions = agent.predict("Read the visible quote", {"screenshot": screenshot()})
    assert "moveTo" in actions[0] and len(client.requests) == 5
    trace = agent.control.last_trace
    assert trace["controller"] == client.original
    assert trace["normalized_needs"][2]["anchors"] == ["task"]
    resolution = trace["view_anchor_resolutions"][0]
    assert resolution["entity_anchor"] == "task" and resolution["duplicate_entity_omitted"]
    assert resolution["basis"] == "exact_active_core_claim_subject"
    assert trace["normalized_needs"][:2] == client.original["needs"][:2]
    agent.close()


@pytest.mark.parametrize("condition", ["unknown", "stale", "wrong_subject", "duplicate", "extra_field", "hops"])
def test_core_anchor_binding_keeps_invalid_routes_blocked(tmp_path, condition):
    from kobe_views.view_control import InvalidViewNeed
    from copy import deepcopy
    agent = OSWorldAgent(config(tmp_path), client=RoleClient())
    agent.control.initialize("Read the visible quote")
    snapshot = agent.control.memory.read()
    core = deepcopy(agent.control.memory.core_packet(64000))
    goal = next(f for f in core["facts"] if f["category"] == "goal")
    need = {"id": "operate", "consumer": "executor", "purpose": "next GUI step",
            "anchors": [goal["id"]], "focus_predicates": ["task.*"], "max_hops": 0}
    if condition == "unknown":
        need["anchors"] = ["invented-id"]
    elif condition == "stale":
        goal["graph_revision"] = "old-revision"
    elif condition == "wrong_subject":
        goal["subject"] = "different-object"
    elif condition == "duplicate":
        need["anchors"] *= 2
    elif condition == "extra_field":
        need["permissions"] = ["all"]
    elif condition == "hops":
        need["max_hops"] = 5
    with pytest.raises(InvalidViewNeed):
        normalized, _ = agent.control._resolve_core_anchors(snapshot, core, [need])
        agent.control.views.compile(snapshot, normalized, 20000)
    assert agent.control.pending is None
    agent.close()


def test_worker_preserves_blocked_trace_without_emitting_model_fail(tmp_path, monkeypatch):
    import base64
    from io import StringIO
    from ui_kobe.osworld import worker, telemetry
    trace = {"task_control": {"stage": "controller", "gaps": [{"reason": "Unknown semantic anchor"}]}}
    class BlockedAgent:
        sequence = 0
        last_trace = trace
        def predict(self, *_args, **_kwargs):
            raise TaskControlBlocked("Controller proposed an invalid semantic view; inspect bounded trace")
        def close(self):
            pass
    emitted = []
    monkeypatch.setattr(worker, "load_config", lambda _: {})
    monkeypatch.setattr(worker, "OSWorldAgent", lambda _: BlockedAgent())
    monkeypatch.setattr(worker.sys, "argv", ["worker", "--config", "unused"])
    monkeypatch.setenv("UI_KOBE_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setattr(telemetry, "install_api", lambda _: None)
    monkeypatch.setattr(telemetry, "set_context", lambda *_: None)
    monkeypatch.setattr(telemetry, "emit", lambda kind, **data: emitted.append((kind, data)))
    monkeypatch.setattr(worker.sys, "stdin", StringIO(json.dumps({"method": "predict", "instruction": "goal",
        "seconds": 480, "screenshot": base64.b64encode(screenshot()).decode()}) + "\n"))
    output = StringIO()
    monkeypatch.setattr(worker.sys, "stdout", output)
    worker.main()
    reply = json.loads(output.getvalue())
    assert reply["ok"] is False and reply["trace"] == trace
    assert "invalid semantic view" in reply["error"] and "response" not in reply
    assert emitted == [("framework_error", {"error_type": "TaskControlBlocked", "error": reply["error"], "trace": trace})]


def test_core_claim_subject_still_cannot_expand_a_role_scope(tmp_path):
    from kobe_views.task_views import RoleContract
    from kobe_views.view_control import DynamicViewController, InvalidViewNeed
    agent = OSWorldAgent(config(tmp_path), client=RoleClient())
    agent.control.initialize(f"Read {URL}")
    snapshot = agent.control.memory.read()
    core = agent.control.memory.core_packet(64000)
    url = next(f for f in core["facts"] if f["category"] == "url")
    controller = DynamicViewController([RoleContract(id="executor", anchors=("task",),
        read_predicates=("*",), max_hops=0)])
    agent.control.views = controller
    original = {"id": "url", "consumer": "executor", "purpose": "inspect visible resource",
        "anchors": [url["id"]], "focus_predicates": ["resource.*"], "max_hops": 0}
    normalized, resolutions = agent.control._resolve_core_anchors(snapshot, core, [original])
    assert normalized[0]["anchors"] == [url["subject"]] and len(resolutions) == 1
    with pytest.raises(InvalidViewNeed, match="outside trusted role scope"):
        controller.compile(snapshot, normalized, 20000)
    assert original["anchors"] == [url["id"]] and agent.control.pending is None
    agent.close()
