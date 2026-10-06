import json
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts import osworld_task035_pipeline as pipeline
from scripts import osworld_task035_background as supervisor
from scripts import launch_osworld_task035_pipeline as launcher
from ui_kobe.osworld.official_adapter import TaskViewsOfficialAgent, install_taskviews_execution_guard
from ui_kobe.osworld import telemetry
from scripts.run_official_qwen_task035 import minimal_preflight


def test_new_comparison_report_preserves_previous_report(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "PROJECT", tmp_path)
    previous = tmp_path / "docs" / "previous.md"
    previous.parent.mkdir()
    previous.write_text("previous completed experiment")
    monkeypatch.setattr(pipeline, "REPORT", previous)
    root = tmp_path / "docs" / "experiments" / "new-comparison"
    target = tmp_path / "docs" / "new-comparison.md"
    supervisor.atomic(root / "plan.json", {"unit": "new.service", "report_path": str(target)})
    supervisor.atomic(root / "state.json", {"status": "prepared", "repair_round": 0, "runs": []})
    supervisor.atomic(root / "taskviews-config.json", {"agent": {"task_control": {"enabled": True}}})
    pipeline.render_comparison(root)
    assert previous.read_text() == "previous completed experiment"
    text = target.read_text()
    assert "动态角色视图" in text and "3–5" in text and "5.75" in text
    assert "6 GiB" in text and "10 GiB" not in text


def test_complete_experiment_attempts_never_share_task_memory(tmp_path):
    original = {"api": {"model": "qwen3.8-max"}, "agent": {
        "temperature": 0, "context_bytes": 32000, "task_control": {
            "enabled": True, "memory_dir": "prior-memory", "max_fail_reviews": 2}}}
    supervisor.atomic(tmp_path / "taskviews-config.json", original)
    before = (tmp_path / "taskviews-config.json").read_bytes()
    paths = []
    for name in ("taskviews-r00", "taskviews-r01"):
        path = tmp_path / name
        path.mkdir()
        derived = pipeline.stage_taskviews_config(tmp_path, path)
        actual = json.loads(derived.read_text())
        paths.append(actual["agent"]["task_control"]["memory_dir"])
        actual["agent"]["task_control"]["memory_dir"] = "prior-memory"
        assert actual == original  # Only the persistence directory is rebased.
    assert paths[0] != paths[1]
    assert (tmp_path / "taskviews-config.json").read_bytes() == before
    (tmp_path / "taskviews-r00" / "taskviews-memory").mkdir()
    with pytest.raises(RuntimeError, match="reuse existing task memory"):
        pipeline.stage_taskviews_config(tmp_path, tmp_path / "taskviews-r00")


def test_legacy_experiment_configuration_is_not_rewritten(tmp_path):
    source = tmp_path / "taskviews-config.json"
    supervisor.atomic(source, {"api": {"model": "qwen3.8-max"}, "agent": {"context_bytes": 16000}})
    assert pipeline.stage_taskviews_config(tmp_path, tmp_path / "legacy-r00") == source


def test_launcher_requires_passing_tests_for_current_code(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "snapshot_project", lambda: {"agent.py": "new"})
    path = tmp_path / "validation.json"
    validation = {"status": "passed", "exit_code": 0, "tests_passed": 4,
                  "project_source_sha256": {"agent.py": "new"}}
    supervisor.atomic(path, validation)
    assert launcher.require_validation(path) == validation
    for change in ({"exit_code": 1}, {"tests_passed": 0},
                   {"project_source_sha256": {"agent.py": "old"}}):
        supervisor.atomic(path, {**validation, **change})
        with pytest.raises(RuntimeError, match="Current project code"):
            launcher.require_validation(path)


def resource_stopped_setup(root, monkeypatch):
    stage = root / "baseline-r00"
    official = stage / "official"
    official.mkdir(parents=True)
    supervisor.atomic(root / "taskviews-config.json", {})
    supervisor.atomic(root / "plan.json", {"unit": "test.service", "config_sha256":
        hashlib.sha256((root / "taskviews-config.json").read_bytes()).hexdigest()})
    supervisor.atomic(root / "state.json", {"status": "baseline_needs_attention", "active_arm": "baseline",
        "active_run": "baseline-r00", "repair_round": 0, "runs": [{"arm": "baseline", "directory": "baseline-r00"}]})
    supervisor.atomic(stage / "manifest.json", {"run_id": "test-baseline-r00", "official_results": str(official)})
    progress = {"status": "stopped", "reason": "Windows 内存或磁盘保留量触发保护停止。",
        "decisions": 0, "completed_actions": 0, "api_responses": 0, "api_errors": 0,
        "official_score": None, "cleanup_errors": [], "cleanup_utc": "verified",
        "latest_resources": {"windows": {"available_ram_gib": 3.89, "c_free_gib": 100, "d_free_gib": 30},
                             "service_memory_events": {"oom": "0", "oom_kill": "0"}}}
    supervisor.atomic(stage / "state.json", progress)
    checks = []
    monkeypatch.setattr(pipeline, "require_recovery_cleanup", lambda *args: checks.append(args))
    monkeypatch.setattr(pipeline, "render_comparison", lambda _: None)
    return stage, official, progress, checks


