from io import BytesIO
import json
from types import SimpleNamespace
from pathlib import Path
import sys

from PIL import Image
import pytest

from ui_kobe.osworld.actions import InvalidAction, compile_action, json_object
from ui_kobe.osworld.agent import GLMOSWorldAgent, bounded_visual_evidence
from ui_kobe.osworld.runner import CheckedController, run_episode, main, wait_for_visible_desktop
from ui_kobe.osworld.local_web import ensure_guest_return_route
from ui_kobe.osworld.process import AgentProcess


def screenshot():
    buffer = BytesIO()
    Image.new("RGB", (800, 600), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("action", [
    {"type": "click", "x": -1, "y": 2}, {"type": "click", "x": 800, "y": 2},
    {"type": "move", "x": True, "y": 2}, {"type": "move", "x": 1.5, "y": 2},
    {"type": "move", "x": 2, "y": 600}, {"type": "exec", "code": "print(1)"},
    {"type": "click", "x": 2, "y": 2, "code": "print(1)"},
    {"type": "hotkey", "keys": ["__import__('os')"]},
    {"type": "wait", "seconds": float("nan")}, {"type": "wait", "seconds": 31},
    {"type": "scroll", "x": 2, "y": 2, "amount": 0},
])
def test_invalid_model_actions_never_compile(action):
    with pytest.raises(InvalidAction):
        compile_action(action, 800, 600)


def test_unicode_and_code_like_text_remain_literal(monkeypatch):
    import subprocess
    text = "你好'); __import__('os').system('bad')\n\\quote\""
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    events = []
    gui = SimpleNamespace(hotkey=lambda *keys: events.append(keys))
    exec(compile_action({"type": "type", "text": text}, 800, 600), {"pyautogui": gui})
    argv, options = calls[0]
    assert argv == [sys.executable, "-c", "import sys, pyperclip; pyperclip.copy(sys.stdin.read())"]
    assert options["input"] == text and text not in argv[2]
    assert options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert options["timeout"] == 10 and options["check"] and options["encoding"] == "utf-8"
    assert events == [("ctrl", "v")]


def test_clipboard_timeout_never_proceeds_to_paste(monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(subprocess, "run", timeout)
    events = []
    with pytest.raises(subprocess.TimeoutExpired):
        exec(compile_action({"type": "type", "text": "abc"}, 800, 600),
             {"pyautogui": SimpleNamespace(hotkey=lambda *keys: events.append(keys))})
    assert not events


def test_clipboard_owner_cannot_hold_guest_execution_capture_pipes_open(tmp_path):
    import os
    import subprocess
    # Emulate a clipboard daemon without X11 or desktop interaction. It outlives copy().
    (tmp_path / "pyperclip.py").write_text(
        "import subprocess, sys\ndef copy(text):\n"
        "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'])\n")
    environment = dict(os.environ, PYTHONPATH=str(tmp_path))
    action = compile_action({"type": "type", "text": "你好"}, 800, 600)
    outer = "from types import SimpleNamespace; pyautogui=SimpleNamespace(hotkey=lambda *keys: print('paste-called')); " + action
    # The captured outer command must finish before the simulated owner exits.
    reply = subprocess.run([sys.executable, "-c", outer], env=environment,
                           capture_output=True, text=True, timeout=1.5, check=True)
    assert reply.stdout.strip() == "paste-called"


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"x":NaN}', 'prefix {"x":1}', '[]'])
def test_json_parser_rejects_ambiguous_or_non_json_output(text):
    with pytest.raises(ValueError):
        json_object(text)


class FakeClient:
    def __init__(self, decision=None):
        self.requests = []
        self.stats = {"requests": 0}
        self.decision = decision or {"reason": "Move to the requested location", "action": {"type": "move", "x": 320, "y": 240}}

    def create(self, **kwargs):
        self.requests.append(kwargs)
        self.stats["requests"] += 1
        body = {"summary": "Save button visible", "elements": [{"text": "Save", "role": "button", "bbox": [10, 10, 80, 40]}]}
        if len(self.requests) % 2 == 0:
            body = self.decision
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(body)))])

    def close(self):
        pass


