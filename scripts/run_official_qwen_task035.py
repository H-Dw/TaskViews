"""Launch OSWorld 2.1's unmodified Qwen runner for this WSL/Docker profile.

The wrapper maps QWEN_API_KEY inside Python and attaches the existing local
TeamChat transport before Task035 setup. No OSWorld module is written to disk.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import runpy
import sys
import threading


def minimal_preflight(client, local_budget, kvm_path: Path = Path("/dev/kvm"), *, startup_available_gib=None):
    """Project-owned minimal profile checks; keep runtime and disk protection."""
    from scripts.osworld_task035_background import START_AVAILABLE_GIB

    threshold = START_AVAILABLE_GIB if startup_available_gib is None else startup_available_gib
    status = local_budget.host_status()
    if status["available_ram_gib"] < threshold:
        raise RuntimeError(f"Windows available RAM {status['available_ram_gib']:.2f} GiB; at least {threshold} GiB is required. Nothing was started.")
    if status["c_free_gib"] < 45 or status["d_free_gib"] < 12:
        raise RuntimeError("Disk reserve reached: keep C >= 45 GiB and D >= 12 GiB free.")
    if client.containers.list(filters={"label": f"{local_budget.LABEL}={local_budget.OWNER}"}):
        raise RuntimeError("An OSWorld local desktop is already running. This profile permits only one environment.")
    if not kvm_path.exists():
        raise RuntimeError("KVM is unavailable. This profile does not allow a slow software-emulation fallback.")
    return status


def install_local_memory_profile(output: Path, profile: str, *, startup_available_gib=None) -> None:
    """Override only this process's Docker profile; never write OSWorld source."""
    from desktop_env.providers.docker import local_budget, provider

    original_run = provider.run_limited
    output.mkdir(parents=True, exist_ok=True)
    guest_ram, guest_gib, container_gib = {
        "compact": ("2560M", 2.5, 4),
        "minimal": ("2048M", 2, 3),
    }[profile]
    container_bytes = container_gib * 1024**3
    if profile == "minimal":
        local_budget.preflight = lambda client: minimal_preflight(client, local_budget, startup_available_gib=startup_available_gib)

    class BudgetLogFilter(logging.Filter):
        def filter(self, record):
            if str(record.msg).startswith("Local budget applied:"):
                record.msg = f"Local budget applied: 2 vCPUs, {guest_gib} GiB guest RAM, {container_gib} GiB container limit; Windows free RAM %.2f GiB"
            return True

    local_budget.LOG.addFilter(BudgetLogFilter())

    def sample_resources(container) -> None:
        with (output / "resources.jsonl").open("a", encoding="utf-8") as log:
            while True:
                try:
                    container.reload()
                    state = container.attrs.get("State", {})
                    host = local_budget.host_status()
                    memory = container.stats(stream=False, one_shot=True).get("memory_stats", {}) if state.get("Running") else {}
                    record = {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "windows_available_gib": host["available_ram_gib"],
                        "container_memory_bytes": memory.get("usage"),
                        "container_limit_bytes": memory.get("limit"),
                        "running": state.get("Running"),
                        "oom_killed": state.get("OOMKilled"),
                    }
                    log.write(json.dumps(record) + "\n")
                    log.flush()
                    if not state.get("Running"):
                        return
                except Exception as exc:
                    log.write(json.dumps({"monitor_ended": type(exc).__name__}) + "\n")
                    log.flush()
                    return
                threading.Event().wait(5)

    class ContainersProxy:
        def __init__(self, manager):
            self.manager = manager

        def __getattr__(self, name):
            return getattr(self.manager, name)

        def run(self, image, **kwargs):
            environment = dict(kwargs["environment"])
            environment["RAM_SIZE"] = guest_ram
            kwargs.update(environment=environment, mem_limit=container_bytes, memswap_limit=container_bytes)
            if os.environ.get("OSWORLD_FULL_RUN_ID"):
                kwargs["labels"] = {**kwargs.get("labels", {}), "ui-kobe.osworld.run": os.environ["OSWORLD_FULL_RUN_ID"]}
            container = self.manager.run(image, **kwargs)
            container.reload()
            config = container.attrs["HostConfig"]
            effective = {
                "profile": profile,
                "guest_ram": environment["RAM_SIZE"],
                "vcpus": environment["CPU_CORES"],
                "container_limit_bytes": config["Memory"],
                "memory_and_swap_limit_bytes": config["MemorySwap"],
                "nano_cpus": config["NanoCpus"],
                "container": container.id,
                "image": image,
            }
            (output / "resource-profile.json").write_text(json.dumps(effective, indent=2), encoding="utf-8")
            logging.getLogger(__name__).info("Effective Docker profile: %s GiB guest RAM, %s GiB container limit, 2 vCPUs", guest_gib, container_gib)
            threading.Thread(target=sample_resources, args=(container,), daemon=True).start()
            return container

    class ClientProxy:
        def __init__(self, client):
            self.client = client
            self.containers = ContainersProxy(client.containers)

        def __getattr__(self, name):
            return getattr(self.client, name)

    def run_with_profile(client, image, **kwargs):
        container = original_run(ClientProxy(client), image, **kwargs)
        metadata_path = local_budget.ROOT / "logs/last-container.json"
        metadata = json.loads(metadata_path.read_text())
        metadata.update(guest_ram=guest_ram, memory_limit_bytes=container_bytes)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return container

    provider.run_limited = run_with_profile