def test_unstarted_resource_requeue_requires_cleanup_and_preserves_guards(tmp_path, monkeypatch):
    stage, official, progress, checks = resource_stopped_setup(tmp_path, monkeypatch)
    pipeline.queue_resource_stopped_baseline(tmp_path)
    state = supervisor.read_json(tmp_path / "state.json")
    record = json.loads((tmp_path / "preparation-retries.jsonl").read_text())
    assert state["status"] == "prepared" and state["repair_round"] == 0
    assert state["unstarted_resource_retries"] == record["retry"] == 1
    assert len(checks) == 1 and checks[0][2] == official
    assert pipeline.START_RESERVE_GIB == 6
    assert supervisor.read_json(stage / "state.json") == progress


@pytest.mark.parametrize("change", [{"decisions": 1}, {"api_responses": 1}, {"api_errors": 1},
    {"completed_actions": 1}, {"official_score": "0"}, {"cleanup_errors": ["failed"]},
    {"status": "failed"}, {"latest_resources": {"windows": {"available_ram_gib": 4.01}}},
    {"latest_resources": {"windows": {"available_ram_gib": 6, "c_free_gib": 36, "d_free_gib": 20}}}])
def test_resource_requeue_rejects_started_or_different_failures(tmp_path, monkeypatch, change):
    stage, official, progress, checks = resource_stopped_setup(tmp_path, monkeypatch)
    supervisor.atomic(stage / "state.json", {**progress, **change})
    with pytest.raises(RuntimeError, match="prevents resource requeue"):
        pipeline.queue_resource_stopped_baseline(tmp_path)
    assert not checks and not (tmp_path / "preparation-retries.jsonl").exists()


@pytest.mark.parametrize("evidence", ["request", "score", "exhausted", "source"])
def test_resource_requeue_rechecks_raw_evidence_retry_limit_and_source(tmp_path, monkeypatch, evidence):
    stage, official, progress, checks = resource_stopped_setup(tmp_path, monkeypatch)
    if evidence == "request":
        supervisor.atomic(stage / "telemetry" / "events-1.jsonl", '{"event":"api_request"}\n')
    elif evidence == "score":
        (official / "result.txt").write_text("0.0")
    elif evidence == "exhausted":
        (tmp_path / "preparation-retries.jsonl").write_text(
            '\n'.join(json.dumps({"kind": "unstarted_resource_recovery"}) for _ in range(3)))
    else:
        def reject_source(*args):
            raise RuntimeError("OSWorld source changed")
        monkeypatch.setattr(pipeline, "require_recovery_cleanup", reject_source)
    with pytest.raises(RuntimeError):
        pipeline.queue_resource_stopped_baseline(tmp_path)
    assert supervisor.read_json(tmp_path / "state.json")["status"] == "baseline_needs_attention"


def test_transport_cause_logging_is_bounded_and_redacts_environment_key(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "offline-secret")
    cause = ConnectionError("offline-secret: transport reset")
    error = RuntimeError("request failed")
    error.__cause__ = cause
    cause.__cause__ = error  # Cycle cannot make logging unbounded.
    assert telemetry.exception_causes(error) == [
        {"type": "ConnectionError", "error": "[REDACTED]: transport reset"}]


@pytest.mark.parametrize("result", [None, {}, {"status": "error", "returncode": 1},
                                    {"status": "success", "returncode": False},
                                    {"status": "success", "returncode": "0"}])
def test_official_taskviews_guard_never_accepts_unconfirmed_execution(monkeypatch, result):
    class Controller:
        def execute_python_command(self, command):
            return result

    events = []
    monkeypatch.setattr(telemetry, "in_agent_action", lambda: True)
    monkeypatch.setattr(telemetry, "emit", lambda kind, **fields: events.append((kind, fields)))
    install_taskviews_execution_guard(Controller)
    with pytest.raises(RuntimeError, match="failed or unconfirmed"):
        Controller().execute_python_command("pyautogui.click(1, 2)")
    assert events[0][0] == "execution_unconfirmed" and events[0][1]["result"] == result


def test_official_taskviews_guard_preserves_success_setup_and_judge_results(monkeypatch):
    reply = {"status": "success", "returncode": 0, "output": ""}

    class Controller:
        def execute_python_command(self, command):
            return reply

    monkeypatch.setattr(telemetry, "in_agent_action", lambda: True)
    install_taskviews_execution_guard(Controller)
    wrapped = Controller.execute_python_command
    install_taskviews_execution_guard(Controller)
    assert Controller.execute_python_command is wrapped  # No stacking on resets.
    assert Controller().execute_python_command("GUI action") is reply
    monkeypatch.setattr(telemetry, "in_agent_action", lambda: False)
    reply = None
    assert Controller().execute_python_command("setup or judge") is None


def completed_stage(path, score="0", audit=True):
    path.mkdir(parents=True, exist_ok=True)
    official = path / "official"
    official.mkdir(exist_ok=True)
    supervisor.atomic(official / "source-audit.json", {"unchanged": audit})
    supervisor.atomic(path / "manifest.json", {"official_results": str(official)})
    supervisor.atomic(path / "state.json", {"status": "completed", "official_score": score, "cleanup_errors": []})


