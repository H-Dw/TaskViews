from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from examples import osworld2_eval as example
from ui_kobe.osworld import runner
from ui_kobe.osworld.actions import compile_action
from ui_kobe.osworld.local_web import website_origins
from ui_kobe.osworld.task_examples import task_example


@pytest.fixture
def prepared_inputs(tmp_path):
    def build(case):
        spec = task_example(case)
        repo = tmp_path / "osworld"
        source = repo / "evaluation_examples/task_class" / f"task_{case}.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        # An import would fail: preparation must only inspect literal fields.
        source.write_text(f'raise RuntimeError("must not import evaluator")\nclass Task{case}:\n'
                          f'    id = "{case}"\n    instruction = "Original task {case} instruction"\n'
                          f'    related_apps = {list(spec.websites)!r}\n', encoding="utf-8")
        hashes = repo / "benchmark_releases/osworld-v2.1.task_hashes.json"
        hashes.parent.mkdir(parents=True, exist_ok=True)
        example.write_json(hashes, {"files": {source.name: {"sha256": example.sha256(source)}}})
        release = hashes.with_name("osworld-v2.1.json")
        example.write_json(release, {"release": "osworld-v2.1", "tasks": {"commit": "task-rev"},
                                    "assets": {"commit": "asset-rev"}, "website_code": {"commit": "web-rev"},
                                    "task_hash_manifest": {"path": str(hashes.relative_to(repo)),
                                                           "sha256": "sha256:" + example.sha256(hashes)}})
        assets = tmp_path / "assets"
        for name in spec.assets:
            path = assets / f"task_{case}" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"offline placeholder, not real benchmark data")
        config = tmp_path / "input-config.json"
        example.write_json(config, {"api": {"provider": "qwen", "model": "example-model", "api_key_env": "QWEN_API_KEY"},
                                    "agent": {"context_bytes": 32000, "task_control": {
                                        "constraints": ["old035-contract"], "delivery_files": ["old035.xlsx"],
                                        "key_semantics": ["old035-answer"], "memory_dir": "old-memory"}}})
        vm = tmp_path / "image.qcow2"
        vm.write_bytes(b"offline placeholder")
        interpreter = repo / ".venv/bin/python"
        interpreter.parent.mkdir(parents=True, exist_ok=True)
        interpreter.write_text("placeholder", encoding="utf-8")
        desktop = repo / "desktop_env/desktop_env.py"
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text("# placeholder", encoding="utf-8")
        return {"case_id": case, "osworld_root": repo, "assets_root": assets, "config": config,
                "vm_path": vm, "agent_python": Path(sys.executable), "output": tmp_path / f"bundle-{case}"}
    return build


@pytest.mark.parametrize("case", ["059", "046"])
def test_prepare_official_bundle_without_imports_or_fixture_answers(prepared_inputs, case):
    options = prepared_inputs(case)
    plan = example.prepare(**options)
    config = json.loads(Path(plan["config"]).read_text())
    control = config["agent"]["task_control"]
    assert control["enabled"] is True
    assert control["memory_dir"] == str(options["output"] / "evaluation/memory")
    assert control["task_id"].endswith(case)
    assert control["constraints"] == control["delivery_files"] == control["key_semantics"] == []
    assert "old035" not in json.dumps(config)
    assert "synthetic" not in json.dumps(config)
    assert "view_focus" not in config and "evaluation_notes" not in config
    assert plan["official"]["instruction"] == f"Original task {case} instruction"
    assert plan["commands"]["setup"][plan["commands"]["setup"].index("--task") + 1] == case
    assert "--setup-only" in plan["commands"]["setup"] and "--evaluate" not in plan["commands"]["setup"]
    assert "--evaluate" in plan["commands"]["evaluate"]
    assert example.check(plan)["files_ready"]
    assert example.check(plan)["ready_for_setup"] == (case == "059")
    with pytest.raises(FileExistsError, match="new trial"):
        example.prepare(**options)


def test_prepare_rejects_stale_official_source_before_creating_bundle(prepared_inputs):
    options = prepared_inputs("059")
    source = options["osworld_root"] / "evaluation_examples/task_class/task_059.py"
    source.write_text(source.read_text() + "\n# changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source differs"):
        example.prepare(**options)
    assert not options["output"].exists()