def test_real_frame_projects_taskviews_into_decision_and_clears_on_reset():
    client = FakeClient()
    agent = GLMOSWorldAgent(client=client)
    response, actions = agent.predict("Move pointer", {"screenshot": screenshot()})
    assert "moveTo(320, 240" in actions[0]
    prompt = client.requests[1]["messages"][1]["content"][0]["text"]
    assert "800 x 600" in prompt
    assert "read-only evidence" in prompt
    assert "Save" in prompt
    assert "candidate" in prompt
    assert set(k.value for k in agent.bridge.last_views) == {"grounding", "relation", "planning", "verification"}
    assert "interaction_verified" not in agent.last_trace["context"]
    agent.predict("Move pointer", {"screenshot": screenshot()})
    assert len(agent.transitions) == 1
    assert agent.transitions[0]["grade"] == "candidate"
    agent.reset()
    assert agent.history == [] and agent.frames == [] and agent.sequence == 0


def test_agent_stops_on_unsafe_coordinate():
    client = FakeClient({"reason": "bad", "action": {"type": "click", "x": 801, "y": 0}})
    with pytest.raises(InvalidAction):
        GLMOSWorldAgent(client=client).predict("test", {"screenshot": screenshot()})


def test_agent_rejects_bare_action_and_preserves_diagnostic_trace():
    bare = {"type": "move", "x": 320, "y": 240}
    agent = GLMOSWorldAgent(client=FakeClient(bare))
    with pytest.raises(ValueError, match="Invalid decision schema"):
        agent.predict("Move pointer", {"screenshot": screenshot()})
    assert agent.history == []
    assert agent.last_trace["stage"] == "decision"
    assert agent.last_trace["unvalidated_response"] == bare
    assert agent.last_trace["evidence"]["summary"] == "Save button visible"


def test_long_rationale_is_preserved_but_does_not_expand_future_history():
    reason = "解释" * 1100 + "UNIQUE-OMITTED-TAIL"
    decision = {"reason": reason, "action": {"type": "click", "x": 799, "y": 40}}
    client = FakeClient(decision)
    agent = GLMOSWorldAgent(client=client)
    response, actions = agent.predict("test", {"screenshot": screenshot()})
    assert json.loads(response) == decision == client.decision
    assert actions == ["pyautogui.click(799, 40, clicks=1, interval=0.15, button='left')"]
    assert agent.last_trace["decision"] == decision
    assert agent.history == [{**decision, "reason": reason[:2000]}]
    assert agent.last_trace["decision_history_budget"] == {
        "received_reason_chars": len(reason), "retained_reason_chars": 2000,
        "omitted_reason_chars": len(reason) - 2000,
        "policy": "history_prefix_only_original_response_preserved"}
    agent.predict("test", {"screenshot": screenshot()})
    assert len(client.requests) == 4  # No extra model calls to repair rationale.
    assert "UNIQUE-OMITTED-TAIL" not in client.requests[-1]["messages"][1]["content"][0]["text"]


@pytest.mark.parametrize("reason", [None, True, [], {"text": "reason"}])
def test_non_text_rationale_still_fails_schema(reason):
    agent = GLMOSWorldAgent(client=FakeClient({"reason": reason, "action": {"type": "move", "x": 1, "y": 1}}))
    with pytest.raises(ValueError, match="Invalid decision schema"):
        agent.predict("test", {"screenshot": screenshot()})
    assert agent.history == []


def test_long_rationale_never_weakens_action_validation_or_json_capacity():
    bad_action = {"reason": "r" * 2100, "action": {"type": "click", "x": 800, "y": 40}}
    agent = GLMOSWorldAgent(client=FakeClient(bad_action))
    with pytest.raises(InvalidAction):
        agent.predict("test", {"screenshot": screenshot()})
    assert agent.history == []
    oversized = GLMOSWorldAgent(client=FakeClient({"reason": "r" * 100001, "action": {"type": "done"}}))
    with pytest.raises(ValueError, match="bounded JSON"):
        oversized.predict("test", {"screenshot": screenshot()})
    assert oversized.history == []


def many_controls(count):
    return {"summary": "Visible controls", "elements": [
        {"text": f"control-{i}", "role": "button", "bbox": [10, 10, 80, 40]} for i in range(count)]}


