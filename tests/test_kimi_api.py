import hashlib
import json
from pathlib import Path

import httpx
from openai import OpenAI
import pytest

from ui_kobe.api import client_from_config
from ui_kobe.api.kimi import BASE_URL, K3Requests, KimiClient, KimiConfig, install_official_k3_transport
from ui_kobe.osworld import telemetry
from scripts import osworld_task035_pipeline as pipeline
from scripts import osworld_task035_background as supervisor
from scripts.osworld_task035_profiles import validate_comparison_config


def completion(content="OK"):
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "kimi-k3",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content,
                        "reasoning_content": "original reasoning"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def sdk_with(handler):
    return OpenAI(api_key="offline", base_url=BASE_URL, max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_k3_actual_http_payload_and_preserved_message():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        assert str(request.url) == BASE_URL + "/chat/completions"
        return httpx.Response(200, json=completion())
    with KimiClient(KimiConfig(), sdk_client=sdk_with(handler)) as client:
        first = client.create(messages=[{"role": "user", "content": "first"}],
                              temperature=1, top_p=0.95, max_tokens=16000)
        client.create(messages=[{"role": "assistant", "content": [{"type": "text", "text": "OK"}]},
                                {"role": "user", "content": "second"}], max_tokens=16000)
    assert requests[0]["reasoning_effort"] == "max"
    assert requests[0]["max_completion_tokens"] == 16000
    assert not {"temperature", "top_p", "enable_thinking", "thinking", "max_tokens"} & requests[0].keys()
    assert requests[1]["messages"][0] == first.choices[0].message.model_dump(exclude_none=True)


@pytest.mark.parametrize("kwargs", [{"temperature": 0}, {"top_p": 0.9},
    {"reasoning_effort": "low"}, {"extra_body": {"thinking": {"type": "disabled"}}},
    {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
    {"model": "kimi-k2.5"}])
def test_k3_rejects_incompatible_parameters(kwargs):
    with pytest.raises(ValueError):
        K3Requests().prepare({"model": "kimi-k3", "messages": [], **kwargs})


def test_k3_requires_original_assistant_reasoning():
    with pytest.raises(ValueError, match="original response"):
        K3Requests().prepare({"model": "kimi-k3", "messages": [{"role": "assistant", "content": "invented"}]})


def test_k3_retains_the_official_500_turn_history():
    transport = K3Requests()
    from openai.types.chat import ChatCompletion
    for index in range(500):
        transport.remember(ChatCompletion.model_validate(completion(f"turn {index}")))
    messages = [{"role": "assistant", "content": f"turn {index}"} for index in range(500)]
    prepared = transport.prepare({"model": "kimi-k3", "messages": messages})
    assert len(prepared["messages"]) == 500
    assert all(m["reasoning_content"] == "original reasoning" for m in prepared["messages"])


def test_kimi_factory_does_not_fall_back_to_other_keys(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("QWEN_API_KEY", "unrelated")
    with pytest.raises(ValueError, match="KIMI_API_KEY"):
        client_from_config({"provider": "kimi"})
    monkeypatch.setenv("KIMI_API_KEY", "offline-kimi-key")
    with client_from_config({"provider": "kimi"}) as client:
        assert isinstance(client, KimiClient) and client._sdk.api_key == "offline-kimi-key"


def test_kimi_secret_redaction(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "offline-secret")
    assert telemetry.safe({"error": "Bearer offline-secret", "api_key": "offline-secret"}) == {
        "error": "Bearer [REDACTED]", "api_key": "[REDACTED]"}


def test_official_k3_transport_recreated_simulator_client(monkeypatch):
    original = OpenAI.__init__
    monkeypatch.setattr(OpenAI, "__init__", original)
    install_official_k3_transport()
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion(" OK "))
    with sdk_with(handler) as sdk:
        sdk.chat.completions.create(model="kimi-k3", messages=[{"role": "system", "content": "sim"}],
                                    temperature=1, top_p=0.95, max_tokens=16000,
                                    extra_body={"enable_thinking": False})
    with sdk_with(handler) as sdk:
        sdk.chat.completions.create(model="kimi-k3", messages=[{"role": "system", "content": "sim"},
            {"role": "assistant", "content": "OK"}, {"role": "user", "content": "next"}], max_tokens=16000)
    assert requests[1]["messages"][1]["reasoning_content"] == "original reasoning"
    assert requests[1]["messages"][1]["content"] == " OK "


def test_kimi_config_runner_and_resource_guards():
    config = json.loads((Path(__file__).resolve().parents[1] / "configs/osworld_kimi_k3_task_control.json").read_text())
    profile = validate_comparison_config(config)
    command = supervisor.runner_command({"model": "kimi-k3", "base_url": BASE_URL,
        "official_results": "/tmp/official", "run_dir": "/tmp/run"})
    assert profile["api_key_env"] == "KIMI_API_KEY"
    assert command[command.index("--model-profile") + 1] == "kimi-k3"
    assert command[command.index("--temperature") + 1] == "1"
    assert command[command.index("--top_p") + 1] == "0.95"
    assert command[command.index("--max_steps") + 1] == "500"
    assert supervisor.SERVICE_LIMIT + supervisor.DOCKER_LIMIT == int(5.75 * 1024**3)
    assert supervisor.START_AVAILABLE_GIB == 6
    config["api"]["extra_body"] = {"enable_thinking": False}
    with pytest.raises(RuntimeError):
        validate_comparison_config(config)


def test_official_model_argument_is_not_abbreviated_to_local_model_profile():
    from scripts.run_official_qwen_task035 import parse_local_arguments
    arguments = ["--model", "kimi-k3", "--base_url", BASE_URL, "--model-profile", "kimi-k3"]
    local, official = parse_local_arguments(arguments)
    assert local.model_profile == "kimi-k3"
    assert official == ["--model", "kimi-k3", "--base_url", BASE_URL]
    local, official = parse_local_arguments(["--model", "qwen3.8-max"])
    assert local.model_profile == "qwen" and official == ["--model", "qwen3.8-max"]


def test_k3_judge_translates_task035_hardcoded_temperature_zero_without_changing_prompt():
    from ui_kobe.osworld.qwen_judge import judge_request
    messages = [{"role": "user", "content": "Unmodified whole-table judgment prompt"}]
    request = judge_request("kimi-k3", messages, 4096, 0)
    assert request["messages"] == messages
    assert request["max_completion_tokens"] == 16000 and request["reasoning_effort"] == "max"
    assert "temperature" not in request and "top_p" not in request and "extra_body" not in request
    assert K3Requests().prepare(request) == request
    legacy = judge_request("qwen3.8-max", messages, 4096, 0)
    assert legacy["temperature"] == 0 and legacy["extra_body"] == {"enable_thinking": False}


def kimi_proof(tmp_path):
    supervisor.atomic(tmp_path / "taskviews-config.json", {})
    plan = {"model": "kimi-k3", "base_url": BASE_URL,
            "config_sha256": hashlib.sha256((tmp_path / "taskviews-config.json").read_bytes()).hexdigest()}
    proof = {"base_url": BASE_URL, "key_env": "KIMI_API_KEY", "probes": [
        {"case": case, "started_utc": supervisor.now(), "status_code": 200, "valid_chat_completion": True,
         "response_model": "kimi-k3", "finish_reason": "stop", "content_chars": 3, "reasoning_chars": 25,
         "request": {"model": "kimi-k3", "stream": False, "reasoning_effort": "max", "max_completion_tokens": 2048}}
        for case in ("control_text", "control_top_false_vision")]}
    supervisor.atomic(tmp_path / "probe.json", proof)
    return plan, proof


def test_kimi_recovery_accepts_reasoning_under_frozen_profile(tmp_path):
    plan, _ = kimi_proof(tmp_path)
    pipeline.require_recovery_probe(tmp_path, plan, tmp_path / "probe.json")


@pytest.mark.parametrize("change", [None, {"decisions": 1}, {"api_responses": 1}, {"official_score": "0"},
                                   {"cleanup_errors": ["failed"]}])
def test_adapter_retry_is_zero_request_only_and_separately_bounded(tmp_path, monkeypatch, change):
    plan, _ = kimi_proof(tmp_path)
    plan["unit"] = "fake.service"
    supervisor.atomic(tmp_path / "plan.json", plan)
    stage = tmp_path / "failed"
    supervisor.atomic(stage / "state.json", {"status": "failed", "cleanup_utc": supervisor.now(), **(change or {})})
    supervisor.atomic(stage / "manifest.json", {"official_results": str(stage / "official")})
    (stage / "console.log").write_text("K3 profile requires the exact official model and endpoint\n")
    supervisor.atomic(tmp_path / "state.json", {"status": "baseline_needs_attention", "active_arm": "baseline",
                      "active_run": "failed", "repair_round": 0})
    supervisor.atomic(stage / "project-source-before.json", {"scripts/run_official_qwen_task035.py": "old"})
    current = {"scripts/run_official_qwen_task035.py": "new"}
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: current)
    monkeypatch.setattr(pipeline, "require_recovery_cleanup", lambda *args: None)
    monkeypatch.setattr(pipeline, "render_comparison", lambda *args: None)
    supervisor.atomic(tmp_path / "validation.json", {"status": "passed", "exit_code": 0,
                      "tests_passed": 1, "project_source_sha256": current})
    supervisor.atomic(tmp_path / "note.json", {"cause": "abbreviated --model", "changes": "disable abbreviation",
                      "validation": "argument forwarding test"})
    if change:
        with pytest.raises(RuntimeError):
            pipeline.queue_adapter_preflight_baseline(tmp_path, tmp_path / "note.json", tmp_path / "validation.json", tmp_path / "probe.json")
        assert not (tmp_path / "preparation-retries.jsonl").exists()
    else:
        pipeline.queue_adapter_preflight_baseline(tmp_path, tmp_path / "note.json", tmp_path / "validation.json", tmp_path / "probe.json")
        state = supervisor.read_json(tmp_path / "state.json")
        assert state["status"] == "prepared" and state["adapter_preflight_retries"] == 1 and state["repair_round"] == 0
        with pytest.raises(RuntimeError):
            pipeline.queue_adapter_preflight_baseline(tmp_path, tmp_path / "note.json", tmp_path / "validation.json", tmp_path / "probe.json")


@pytest.mark.parametrize("change", [None, "score", "judge_api", "action_error", "wrong_code"])
def test_judge_adapter_recovery_requires_sole_pre_request_failure(tmp_path, monkeypatch, change):
    plan, _ = kimi_proof(tmp_path)
    plan["unit"] = "fake.service"
    supervisor.atomic(tmp_path / "plan.json", plan)
    stage, official = tmp_path / "failed", tmp_path / "failed" / "official"
    supervisor.atomic(stage / "state.json", {"status": "failed", "cleanup_utc": supervisor.now(),
                      "decisions": 1, "completed_actions": 1})
    supervisor.atomic(stage / "manifest.json", {"official_results": str(official)})
    supervisor.atomic(official / "source-audit.json", {"unchanged": True})
    (stage / "console.log").write_text("ValueError: K3 temperature is fixed at 1")
    events = [{"event": "decision"}, {"event": "action_result", "action": "DONE", "done": True},
              {"event": "evaluation_error", "error": "Task035 evaluator failed during the LLM whole-table judgment."}]
    if change in ("judge_api", "action_error"):
        events.append({"event": "api_request" if change == "judge_api" else "action_error", "phase": "judge"})
    if change == "score":
        (official / "result.txt").write_text("0")
    supervisor.atomic(stage / "telemetry" / "events-1.jsonl", "".join(json.dumps(e) + "\n" for e in events))
    supervisor.atomic(tmp_path / "state.json", {"status": "baseline_needs_attention", "active_arm": "baseline",
                      "active_run": "failed", "repair_round": 0})
    before = {"ui_kobe/osworld/qwen_judge.py": "old", "ui_kobe/osworld/agent.py": "unchanged"}
    current = {**before, "ui_kobe/osworld/qwen_judge.py": "new"}
    if change == "wrong_code":
        current["ui_kobe/osworld/agent.py"] = "changed"
    supervisor.atomic(stage / "project-source-before.json", before)
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: current)
    monkeypatch.setattr(pipeline, "require_recovery_cleanup", lambda *args: None)
    monkeypatch.setattr(pipeline, "render_comparison", lambda *args: None)
    supervisor.atomic(tmp_path / "validation.json", {"status": "passed", "exit_code": 0,
                      "tests_passed": 1, "project_source_sha256": current})
    supervisor.atomic(tmp_path / "note.json", {"cause": "judge temperature", "changes": "K3 protocol",
                      "validation": "real task options remain fixed"})
    if change:
        with pytest.raises(RuntimeError):
            pipeline.queue_judge_adapter_baseline(tmp_path, tmp_path / "note.json", tmp_path / "validation.json", tmp_path / "probe.json")
        assert not (tmp_path / "preparation-retries.jsonl").exists()
    else:
        pipeline.queue_judge_adapter_baseline(tmp_path, tmp_path / "note.json", tmp_path / "validation.json", tmp_path / "probe.json")
        state = supervisor.read_json(tmp_path / "state.json")
        assert state["status"] == "prepared" and state["judge_adapter_retries"] == 1 and state["repair_round"] == 0
        assert (stage / "telemetry" / "events-1.jsonl").read_text() == "".join(json.dumps(e) + "\n" for e in events)
        with pytest.raises(RuntimeError):
            pipeline.queue_judge_adapter_baseline(tmp_path, tmp_path / "note.json", tmp_path / "validation.json", tmp_path / "probe.json")


@pytest.mark.parametrize("field,value", [("temperature", 0), ("extra_body", {"enable_thinking": False}),
    ("reasoning_effort", "low"), ("model", "kimi-k2.5")])
def test_kimi_recovery_rejects_changed_settings(tmp_path, field, value):
    plan, proof = kimi_proof(tmp_path)
    proof["probes"][0]["request"][field] = value
    supervisor.atomic(tmp_path / "probe.json", proof)
    with pytest.raises(RuntimeError):
        pipeline.require_recovery_probe(tmp_path, plan, tmp_path / "probe.json")