def parse_local_arguments(argv):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--local-memory-profile", choices=["standard", "compact", "minimal"], default="standard")
    parser.add_argument("--detailed-log-dir", type=Path)
    parser.add_argument("--taskviews-config", type=Path)
    parser.add_argument("--native-kimi", action="store_true")
    parser.add_argument("--model-profile", choices=["qwen", "kimi-k3"], default="qwen")
    parser.add_argument("--agent-python", type=Path,
                        default=Path.home() / ".local/share/ui-kobe-glm/venv/bin/python")
    return parser.parse_known_args(argv)


def main() -> None:
    local_args, runner_args = parse_local_arguments(sys.argv[1:])
    sys.argv[1:] = runner_args
    key_env = "KIMI_API_KEY" if local_args.model_profile == "kimi-k3" else "QWEN_API_KEY"
    key = os.environ.get(key_env)
    if not key:
        raise SystemExit(f"{key_env} is missing from the WSL environment")
    os.environ["OPENAI_API_KEY"] = key
    repository = Path.home() / "osworld2/OSWorld-V2"
    project = Path(__file__).resolve().parents[1]
    runner = repository / "scripts/python/run_multienv_qwen.py"
    if not runner.is_file():
        raise SystemExit("OSWorld 2.1 Qwen runner was not found")
    sys.path[:0] = [str(project), str(repository), str(runner.parent)]
    os.chdir(repository)

    output = None
    source_before = None
    if "--result_dir" in runner_args:
        output = Path(runner_args[runner_args.index("--result_dir") + 1])
        output.mkdir(parents=True, exist_ok=True)
        from ui_kobe.osworld.runner import source_snapshot
        source_before = source_snapshot(repository)
        (output / "osworld-source-before.json").write_text(json.dumps(source_before, indent=2), encoding="utf-8")

    if "--smoke_only" not in sys.argv[1:]:
        if os.environ.get("WEBSITE_HOST_SUFFIX") != "127.0.0.1.nip.io:21280":
            raise SystemExit("This Task035 adapter requires the local TeamChat profile")
        if "--specific_task_id" not in sys.argv[1:]:
            raise SystemExit("Pass --specific_task_id 035")
        index = sys.argv.index("--specific_task_id")
        if len(sys.argv) <= index + 1 or sys.argv[index + 1] != "035":
            raise SystemExit("This adapter supports only Task035")

        # Task035 uses a model-based table judge, and the local profile has no
        # Anthropic credential. Keep the official evaluator code and record the
        # explicitly substituted Qwen judge in the experiment report.
        selected_model = runner_args[runner_args.index("--model") + 1] if "--model" in runner_args else "qwen3.6-35b-a3b"
        selected_url = runner_args[runner_args.index("--base_url") + 1] if "--base_url" in runner_args else "https://pjfdspqowq.a.pinggy.link"
        kimi = local_args.model_profile == "kimi-k3"
        if kimi and (selected_model != "kimi-k3" or selected_url != "https://api.moonshot.ai/v1"):
            raise SystemExit("K3 profile requires the exact official model and endpoint")
        os.environ.update({
            "OSWORLD_EVAL_MODEL_PROVIDER": "ui_kobe_qwen_judge",
            "OSWORLD_EVAL_MODEL_API_KEY_ENV": key_env,
            "OSWORLD_EVAL_MODEL_NAME": selected_model,
            "OSWORLD_EVAL_MODEL_BASE_URL": selected_url,
            "OSWORLD_EVAL_MODEL_TEMPERATURE": "1" if kimi else "0",
            "OSWORLD_EVAL_MODEL_MAX_OUTPUT_TOKENS": "16000" if kimi else "4096",
            "OSWORLD_EVAL_MODEL_RETRY_ATTEMPTS": "2",
            "OSWORLD_USER_SIM_PROVIDER": "openai_compatible",
            "OSWORLD_USER_SIM_API_KEY_ENV": key_env,
            "OSWORLD_USER_SIM_MODEL": selected_model,
            "OSWORLD_USER_SIM_BASE_URL": selected_url,
        })
        if kimi:
            os.environ.update(OSWORLD_USER_SIM_TEMPERATURE="1", OSWORLD_USER_SIM_MAX_TOKENS="16000")
        os.environ["OSWORLD_LOCAL_WEB"] = "0"
        from desktop_env.desktop_env import DesktopEnv
        from ui_kobe.osworld.local_web import configure_local_teamchat, verify_teamchat_browser
        from ui_kobe.osworld.qwen_judge import install_qwen_judge_backend

        install_qwen_judge_backend()

        if local_args.native_kimi:
            if not kimi or local_args.taskviews_config or not local_args.detailed_log_dir:
                raise SystemExit("Native K3 baseline requires K3 telemetry and no TaskViews override")
            os.environ['UI_KOBE_TELEMETRY_DIR'] = str(local_args.detailed_log_dir.resolve())
            import mm_agents.qwen
            from ui_kobe.osworld.kimi_native import KimiNativeAgent
            mm_agents.qwen.QwenAgent = KimiNativeAgent

        if local_args.taskviews_config:
            if not local_args.detailed_log_dir or not local_args.agent_python.is_file():
                raise SystemExit("TaskViews requires telemetry and the isolated Agent interpreter")
            os.environ.update(UI_KOBE_TASKVIEWS_CONFIG=str(local_args.taskviews_config.resolve()),
                              UI_KOBE_AGENT_PYTHON=str(local_args.agent_python.absolute()),
                              UI_KOBE_TELEMETRY_DIR=str(local_args.detailed_log_dir.resolve()))
            import mm_agents.qwen
            from ui_kobe.osworld.official_adapter import TaskViewsOfficialAgent
            mm_agents.qwen.QwenAgent = TaskViewsOfficialAgent

        if local_args.detailed_log_dir:
            from ui_kobe.osworld.telemetry import install
            install(local_args.detailed_log_dir)
        if kimi:
            from ui_kobe.api.kimi import install_official_k3_transport
            install_official_k3_transport()

        if local_args.local_memory_profile != "standard":
            if output is None:
                raise SystemExit("Local memory profile requires an explicit --result_dir")
            install_local_memory_profile(output, local_args.local_memory_profile)

        original_setup = DesktopEnv._setup_task

        def setup_with_local_teamchat(self, task_config, use_proxy):
            if self.provider_name != "docker" or str(self._task_get(task_config, "id", "")) != "035":
                raise RuntimeError("Local TeamChat adapter received an unsupported task")
            configure_local_teamchat(self)
            result = original_setup(self, task_config, use_proxy)
            if result[0]:
                verify_teamchat_browser(self)
            return result

        DesktopEnv._setup_task = setup_with_local_teamchat

    sys.argv[0] = str(runner)
    try:
        runpy.run_path(str(runner), run_name="__main__")
    finally:
        if source_before is not None:
            after = source_snapshot(repository)
            changed = sorted(name for name in set(source_before) | set(after) if source_before.get(name) != after.get(name))
            (output / "source-audit.json").write_text(json.dumps({"unchanged": not changed, "changed_paths": changed}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