def test_perception_budget_overflow_reaches_decision_with_bounded_evidence():
    raw = many_controls(27)  # Regression: a valid 27-control response ended the live run.

    class OverflowClient(FakeClient):
        def create(self, **kwargs):
            response = super().create(**kwargs)
            if len(self.requests) == 1:
                response.choices[0].message.content = json.dumps(raw)
            return response

    client = OverflowClient()
    agent = GLMOSWorldAgent(client=client)
    _, actions = agent.predict("Move pointer", {"screenshot": screenshot()})
    assert len(client.requests) == 2 and "moveTo(320, 240" in actions[0]
    assert len(raw["elements"]) == 27  # Keep the original response intact for telemetry.
    assert agent.last_trace["evidence"]["elements"] == raw["elements"][:24]
    assert agent.last_trace["evidence_normalization"]["dropped_elements"] == 3
    assert "control-24" not in client.requests[1]["messages"][1]["content"][0]["text"]


def test_invalid_overflow_control_is_never_hidden_by_truncation():
    raw = many_controls(27)
    raw["elements"][-1]["bbox"][2] = 801
    evidence, log = bounded_visual_evidence(raw, 800, 600)
    assert len(evidence["elements"]) == 24
    assert log["invalid_elements"] == 1 and log["budget_dropped_elements"] == 2
    assert log["rejected_elements"] == [{"index": 26, "reason": "invalid_bbox"}]


@pytest.mark.parametrize("box", [[55, 98, 233, 16], [10, 10, 801, 40], [10, 10, 10, 40],
                                [-1, 10, 80, 40], [True, 10, 80, 40], [10.5, 10, 80, 40], [10, 10]])
def test_invalid_observation_geometry_is_omitted_without_coordinate_guessing(box):
    raw = many_controls(2)
    raw["elements"][1]["bbox"] = box
    evidence, log = bounded_visual_evidence(raw, 800, 600)
    assert evidence["elements"] == [raw["elements"][0]]
    assert evidence["elements"][0]["bbox"] == [10, 10, 80, 40]
    assert raw["elements"][1]["bbox"] is box
    assert log["invalid_elements"] == 1 and log["rejected_elements"][0]["index"] == 1


def test_perception_geometry_error_still_reaches_decision_from_original_screenshot():
    raw = many_controls(2)
    raw["elements"][1]["text"] = "invalid-target"
    raw["elements"][1]["bbox"] = [55, 98, 233, 16]

    class GeometryClient(FakeClient):
        def create(self, **kwargs):
            response = super().create(**kwargs)
            if len(self.requests) == 1:
                response.choices[0].message.content = json.dumps(raw)
            return response

    client = GeometryClient()
    agent = GLMOSWorldAgent(client=client)
    _, actions = agent.predict("Move pointer", {"screenshot": screenshot()})
    assert len(client.requests) == 2 and "moveTo(320, 240" in actions[0]
    assert "invalid-target" not in client.requests[1]["messages"][1]["content"][0]["text"]
    assert client.requests[1]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert agent.last_trace["evidence_normalization"]["invalid_elements"] == 1


def test_empty_valid_control_set_remains_observation_without_fabricated_geometry():
    raw = many_controls(1)
    raw["elements"][0]["bbox"] = [0, 0, 0, 0]
    evidence, log = bounded_visual_evidence(raw, 800, 600)
    assert evidence == {"summary": raw["summary"], "elements": []}
    assert log["invalid_elements"] == 1


def test_unbounded_control_count_is_rejected_before_projection():
    with pytest.raises(ValueError, match="Invalid visual evidence schema"):
        bounded_visual_evidence(many_controls(257), 800, 600)


def test_guest_execution_error_is_not_silently_accepted():
    controller = CheckedController(SimpleNamespace(execute_python_command=lambda _: {"status": "error", "returncode": 1}))
    with pytest.raises(RuntimeError, match="Guest GUI action failed"):
        controller.execute_python_command("pyautogui.click(1,2)")


class FakeEnv:
    def __init__(self):
        self.actions = []
        self.evaluations = 0
        self.controller = SimpleNamespace(execute_python_command=lambda _: {"status": "success", "returncode": 0, "output": "[320,240]"})

    def reset(self, task):
        return {"screenshot": screenshot()}

    def step(self, action, pause):
        self.actions.append(action)
        return {"screenshot": screenshot()}, 0, action in ("DONE", "FAIL"), {}

    def evaluate(self):
        self.evaluations += 1
        return 0.5


class FakeProxy:
    def __init__(self, action):
        self.action = action
        self.last_trace = {"usage": {"requests": 2}}

    def predict(self, instruction, obs, seconds):
        return json.dumps({"reason": "test", "action": self.action}), [compile_action(self.action, 800, 600)]