def test_real_zero_is_complete_but_missing_score_or_changed_source_is_not(tmp_path):
    completed_stage(tmp_path, "0")
    assert pipeline.stage_accepted(tmp_path)
    completed_stage(tmp_path, None)
    assert not pipeline.stage_accepted(tmp_path)
    completed_stage(tmp_path, "0", audit=False)
    assert not pipeline.stage_accepted(tmp_path)


def test_error_with_candidate_score_cannot_be_accepted(tmp_path):
    completed_stage(tmp_path, "0.5")
    trace = tmp_path / "telemetry"
    trace.mkdir()
    (trace / "events-1.jsonl").write_text(json.dumps({"event": "framework_error"}) + "\n")
    assert not pipeline.stage_accepted(tmp_path)


def test_repair_budget_and_no_unchanged_retries(tmp_path, monkeypatch):
    supervisor.atomic(tmp_path / "state.json", {"status": "experiment_needs_repair", "repair_round": 10})
    with pytest.raises(RuntimeError, match="exhausted"):
        pipeline.record_repair(tmp_path, tmp_path / "unused.json")
    stage = tmp_path / "failed"
    stage.mkdir()
    supervisor.atomic(stage / "project-source-before.json", {"worker.py": "hash1"})
    supervisor.atomic(tmp_path / "state.json", {"status": "experiment_needs_repair", "repair_round": 0, "active_run": "failed"})
    note = tmp_path / "note.json"
    supervisor.atomic(note, {"cause": "bad transport", "changes": "validate reply", "validation": "passed"})
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: {"worker.py": "hash1"})
    with pytest.raises(ValueError, match="No project code change"):
        pipeline.record_repair(tmp_path, note)
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: {"worker.py": "hash2"})
    monkeypatch.setattr(pipeline, "render_comparison", lambda _: None)
    pipeline.record_repair(tmp_path, note)
    state = supervisor.read_json(tmp_path / "state.json")
    assert state["repair_round"] == 1 and state["status"] == "experiment_queued"
    assert json.loads((tmp_path / "repairs.jsonl").read_text())["changed_paths"] == ["worker.py"]


def test_both_arms_share_model_and_harness_limits(tmp_path):
    baseline = {"run_dir": str(tmp_path), "official_results": str(tmp_path / "results"),
                "model": "qwen3.8-max", "base_url": "https://pjfdspqowq.a.pinggy.link"}
    experiment = {**baseline, "arm": "taskviews", "taskviews_config": str(tmp_path / "config.json")}
    command = supervisor.runner_command(baseline)
    assert supervisor.runner_command(experiment)[:-2] == command
    assert command[command.index("--max_steps") + 1] == "500"
    assert command[command.index("--model") + 1] == "qwen3.8-max"
    assert supervisor.SERVICE_LIMIT + supervisor.DOCKER_LIMIT < 6 * supervisor.GIB