@pytest.mark.parametrize("changed", ["source", "config", "asset"])
def test_preflight_rejects_changes_and_missing_assets(prepared_inputs, changed):
    plan = example.prepare(**prepared_inputs("059"))
    if changed == "asset":
        Path(plan["required_assets"][0]).unlink()
    else:
        target = Path(plan["official"]["source"] if changed == "source" else plan["config"])
        target.write_text(target.read_text() + "\n", encoding="utf-8")
    check = example.check(plan)
    assert not check["ready_for_setup"]
    assert check["missing_files"] if changed == "asset" else check["identity_errors"]


def test_prepare_does_not_copy_inline_credentials(prepared_inputs):
    options = prepared_inputs("059")
    example.write_json(options["config"], {"api": {"api_key": "not-a-real-key"}})
    with pytest.raises(ValueError, match="api_key_env"):
        example.prepare(**options)
    assert not options["output"].exists()


def test_046_preflight_requires_all_three_sites(prepared_inputs, monkeypatch):
    plan = example.prepare(**prepared_inputs("046"))
    visited = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def visit(url, timeout):
        visited.append(url)
        if "vaultbank" in url:
            raise OSError("bank is offline")
        return Response()

    monkeypatch.setattr(example, "build_opener", lambda *args: SimpleNamespace(open=visit))
    report = example.check(plan, websites=True)
    assert len(visited) == 3
    assert set(report["website_checks"]) == {"teamchat", "vaultbank", "mailhub"}
    assert not report["ready_for_setup"]
    assert report["website_checks"]["teamchat"]["reachable"]
    assert not report["website_checks"]["vaultbank"]["reachable"]


def test_run_uses_official_bundle_environment_and_keeps_outputs_separate(prepared_inputs, monkeypatch):
    options = prepared_inputs("059")
    plan = example.prepare(**options)
    calls = []
    monkeypatch.setattr(example.sys, "platform", "linux")
    monkeypatch.setenv("OSWORLD_EVAL_MODEL_NAME", "old035-judge")
    monkeypatch.setenv("QWEN_API_KEY", "offline-test-key")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(example.subprocess, "run", run)
    assert example.run_prepared(options["output"], "setup") == 0
    assert calls[0][0] == plan["commands"]["setup"]
    env = calls[0][1]["env"]
    assert env["OSWORLD_FILE_BASE_URL"] == str(options["assets_root"])
    assert env["OSWORLD_LOCAL_WEB"] == "0"
    assert "OSWORLD_EVAL_MODEL_NAME" not in env
    assert env["QWEN_API_KEY"] == "offline-test-key"
    assert "--evaluate" not in calls[0][0]
    (options["output"] / "evaluation").mkdir()
    with pytest.raises(FileExistsError):
        example.run_prepared(options["output"], "evaluate")
    assert len(calls) == 1


@pytest.mark.parametrize("score,partial,full", [(0.2, 0.2, False), (1.0, 1.0, True),
                                              ({"score": 0.8, "safety": {"checks": []}}, 0.8, False)])
def test_official_reward_keeps_partial_and_full_success_distinct(tmp_path, score, partial, full):
    buffer = BytesIO()
    Image.new("RGB", (800, 600), "white").save(buffer, format="PNG")
    obs = {"screenshot": buffer.getvalue()}
    agent = SimpleNamespace(last_trace={}, predict=lambda *a, **k: (
        json.dumps({"reason": "offline test", "action": {"type": "done"}}), ["DONE"]))
    env = SimpleNamespace(reset=lambda task: obs, controller=SimpleNamespace(),
                          step=lambda *a, **k: (obs, 0, True, {}), evaluate=lambda: score)
    report = runner.run_episode(env, agent, "official instruction", tmp_path,
                                max_steps=2, max_seconds=5, evaluate=True)
    assert report["score"] == score
    assert report["partial_score"] == partial and report["full_success"] is full
    assert report["agent_done"] and report["evaluated"]


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), -1, 1.1, {}, {"score": "0.2"}])
def test_unscored_or_malformed_result_never_becomes_zero_or_success(value):
    with pytest.raises(ValueError, match="Official evaluator"):
        runner.official_score(value)


