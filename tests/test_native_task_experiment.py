from copy import deepcopy
from io import BytesIO
import json

from PIL import Image
import pytest

from ui_kobe.api.kimi_stream import Completion, SSEAccumulator, StreamProtocolError
from ui_kobe.osworld import kimi_taskviews_native as views
from ui_kobe.osworld.cua_contract import CUAContract
from scripts.osworld_native_experiment import official_arguments
from scripts import osworld_native_experiment as experiment


@pytest.fixture
def launch_sandbox(tmp_path, monkeypatch):
    root = tmp_path / "new-plan"
    root.mkdir()
    experiment.write(root / "plan.json", {"task_id": "059", "arms": ["baseline", "taskviews"],
        'implementation_version': 6, 'agent_interface': 'k3-native',
        "protocols": ["kimi-k3-native-tools-official-cua-v6", "kimi-k3-native-tools-taskviews-official-cua-v6"],
        "cua_contract": CUAContract().snapshot()})
    home = tmp_path / "home"
    (home / ".config/systemd/user").mkdir(parents=True)
    monkeypatch.setattr(experiment.Path, "home", lambda: home)
    monkeypatch.setattr(experiment, "ROOT", tmp_path / "official")
    checks, commands = [], []
    monkeypatch.setattr(experiment, "frozen_check", lambda path: checks.append(("source", path)))
    monkeypatch.setattr(experiment, "resources_ready", lambda: checks.append(("resources", None)))
    monkeypatch.setattr(experiment.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr(experiment.subprocess, "run", lambda args, **k: commands.append(args))
    return root, checks, commands


@pytest.mark.parametrize("baseline", [None, {"valid_score": False, "score": None},
                                     {"valid_score": True, "score": 0}])
def test_taskviews_launch_is_independent_of_baseline_score(launch_sandbox, baseline):
    root, checks, commands = launch_sandbox
    if baseline is not None:
        experiment.write(root / "baseline/audit.json", {**baseline, "source_unchanged": True, "cleanup_ok": True})
    experiment.launch(root, "taskviews")
    manifest = experiment.load(root / "taskviews/manifest.json")
    assert manifest["arm"] == "taskviews"
    assert manifest["agent_protocol"] == "kimi-k3-native-tools-taskviews-official-cua-v6"
    assert checks == [("source", root), ("resources", None)]
    assert commands[-1] == ["systemctl", "--user", "start", manifest["unit"]]
    assert not (root / "taskviews/audit.json").exists()
    if baseline is not None:
        assert experiment.load(root / "baseline/audit.json")["score"] == baseline["score"]


@pytest.mark.parametrize('change', [
    {'implementation_version': 5}, {'agent_interface': 'guess'},
    {'agent_interface': 'official-xml'},
    {'agent_interface': 'official-xml', 'protocols': ['kimi-k3-official-qwen-xml-v6',
        'kimi-k3-official-qwen-xml-taskviews-v6']}])
def test_mixed_old_or_unverified_xml_interface_is_rejected_before_resources(launch_sandbox, change):
    root, checks, commands = launch_sandbox
    experiment.write(root / 'plan.json', {**experiment.load(root / 'plan.json'), **change})
    with pytest.raises(RuntimeError):
        experiment.launch(root, 'baseline')
    assert checks == [('source', root)] and not commands
    assert not (root / 'baseline').exists()


@pytest.mark.parametrize("failed_check", ["source_unchanged", "cleanup_ok"])
def test_taskviews_keeps_existing_baseline_safety_checks(launch_sandbox, failed_check):
    root, _, commands = launch_sandbox
    experiment.write(root / "baseline/audit.json", {"valid_score": True, "score": 1,
        "source_unchanged": True, "cleanup_ok": True, failed_check: False})
    with pytest.raises(RuntimeError, match="source audit or cleanup failed"):
        experiment.launch(root, "taskviews")
    assert not commands and not (root / "taskviews").exists()


def test_independent_arm_still_rejects_concurrent_service(launch_sandbox, monkeypatch):
    root, _, commands = launch_sandbox
    monkeypatch.setattr(experiment.subprocess, "check_output",
                        lambda *a, **k: "osworld21-existing.service loaded active running\n")
    with pytest.raises(RuntimeError, match="already runs"):
        experiment.launch(root, "taskviews")
    assert not commands and not (root / "taskviews").exists()


def test_independent_arm_never_overwrites_existing_trial(launch_sandbox):
    root, _, commands = launch_sandbox
    (root / "taskviews").mkdir()
    with pytest.raises(FileExistsError):
        experiment.launch(root, "taskviews")
    assert not commands


def test_legacy_plan_is_rejected_before_resource_probe_or_service(launch_sandbox):
    root, checks, commands = launch_sandbox
    plan = experiment.load(root / "plan.json")
    del plan["cua_contract"]
    experiment.write(root / "plan.json", plan)
    with pytest.raises(RuntimeError, match="predeclared CUA contract"):
        experiment.launch(root, "baseline")
    assert checks == [("source", root)] and not commands


def test_task046_still_rejects_missing_deployment_proof(launch_sandbox):
    root, _, commands = launch_sandbox
    plan = experiment.load(root / "plan.json")
    plan["task_id"] = "046"
    experiment.write(root / "plan.json", plan)
    with pytest.raises(RuntimeError, match="deployment/resource admission"):
        experiment.launch(root, "baseline")
    assert not commands


def test_task046_admission_requires_matching_source_cleanup_and_intact_evidence(tmp_path):
    from scripts.native_task046_web import validate_admission
    evidence = tmp_path / "setup.json"
    experiment.write(evidence, {"official_setup_success": True})
    path = tmp_path / "admission.json"
    source = {"runtime.py": "frozen-sha"}
    record = {"status": "passed", "cleanup_ok": True, "project_source": source,
              "evidence_sha256": {str(evidence): experiment.digest(evidence)}}
    experiment.write(path, record)
    assert validate_admission(path, source)["sha256"] == experiment.digest(path)
    with pytest.raises(RuntimeError, match="current interface"):
        validate_admission(path, {"runtime.py": "changed"})
    experiment.write(path, {**record, "cleanup_ok": False})
    with pytest.raises(RuntimeError, match="cleaned setup proof"):
        validate_admission(path, source)
    experiment.write(path, record)
    experiment.write(evidence, {"official_setup_success": False})
    with pytest.raises(RuntimeError, match="evidence changed"):
        validate_admission(path, source)


@pytest.mark.parametrize("fragment", ["not-json", "[]", '{"choices":42}', '{"choices":[{"delta":{"content":42}}]}'])
def test_invalid_sse_json_and_delta_are_protocol_errors(fragment):
    accumulator = SSEAccumulator()
    accumulator.add(fragment)
    accumulator.add('[DONE]')
    with pytest.raises(StreamProtocolError):
        accumulator.complete()


def response(message, finish="stop"):
    return Completion({"id": "test", "model": "kimi-k3", "choices": [{"finish_reason": finish,
        "message": {"role": "assistant", "content": None, "reasoning_content": "original reasoning", **message}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


class Transport:
    last_timing = {"complete_s": 1}

    def __init__(self):
        self.requests = []
        self.actor = 0

    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        if kwargs.get("tools"):
            self.actor += 1
            return response({"tool_calls": [{"id": f"call-{self.actor}", "type": "function", "function": {
                "name": "computer_use", "arguments": '{"action":"mouse_move","coordinate":[100,100]}'}}]}, "tool_calls")
        prompt = kwargs["messages"][0]["content"]
        if "Extract visible evidence" in prompt:
            body = {"summary": "GeoGebra visible", "elements": [], "semantics": {"entities": [], "claims": []}}
        else:
            body = {"stage": "observe", "needs": [{"id": "gui", "consumer": "executor", "purpose": "next action",
                      "anchors": ["task"], "focus_predicates": ["*"], "max_hops": 1}]}
        return response({"content": json.dumps(body)})

    def close(self):
        pass


def test_taskviews_native_shares_deadline_and_preserves_tool_history(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "offline-only")
    monkeypatch.setenv("UI_KOBE_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("UI_KOBE_TASK_ID", "059")
    agent = views.KimiTaskViewsNativeAgent(model="kimi-k3", base_url="https://api.moonshot.ai/v1", temperature=1, max_tokens=16000)
    transport = Transport()
    agent.transport = transport
    agent.client.transport = transport
    buf = BytesIO()
    Image.new("RGB", (1920, 1080), "white").save(buf, "PNG")
    try:
        for _ in range(2):
            _, commands = agent.predict("Original exact task with VaseVolume", {"screenshot": buf.getvalue()})
            assert "moveTo" in commands[0] and "DONE" not in commands
        assert len(transport.requests) == 6
        for first, second, actor in (transport.requests[:3], transport.requests[3:]):
            assert first["deadline"] == second["deadline"] < actor["deadline"]
            assert actor["deadline"] - first["deadline"] == agent.budget.generation_s + agent.budget.connect_s
            assert actor["tool_choice"] == "auto" and len(actor["tools"]) == 1
            assert actor["reasoning_effort"] == "low" and actor["max_completion_tokens"] == 16000
            assert "Original exact task with VaseVolume" in actor["messages"][-1]["content"][0]["text"]
            assert "TaskViews evidence" in actor["messages"][-1]["content"][1]["text"]
        actor = transport.requests[-1]
        assistant = next(m for m in actor["messages"] if m["role"] == "assistant")
        tool = next(m for m in actor["messages"] if m["role"] == "tool")
        assert assistant["reasoning_content"] == "original reasoning"
        assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"] == "call-1"
        assert agent.last_trace["protocol"] == views.PROTOCOL
        assert agent.last_trace["taskviews"]["executor_context"]["assigned_views"]
    finally:
        agent.close()


def test_taskviews_never_fabricates_action_when_adviser_json_is_bad(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "offline-only")
    monkeypatch.setenv("UI_KOBE_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("UI_KOBE_TASK_ID", "059")
    agent = views.KimiTaskViewsNativeAgent(model="kimi-k3", base_url="https://api.moonshot.ai/v1", temperature=1, max_tokens=16000)
    transport = Transport()
    transport.create = lambda **kwargs: response({"content": "bad-json"})
    agent.transport = transport
    agent.client.transport = transport
    buf = BytesIO()
    Image.new("RGB", (1920, 1080), "white").save(buf, "PNG")
    try:
        _, actions = agent.predict("Exact goal", {"screenshot": buf.getvalue()})
        assert actions == [] and agent.pending is None
        assert agent.view_trace['advisory_failure']
    finally:
        agent.close()


@pytest.mark.parametrize("task", ["059", "046"])
def test_official_task_arguments_keep_budget_and_task_identity(task, tmp_path):
    arguments = official_arguments(task, tmp_path / "official")
    for key, value in {"--max_steps": "500", "--specific_task_id": task, "--num_envs": "1",
                       "--screen_width": "1920", "--screen_height": "1080", "--sleep_after_execution": "3"}.items():
        assert arguments[arguments.index(key) + 1] == value
    assert "--stream" in arguments and "--batch_actions" in arguments