def test_adapter_rejects_model_mismatch_before_spawning(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    supervisor.atomic(config, {"api": {"model": "other", "base_url": "https://example.invalid"},
                               "agent": {"temperature": 0, "max_output_tokens": 16000}})
    monkeypatch.setenv("UI_KOBE_TASKVIEWS_CONFIG", str(config))
    with pytest.raises(ValueError, match="settings differ"):
        TaskViewsOfficialAgent(model="qwen3.8-max", base_url="https://example.invalid", temperature=0, max_tokens=16000)


@pytest.mark.parametrize("baseline_score", ["0", None])
def test_serial_pipeline_only_starts_experiment_after_a_valid_baseline(tmp_path, monkeypatch, baseline_score):
    config = tmp_path / "taskviews-config.json"
    supervisor.atomic(config, {})
    plan = {"unit": "fake.service", "model": "qwen3.8-max", "base_url": "https://example.invalid",
            "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest()}
    supervisor.atomic(tmp_path / "plan.json", plan)
    supervisor.atomic(tmp_path / "state.json", {"status": "prepared", "repair_round": 0, "runs": []})
    calls = []

    def fake_run(path, unit, options):
        calls.append(options["arm"])
        completed_stage(path, baseline_score if options["arm"] == "baseline" else "0.5")

    monkeypatch.setattr(supervisor, "run", fake_run)
    monkeypatch.setattr(supervisor, "verify_service_budget", lambda: None)
    monkeypatch.setattr(supervisor, "host_status", lambda: {"available_ram_gib": 11, "c_free_gib": 100, "d_free_gib": 30})
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: {})
    monkeypatch.setattr(pipeline, "render_comparison", lambda _: None)
    pipeline.run(tmp_path)
    state = supervisor.read_json(tmp_path / "state.json")
    assert calls == (["baseline", "taskviews"] if baseline_score is not None else ["baseline"])
    assert state["status"] == ("completed" if baseline_score is not None else "baseline_needs_attention")


def test_waits_for_startup_margin_before_allocating_a_stage(tmp_path, monkeypatch):
    samples = iter([{"available_ram_gib": 5.9, "c_free_gib": 100, "d_free_gib": 30},
                    {"available_ram_gib": 6.0, "c_free_gib": 100, "d_free_gib": 30}])
    sleeps = []
    monkeypatch.setattr(supervisor, "host_status", lambda: next(samples))
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    monkeypatch.setattr(pipeline, "render_comparison", lambda _: None)
    state = {}
    pipeline.wait_resources(tmp_path, state, "baseline")
    assert sleeps == [30]
    assert state["waiting_windows"]["available_ram_gib"] == 6.0
    assert not state.get("active_run")


@pytest.mark.parametrize("ram,c_disk,d_disk,active,kvm,blocked", [
    (6, 45, 12, False, True, None),
    (5.99, 100, 30, False, True, "at least 6"),
    (6.1, 44, 30, False, True, "Disk reserve"),
    (6.1, 100, 11, False, True, "Disk reserve"),
    (6.1, 100, 30, True, True, "already running"),
    (6.1, 100, 30, False, False, "KVM"),
])
def test_minimal_vm_guard_uses_six_gib_and_preserves_other_checks(tmp_path, ram, c_disk, d_disk, active, kvm, blocked):
    status = {"available_ram_gib": ram, "c_free_gib": c_disk, "d_free_gib": d_disk}
    filters_seen = []

    def desktops(*, filters):
        filters_seen.append(filters)
        return [object()] if active else []

    client = SimpleNamespace(containers=SimpleNamespace(list=desktops))
    budget = SimpleNamespace(host_status=lambda: status, LABEL="owner", OWNER="this-profile")
    device = tmp_path / "kvm"
    if kvm:
        device.touch()
    assert pipeline.START_RESERVE_GIB == supervisor.START_AVAILABLE_GIB == 6
    if blocked:
        with pytest.raises(RuntimeError, match=blocked):
            minimal_preflight(client, budget, device)
    else:
        assert minimal_preflight(client, budget, device) == status
        assert filters_seen == [{"label": "owner=this-profile"}]


def test_preparation_retry_never_repeats_a_baseline_with_an_action(tmp_path, monkeypatch):
    stage = tmp_path / "failed"
    stage.mkdir()
    supervisor.atomic(tmp_path / "state.json", {"status": "baseline_needs_attention", "active_run": "failed"})
    supervisor.atomic(stage / "state.json", {"official_score": None, "completed_actions": 1})
    (stage / "console.log").write_text("Windows available RAM 7.92 GiB")
    with pytest.raises(RuntimeError, match="Refusing to repeat"):
        pipeline.queue_unstarted_baseline(tmp_path)


def recovery_fixture(root, monkeypatch):
    stage = root / "failed"
    official = stage / "official"
    trace = stage / "telemetry"
    official.mkdir(parents=True)
    trace.mkdir()
    supervisor.atomic(root / "taskviews-config.json", {})
    settings = {"model": "qwen3.8-max", "base_url": "https://example.invalid"}
    supervisor.atomic(root / "plan.json", {**settings, "unit": "fake.service",
                      "config_sha256": hashlib.sha256((root / "taskviews-config.json").read_bytes()).hexdigest()})
    supervisor.atomic(root / "state.json", {"status": "baseline_needs_attention", "active_arm": "baseline",
                      "active_run": "failed", "repair_round": 0,
                      "runs": [{"arm": "baseline", "directory": "earlier"}, {"arm": "baseline", "directory": "failed"}]})
    supervisor.atomic(stage / "state.json", {"status": "failed", "official_score": None,
                      "decisions": 0, "completed_actions": 0, "api_responses": 0, "api_errors": 1,
                      "cleanup_errors": [], "cleanup_utc": supervisor.now()})
    supervisor.atomic(stage / "manifest.json", {**settings, "run_id": "failed", "official_results": str(official)})
    supervisor.atomic(official / "source-audit.json", {"unchanged": True})
    event = {"event": "api_error", "error_type": "APIConnectionError", "status_code": None}
    (trace / "events-1.jsonl").write_text(json.dumps(event) + "\n")
    request = {"model": settings["model"], "temperature": 0, "top_p": 0.9,
               "stream": False, "extra_body": {"enable_thinking": False}}
    proof = {"base_url": settings["base_url"], "key_env": "QWEN_API_KEY", "probes": [
        {"case": case, "started_utc": supervisor.now(), "status_code": 200, "valid_chat_completion": True,
         "response_model": settings["model"], "content_chars": 3, "reasoning_chars": 0, "request": request}
        for case in ("control_text", "control_top_false_vision")]}
    probe = root / "probe.json"
    supervisor.atomic(probe, proof)
    checks = []
    monkeypatch.setattr(pipeline, "require_recovery_cleanup", lambda *args: checks.append(args))
    monkeypatch.setattr(pipeline, "render_comparison", lambda _: None)
    return stage, official, trace, probe, checks


def test_recovery_only_queues_a_clean_new_run_and_retains_failures(tmp_path, monkeypatch):
    stage, official, trace, probe, checks = recovery_fixture(tmp_path, monkeypatch)
    evidence = (trace / "events-1.jsonl").read_bytes()
    pipeline.queue_recovered_baseline(tmp_path, probe)
    state = supervisor.read_json(tmp_path / "state.json")
    assert state["status"] == "prepared" and state["repair_round"] == 0
    assert state["active_run"] == "failed" and len(state["runs"]) == 2
    assert len(checks) == 1 and state["last_api_recovery"]["startup_available_ram_gib"] == 6
    assert (trace / "events-1.jsonl").read_bytes() == evidence
    assert len((tmp_path / "connection-retries.jsonl").read_text().splitlines()) == 1
    with pytest.raises(RuntimeError, match="Not an incomplete"):
        pipeline.queue_recovered_baseline(tmp_path, probe)
    next_run = pipeline.new_stage(tmp_path, state, "baseline")
    assert next_run.name.endswith("baseline-r02")


@pytest.mark.parametrize("condition", [
    "zero_score", "decision", "model_response", "action", "missing_cleanup", "cleanup_error",
    "score_file", "audit_changed", "permission_error", "hidden_response", "stale_probe",
    "missing_vision", "bad_completion", "wrong_model", "changed_config", "live_components",
])
def test_recovery_refuses_to_rerun_scored_or_active_or_unverified_baselines(tmp_path, monkeypatch, condition):
    stage, official, trace, probe, checks = recovery_fixture(tmp_path, monkeypatch)
    progress = supervisor.read_json(stage / "state.json")
    proof = supervisor.read_json(probe)
    if condition == "zero_score":
        progress["official_score"] = "0"
    elif condition in ("decision", "model_response", "action"):
        progress[{"decision": "decisions", "model_response": "api_responses", "action": "completed_actions"}[condition]] = 1
    elif condition == "missing_cleanup":
        progress.pop("cleanup_utc")
    elif condition == "cleanup_error":
        progress["cleanup_errors"] = ["still running"]
    elif condition == "score_file":
        (official / "result.txt").write_text("0")
    elif condition == "audit_changed":
        supervisor.atomic(official / "source-audit.json", {"unchanged": False})
    elif condition == "permission_error":
        (trace / "events-1.jsonl").write_text(json.dumps({"event": "api_error", "error_type": "APIStatusError", "status_code": 403}) + "\n")
    elif condition == "hidden_response":
        with (trace / "events-1.jsonl").open("a") as history:
            history.write(json.dumps({"event": "api_response"}) + "\n")
    elif condition == "stale_probe":
        proof["probes"][1]["started_utc"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    elif condition == "missing_vision":
        proof["probes"].pop()
    elif condition == "bad_completion":
        proof["probes"][1]["valid_chat_completion"] = False
    elif condition == "wrong_model":
        proof["probes"][1]["response_model"] = "other-model"
    elif condition == "changed_config":
        supervisor.atomic(tmp_path / "taskviews-config.json", {"modified": True})
    elif condition == "live_components":
        def incomplete(*args):
            raise RuntimeError("The failed run's VM has not been removed")
        monkeypatch.setattr(pipeline, "require_recovery_cleanup", incomplete)
    supervisor.atomic(stage / "state.json", progress)
    supervisor.atomic(probe, proof)
    with pytest.raises(RuntimeError):
        pipeline.queue_recovered_baseline(tmp_path, probe)
    assert supervisor.read_json(tmp_path / "state.json")["status"] == "baseline_needs_attention"
    assert not (tmp_path / "connection-retries.jsonl").exists()


@pytest.mark.parametrize("condition", ["clean", "service_active", "vm_present", "web_running", "source_changed"])
def test_actual_cleanup_checks_work_with_docker_clients_without_context_manager(tmp_path, monkeypatch, condition):
    from ui_kobe.osworld import runner
    original = {"file.py": "hash"}
    supervisor.atomic(tmp_path / "osworld-source-before.json", original)
    closed = []

    def containers(*, filters, all=False):
        return [object()] if condition == "vm_present" else []

    web = SimpleNamespace(labels={"com.docker.compose.project": "osworld-local-web"},
                          attrs={"State": {"Running": condition == "web_running"}}, reload=lambda: None)
    client = SimpleNamespace(containers=SimpleNamespace(list=containers, get=lambda _: web),
                             close=lambda: closed.append(True))
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda **kwargs: client))
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout="active" if condition == "service_active" else "inactive"))
    monkeypatch.setattr(runner, "source_snapshot", lambda _: {"file.py": "changed"} if condition == "source_changed" else original)
    manifest = {"run_id": "failed", "web_owned": True, "web_container_ids": ["owned-web"]}
    if condition == "clean":
        pipeline.require_recovery_cleanup({"unit": "fake.service"}, manifest, tmp_path)
    else:
        with pytest.raises(RuntimeError):
            pipeline.require_recovery_cleanup({"unit": "fake.service"}, manifest, tmp_path)
    assert closed == ([] if condition == "service_active" else [True])