def test_smoke_full_loop_and_never_calls_evaluator(tmp_path):
    env = FakeEnv()
    report = run_episode(env, FakeProxy({"type": "move", "x": 320, "y": 240}), "Move pointer", tmp_path,
                         max_steps=1, max_seconds=10, desktop_smoke=True)
    assert report["status"] == "desktop_smoke_passed"
    assert report["score"] is None and not report["evaluated"]
    assert env.evaluations == 0
    assert (tmp_path / "frame-0002.png").exists()
    assert json.loads((tmp_path / "step-0001.json").read_text())["executed"]


def test_smoke_does_not_execute_other_actions(tmp_path):
    env = FakeEnv()
    with pytest.raises(ValueError, match="smoke permits only"):
        run_episode(env, FakeProxy({"type": "done"}), "Move", tmp_path, max_steps=1, max_seconds=10, desktop_smoke=True)
    assert not env.actions
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "error"


@pytest.mark.parametrize("evaluate", [False, True])
def test_done_is_distinct_from_official_evaluation(tmp_path, evaluate):
    env = FakeEnv()
    report = run_episode(env, FakeProxy({"type": "done"}), "task", tmp_path,
                         max_steps=2, max_seconds=10, evaluate=evaluate)
    assert report["agent_done"] and report["steps"] == 1
    assert report["evaluated"] == evaluate
    assert report["score"] == (0.5 if evaluate else None)


@pytest.mark.parametrize("exists", [False, True])
def test_guest_nat_is_idempotent_and_scoped_to_one_website(exists):
    commands = []

    def execute(command):
        commands.append(command)
        return SimpleNamespace(exit_code=0 if exists or "-A" in command else 1)

    ensure_guest_return_route(SimpleNamespace(exec_run=execute), "172.25.0.2")
    assert len(commands) == (1 if exists else 2)
    for command in commands:
        assert command[-8:] == ["-d", "172.25.0.2", "-p", "tcp", "--dport", "21280", "-j", "MASQUERADE"]


def test_guest_nat_never_uses_unvalidated_shell_text():
    with pytest.raises(ValueError):
        ensure_guest_return_route(SimpleNamespace(exec_run=lambda _: pytest.fail("must not execute")), "1.2.3.4; bad")


def test_real_subprocess_handshake_does_not_need_a_network_request(tmp_path, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "offline-test-key")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    config = tmp_path / "config.json"
    config.write_text('{"api":{},"agent":{}}')
    with (tmp_path / "stderr.log").open("w") as stderr:
        agent = AgentProcess(sys.executable, config, stderr=stderr)
        try:
            agent.reset()
            assert agent.metadata["ok"]
            assert agent.metadata["openai_version"]
            with pytest.raises(RuntimeError, match="Unknown worker method"):
                agent._call({"method": "unknown"}, 10)
        finally:
            agent.close()
        assert agent._process.poll() == 0


def test_runner_rejects_a_custom_agents_unvalidated_python(tmp_path):
    agent = FakeProxy({"type": "move", "x": 320, "y": 240})
    agent.predict = lambda *a, **k: (json.dumps({"reason": "test", "action": agent.action}), ["print('arbitrary code')"])
    env = FakeEnv()
    with pytest.raises(ValueError, match="validated structured decision"):
        run_episode(env, agent, "task", tmp_path, max_steps=1, max_seconds=10)
    assert not env.actions


def test_cli_refuses_results_inside_osworld_source(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["runner", "--osworld-root", str(tmp_path),
                                    "--agent-python", sys.executable, "--config", "unused.json",
                                    "--adapter-smoke", "--output", str(tmp_path / "results")])
    with pytest.raises(SystemExit) as err:
        main()
    assert err.value.code == 2
    assert "outside the OSWorld source" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("color", ["black", (45, 45, 45)])
def test_boot_black_frame_is_replaced_before_agent_sees_it(monkeypatch, color):
    black = BytesIO()
    Image.new("RGB", (1280, 800), color).save(black, format="PNG")
    monkeypatch.setattr("ui_kobe.osworld.runner.time.sleep", lambda _: None)
    ready = screenshot()
    env = SimpleNamespace(controller=SimpleNamespace(get_screenshot=lambda: ready))
    assert wait_for_visible_desktop(env, {"screenshot": black.getvalue()})["screenshot"] == ready
    with pytest.raises(TimeoutError):
        wait_for_visible_desktop(env, {"screenshot": black.getvalue()}, timeout=0)