def test_local_site_names_cannot_add_arbitrary_hosts():
    assert website_origins(("teamchat", "vaultbank", "mailhub")) == (
        "http://teamchat.127.0.0.1.nip.io:21280", "http://vaultbank.127.0.0.1.nip.io:21280",
        "http://mailhub.127.0.0.1.nip.io:21280")
    for bad in [(), ("teamchat", "teamchat"), ("unknown",), ("teamchat;anything",)]:
        with pytest.raises(ValueError):
            website_origins(bad)


@pytest.mark.parametrize("case", ["059", "046"])
def test_runner_setup_loads_official_task_and_routes_046_sites(prepared_inputs, monkeypatch, case):
    from ui_kobe.osworld import local_web
    options = prepared_inputs(case)
    plan = example.prepare(**options)
    calls = []
    task = SimpleNamespace(instruction=f"OFFICIAL {case} INSTRUCTION")
    buffer = BytesIO()
    Image.new("RGB", (800, 600), "white").save(buffer, format="PNG")
    obs = {"screenshot": buffer.getvalue()}

    class Env:
        def __init__(self, **kwargs):
            self.controller = SimpleNamespace(execute_python_command=lambda code: {
                "status": "success", "returncode": 0, "output": "[320,240]"})

        def reset(self, config):
            assert config is task
            calls.append("reset")
            return obs

        def step(self, code, **kwargs):
            assert code == compile_action({"type": "move", "x": 320, "y": 240}, 800, 600)
            return obs, 0, False, {}

        def evaluate(self):
            pytest.fail("setup must not call the evaluator")

        def close(self):
            calls.append("close")

    def load(*args, **kwargs):
        assert kwargs["task_id"] == case and kwargs["eval_version"] == "v2"
        return task

    monkeypatch.setitem(sys.modules, "desktop_env.desktop_env", SimpleNamespace(DesktopEnv=Env))
    monkeypatch.setitem(sys.modules, "task_loader", SimpleNamespace(load_task_config=load))
    monkeypatch.setattr(runner, "source_snapshot", lambda repo: {})
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *args, **kwargs: "test-commit")
    monkeypatch.setattr(local_web, "configure_local_websites", lambda env, apps: calls.append(tuple(apps)))
    monkeypatch.setattr(local_web, "verify_local_websites", lambda env, apps: {"sites": list(apps)})
    monkeypatch.setenv("WEBSITE_HOST_SUFFIX", "127.0.0.1.nip.io:21280")
    monkeypatch.setenv("OSWORLD_LOCAL_WEB", "1")
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(Path.cwd())  # Restore runner.main's chdir after this test.
    monkeypatch.setattr(sys, "argv", ["runner", *plan["commands"]["setup"][3:]])
    runner.main()
    import os
    assert os.environ["OSWORLD_LOCAL_WEB"] == "0"
    report = json.loads((options["output"] / "setup/result.json").read_text())
    assert report["status"] == "task_setup_and_adapter_passed"
    assert not report["evaluated"] and report["partial_score"] is None
    assert calls == ([tuple(task_example(case).websites)] if case == "046" else []) + ["reset", "close"]


def test_guest_route_contains_all_task046_hosts_and_probes_each(monkeypatch):
    import requests
    from ui_kobe.osworld.local_web import configure_local_websites
    commands = []
    proxy = SimpleNamespace(reload=lambda: None, attrs={"NetworkSettings": {"Networks": {
        "osworld-local-web": {"IPAddress": "172.25.0.2"}}}})
    container = SimpleNamespace(reload=lambda: None, attrs={"NetworkSettings": {"Networks": {"osworld-local-web": {}}}},
                                exec_run=lambda args: SimpleNamespace(exit_code=0))
    client = SimpleNamespace(networks=SimpleNamespace(get=lambda name: SimpleNamespace()),
                             containers=SimpleNamespace(list=lambda **kwargs: [proxy]))

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, *, json, timeout):
            commands.append(json["command"][-1])
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "returncode": 0, "output": "GUEST_ROUTE_OK WEBSITE_HTTP_OK"})

    monkeypatch.setattr(requests, "Session", Session)
    env = SimpleNamespace(provider=SimpleNamespace(client=client, container=container),
                          client_password="fake-guest-password", server_port=5000)
    configure_local_websites(env, task_example("046").websites)
    assert len(commands) == 4
    for app in task_example("046").websites:
        assert f"{app}.127.0.0.1.nip.io" in commands[0]
        assert any(f"http://{app}.127.0.0.1.nip.io:21280" in command for command in commands[1:])