def experiment_recovery_fixture(root, monkeypatch):
    stage, official, trace, probe, checks = recovery_fixture(root, monkeypatch)
    plan = supervisor.read_json(root / "plan.json")
    plan["max_steps"] = 500
    supervisor.atomic(root / "plan.json", plan)
    baseline = root / "baseline"
    completed_stage(baseline, "0")
    state = supervisor.read_json(root / "state.json")
    state.update(status="experiment_needs_repair", active_arm="taskviews", baseline_completed=True, repair_round=3,
                 runs=[{"arm": "baseline", "directory": "baseline"},
                       {"arm": "taskviews", "directory": "failed", "repair_round": 3}])
    supervisor.atomic(root / "state.json", state)
    progress = supervisor.read_json(stage / "state.json")
    progress.update(decisions=1, completed_actions=1, api_responses=2, api_errors=3)
    supervisor.atomic(stage / "state.json", progress)
    manifest = supervisor.read_json(stage / "manifest.json")
    manifest["arm"] = "taskviews"
    supervisor.atomic(stage / "manifest.json", manifest)
    hashes = {"ui_kobe/osworld/agent.py": "frozen-agent", "scripts/osworld_task035_pipeline.py": "old-entry"}
    supervisor.atomic(stage / "project-source-before.json", hashes)
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: {**hashes, "scripts/osworld_task035_pipeline.py": "new-entry"})
    events = [{"event": "api_response", "step": 1, "phase": phase} for phase in ("perception", "decision")]
    events += [{"event": "decision", "step": 1}, {"event": "controller_result", "step": 1, "phase": "action",
                "result": {"status": "success", "returncode": 0}}, {"event": "action_result", "step": 1}]
    events += [{"event": "api_error", "step": 2, "phase": "perception", "error_type": "APIConnectionError",
                "status_code": None, "time_utc": str(index), "error_causes": [{"type": "RemoteProtocolError"}]} for index in range(3)]
    events += [{"event": kind, "step": 2, "error": "QWEN request_failed; HTTP=n/a; code=n/a; attempts=3"}
               for kind in ("framework_error", "decision_error")]
    (trace / "events-1.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    return stage, official, trace, probe, checks, events


def test_experiment_transport_recovery_has_independent_budget_and_preserves_zero_baseline(tmp_path, monkeypatch):
    stage, official, trace, probe, checks, events = experiment_recovery_fixture(tmp_path, monkeypatch)
    evidence = (trace / "events-1.jsonl").read_bytes()
    pipeline.queue_recovered_experiment(tmp_path, probe)
    state = supervisor.read_json(tmp_path / "state.json")
    assert state["status"] == "experiment_queued" and state["repair_round"] == 3
    assert state["experiment_connection_retries"] == 1 and len(checks) == 1
    assert pipeline.stage_accepted(tmp_path / "baseline")
    assert (trace / "events-1.jsonl").read_bytes() == evidence
    assert not (tmp_path / "repairs.jsonl").exists()
    assert pipeline.new_stage(tmp_path, state, "taskviews").name.endswith("taskviews-r03-api01")
    assert "pending_experiment_connection_retry" not in state
    with pytest.raises(RuntimeError):
        pipeline.queue_recovered_experiment(tmp_path, probe)


@pytest.mark.parametrize("model,error_provider,accepted", [
    ("qwen3.8-max", "QWEN", True),
    ("kimi-k3", "KIMI", True),
    ("qwen3.8-max", "KIMI", False),
    ("kimi-k3", "QWEN", False),
    ("kimi-k3", "OTHER", False),
])
def test_experiment_recovery_matches_the_fixed_provider(tmp_path, monkeypatch, model, error_provider, accepted):
    stage, official, trace, probe, checks, events = experiment_recovery_fixture(tmp_path, monkeypatch)
    plan = supervisor.read_json(tmp_path / "plan.json")
    manifest = supervisor.read_json(stage / "manifest.json")
    proof = supervisor.read_json(probe)
    if model == "kimi-k3":
        endpoint = "https://api.moonshot.ai/v1"
        plan.update(model=model, base_url=endpoint)
        manifest.update(model=model, base_url=endpoint)
        proof.update(base_url=endpoint, key_env="KIMI_API_KEY")
        for item in proof["probes"]:
            item.update(response_model=model, reasoning_chars=10, finish_reason="stop",
                        request={"model": model, "stream": False,
                                 "reasoning_effort": "max", "max_completion_tokens": 2048})
    for event in events[-2:]:
        event["error"] = f"{error_provider} request_failed; HTTP=n/a; code=n/a; attempts=3"
    supervisor.atomic(tmp_path / "plan.json", plan)
    supervisor.atomic(stage / "manifest.json", manifest)
    supervisor.atomic(probe, proof)
    evidence = "".join(json.dumps(event) + "\n" for event in events)
    (trace / "events-1.jsonl").write_text(evidence)
    if accepted:
        pipeline.queue_recovered_experiment(tmp_path, probe)
        state = supervisor.read_json(tmp_path / "state.json")
        assert state["status"] == "experiment_queued"
        assert state["experiment_connection_retries"] == 1 and state["repair_round"] == 3
        assert len(checks) == 1
    else:
        with pytest.raises(RuntimeError, match="project, action or policy error"):
            pipeline.queue_recovered_experiment(tmp_path, probe)
        assert supervisor.read_json(tmp_path / "state.json")["status"] == "experiment_needs_repair"
        assert not (tmp_path / "connection-retries.jsonl").exists()
    assert (trace / "events-1.jsonl").read_text() == evidence
    assert not (tmp_path / "repairs.jsonl").exists()


@pytest.mark.parametrize("condition", [
    "scored", "score_file", "500_steps", "cleanup", "source", "agent_changed", "baseline_invalid",
    "action_null", "action_error", "geometry_error", "http_error", "unknown_cause", "no_cause",
    "two_attempts", "wrong_failure_step", "judge_called", "count_mismatch", "stale_probe", "missing_vision",
    "budget_exhausted", "counter_reset", "live_components",
])
def test_experiment_recovery_refuses_policy_failures_and_incomplete_or_active_evidence(tmp_path, monkeypatch, condition):
    stage, official, trace, probe, checks, events = experiment_recovery_fixture(tmp_path, monkeypatch)
    progress = supervisor.read_json(stage / "state.json")
    state = supervisor.read_json(tmp_path / "state.json")
    proof = supervisor.read_json(probe)
    if condition == "scored":
        progress["official_score"] = "0"
    elif condition == "score_file":
        (official / "result.txt").write_text("0")
    elif condition == "500_steps":
        progress["decisions"] = 500
    elif condition == "cleanup":
        progress.pop("cleanup_utc")
    elif condition == "source":
        supervisor.atomic(official / "source-audit.json", {"unchanged": False})
    elif condition == "agent_changed":
        monkeypatch.setattr(pipeline, "snapshot_project", lambda: {"ui_kobe/osworld/agent.py": "changed"})
    elif condition == "baseline_invalid":
        completed_stage(tmp_path / "baseline", None)
    elif condition == "action_null":
        events[3]["result"] = None
    elif condition == "action_error":
        events.append({"event": "execution_unconfirmed"})
    elif condition == "geometry_error":
        events[-2]["error"] = "Invalid bbox"
    elif condition == "http_error":
        events[5]["status_code"] = 403
    elif condition == "unknown_cause":
        events[5]["error_causes"] = [{"type": "ValueError"}]
    elif condition == "no_cause":
        events[5].pop("error_causes")
    elif condition == "two_attempts":
        events.pop(5)
        progress["api_errors"] = 2
    elif condition == "wrong_failure_step":
        events[5]["step"] = 1
    elif condition == "judge_called":
        events.append({"event": "api_request", "phase": "judge"})
    elif condition == "count_mismatch":
        progress["completed_actions"] = 2
    elif condition == "stale_probe":
        proof["probes"][0]["started_utc"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    elif condition == "missing_vision":
        proof["probes"].pop()
    elif condition in ("budget_exhausted", "counter_reset"):
        (tmp_path / "connection-retries.jsonl").write_text((json.dumps({"kind": "taskviews_api_recovery"}) + "\n") * 3)
        state["experiment_connection_retries"] = 3 if condition == "budget_exhausted" else 0
    elif condition == "live_components":
        monkeypatch.setattr(pipeline, "require_recovery_cleanup", lambda *args: (_ for _ in ()).throw(RuntimeError("Still active")))
    supervisor.atomic(stage / "state.json", progress)
    supervisor.atomic(tmp_path / "state.json", state)
    supervisor.atomic(probe, proof)
    (trace / "events-1.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(RuntimeError):
        pipeline.queue_recovered_experiment(tmp_path, probe)
    assert supervisor.read_json(tmp_path / "state.json")["status"] == "experiment_needs_repair"
    assert not (tmp_path / "repairs.jsonl").exists()


def interrupted_resource_fixture(root, monkeypatch):
    stage = root / "baseline-r01"
    official = root / "official"
    trace = stage / "telemetry"
    trace.mkdir(parents=True)
    official.mkdir()
    supervisor.atomic(root / "plan.json", {"run_id": root.name, "max_steps": 500,
                      "model": "qwen3.8-max", "base_url": "https://example.invalid"})
    supervisor.atomic(root / "state.json", {"status": "baseline_needs_attention", "active_arm": "baseline",
                      "active_run": stage.name, "repair_round": 0, "runs": []})
    supervisor.atomic(stage / "state.json", {"status": "failed", "decisions": 2, "api_responses": 2,
                      "completed_actions": 2, "official_score": None, "cleanup_errors": [],
                      "cleanup_utc": supervisor.now(), "latest_resources": {"service_memory_events": {"oom": "0"}}})
    supervisor.atomic(stage / "manifest.json", {"run_id": stage.name, "arm": "baseline",
                      "official_results": str(official), "model": "qwen3.8-max", "base_url": "https://example.invalid"})
    supervisor.atomic(official / "source-audit.json", {"unchanged": True})
    supervisor.atomic(official / "resource-profile.json", {"container": "aabbcc0011223344"})
    guard = {"timestamp_utc": "2026-10-02T13:57:02+00:00", "available_ram_gib": 3.961,
             "c_free_gib": 146, "d_free_gib": 33}
    (stage / "console.log").write_text(f"Windows resource reserve reached: {guard!r}; stopping only OSWorld container aabbcc001122\n")
    (official / "resources.jsonl").write_text(json.dumps({"running": True, "windows_available_gib": 3.961,
                                                         "oom_killed": False}) + "\n")
    stable = {name: "unchanged" for name in ("scripts/run_official_qwen_task035.py",
               "scripts/osworld_task035_background.py", "ui_kobe/osworld/telemetry.py")}
    supervisor.atomic(stage / "project-source-before.json", stable)
    monkeypatch.setattr(pipeline, "snapshot_project", lambda: stable.copy())
    events = []
    for step in (1, 2):
        events.extend([{"event": "api_response", "step": step, "status_code": 200,
                        "response": {"model": "qwen3.8-max"}},
                       {"event": "decision", "step": step, "parsed_actions": ["pyautogui.click(1, 1)"]},
                       {"event": "controller_result", "step": step,
                        "time_utc": "2026-10-02T13:56:00+00:00" if step == 1 else "2026-10-02T14:01:58+00:00",
                        "result": {"status": "success", "returncode": 0} if step == 1 else None},
                       {"event": "action_result", "step": step}])
    (trace / "events-1.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    authorization = root / "authorization.json"
    supervisor.atomic(authorization, {"run_id": root.name, "scope": "unscored_resource_interrupted_baseline",
                      "user_request": "重启推理过程，继续完成两项实验", "authorized_at_utc": supervisor.now(),
                      "max_restarts": 3})
    probe = root / "probe.json"
    supervisor.atomic(probe, {})
    checks = []
    monkeypatch.setattr(pipeline, "require_recovery_probe", lambda *args: checks.append("probe"))
    monkeypatch.setattr(pipeline, "require_recovery_cleanup", lambda *args: checks.append("cleanup"))
    monkeypatch.setattr(pipeline, "render_comparison", lambda *args: None)
    return stage, official, trace, authorization, probe, events, checks


def test_authorized_resource_recovery_preserves_interrupted_evidence_and_repair_budget(tmp_path, monkeypatch):
    stage, official, trace, authorization, probe, events, checks = interrupted_resource_fixture(tmp_path, monkeypatch)
    evidence = (trace / "events-1.jsonl").read_bytes()
    pipeline.queue_authorized_resource_baseline(tmp_path, authorization, probe)
    state = supervisor.read_json(tmp_path / "state.json")
    ledger = json.loads((tmp_path / "authorized-resource-retries.jsonl").read_text())
    assert state["status"] == "prepared" and state["authorized_resource_retries"] == 1
    assert state["repair_round"] == 0 and checks == ["probe", "cleanup"]
    assert ledger["counts"]["decision"] == 2 and ledger["unconfirmed_after_guard"][0]["step"] == 2
    assert ledger["startup_available_ram_gib"] == 6 and ledger["runtime_reserve_gib"] == 4
    assert (trace / "events-1.jsonl").read_bytes() == evidence
    assert not (tmp_path / "repairs.jsonl").exists()
    with pytest.raises(RuntimeError):
        pipeline.queue_authorized_resource_baseline(tmp_path, authorization, probe)


@pytest.mark.parametrize("condition", ["authorization", "scored", "score_file", "500_steps", "cleanup",
    "source_changed", "wrong_model", "wrong_vm", "no_guard", "oom", "early_failure", "policy_fail",
    "judge", "api_failure", "count_mismatch", "runtime_changed", "exhausted", "duplicate",
    "probe_failed", "live_components"])
def test_authorized_resource_recovery_refuses_unrelated_failures_or_completed_episodes(tmp_path, monkeypatch, condition):
    stage, official, trace, authorization, probe, events, checks = interrupted_resource_fixture(tmp_path, monkeypatch)
    progress = supervisor.read_json(stage / "state.json")
    if condition == "authorization":
        supervisor.atomic(authorization, {"run_id": "another-run"})
    elif condition == "scored":
        progress["official_score"] = "0"
    elif condition == "score_file":
        (official / "result.txt").write_text("0")
    elif condition == "500_steps":
        progress["decisions"] = 500
    elif condition == "cleanup":
        progress["cleanup_errors"] = ["still running"]
    elif condition == "source_changed":
        supervisor.atomic(official / "source-audit.json", {"unchanged": False})
    elif condition == "wrong_model":
        events[0]["response"]["model"] = "other-model"
    elif condition == "wrong_vm":
        supervisor.atomic(official / "resource-profile.json", {"container": "ddeeff001122"})
    elif condition == "no_guard":
        (stage / "console.log").write_text("No stop evidence")
    elif condition == "oom":
        (official / "resources.jsonl").write_text(json.dumps({"oom_killed": True}) + "\n")
    elif condition == "early_failure":
        events[6]["time_utc"] = "2026-10-02T13:56:00+00:00"
    elif condition == "policy_fail":
        events[5]["parsed_actions"] = ["FAIL"]
    elif condition == "judge":
        events.append({"event": "evaluation_start"})
    elif condition == "api_failure":
        events.append({"event": "api_error"})
    elif condition == "count_mismatch":
        progress["api_responses"] = 3
    elif condition == "runtime_changed":
        monkeypatch.setattr(pipeline, "snapshot_project", lambda: {})
    elif condition in ("exhausted", "duplicate"):
        records = [{"previous_run": stage.name}] if condition == "duplicate" else [{"previous_run": str(i)} for i in range(3)]
        (tmp_path / "authorized-resource-retries.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    elif condition in ("probe_failed", "live_components"):
        target = "require_recovery_probe" if condition == "probe_failed" else "require_recovery_cleanup"
        monkeypatch.setattr(pipeline, target, lambda *args: (_ for _ in ()).throw(RuntimeError("Recovery rejected")))
    supervisor.atomic(stage / "state.json", progress)
    (trace / "events-1.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    ledger_path = tmp_path / "authorized-resource-retries.jsonl"
    before = ledger_path.read_bytes() if ledger_path.exists() else None
    with pytest.raises(RuntimeError):
        pipeline.queue_authorized_resource_baseline(tmp_path, authorization, probe)
    assert supervisor.read_json(tmp_path / "state.json")["status"] == "baseline_needs_attention"
    assert (ledger_path.read_bytes() if ledger_path.exists() else None) == before
