"""Create one bounded serial comparison service; this launcher never repeats runs."""
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.osworld_task035_pipeline import render_comparison, require_recovery_probe, snapshot_project  # noqa: E402 - repository path is initialized first
from scripts.osworld_task035_background import START_AVAILABLE_GIB, atomic, now  # noqa: E402 - repository path is initialized first
from scripts.osworld_task035_profiles import validate_comparison_config  # noqa: E402 - repository path is initialized first


def require_validation(path):
    validation = json.loads(path.read_text(encoding="utf-8"))
    if (validation.get("status") != "passed" or validation.get("exit_code") != 0
            or type(validation.get("tests_passed")) is not int or validation["tests_passed"] < 1
            or validation.get("project_source_sha256") != snapshot_project()):
        raise RuntimeError("Current project code must have recorded passing validation")
    return validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT / "configs/osworld_qwen38_task_control.json")
    parser.add_argument("--probe-file", type=Path, required=True)
    parser.add_argument("--validation-file", type=Path, required=True)
    args = parser.parse_args()
    validation = require_validation(args.validation_file)
    python = Path.home() / "osworld2/OSWorld-V2/.venv/bin/python"
    config = args.config.resolve()
    config_data = json.loads(config.read_text(encoding="utf-8"))
    profile = validate_comparison_config(config_data)
    run_id = profile["run_prefix"] + datetime.now().strftime("%Y%m%d-%H%M%S")
    unit = run_id + ".service"
    root = PROJECT / "docs/experiments" / run_id
    root.mkdir(parents=True, exist_ok=False)
    atomic(root / "taskviews-config.json", config_data)
    (root / "repairs.jsonl").touch()
    (root / "preparation-retries.jsonl").touch()
    (root / "connection-retries.jsonl").touch()
    atomic(root / "validation.json", validation)
    atomic(root / "api-preflight.json", json.loads(args.probe_file.read_text(encoding="utf-8")))
    atomic(root / "project-source-planned.json", snapshot_project())
    pipeline = PROJECT / "scripts/osworld_task035_pipeline.py"
    plan = {"run_id": run_id, "unit": unit, "created_utc": now(),
                                "model": config_data["api"]["model"], "base_url": config_data["api"]["base_url"],
                                "api_profile": profile,
                                "max_steps": 500, "maximum_repair_rounds": 10, "heartbeat_minutes": 60,
                                "offline_validation": f"{validation['tests_passed']} tests passed against the planned project source",
                                "api_preflight": str(root / "api-preflight.json"),
                                "taskviews_config_source": str(config),
                                "taskviews_framework": "persistent_task_control" if config_data["agent"].get("task_control", {}).get("enabled") else "legacy_two_call",
                                "task_memory_policy": "new directory per complete experiment attempt",
                                "report_path": str(PROJECT / "docs" / (run_id + "-comparison.md")),
                                "user_authorization": "User explicitly requested this model/API baseline followed by the current project Agent experiment; prior results are preserved",
                                "aggregate_hard_cap_bytes": int(5.75 * 1024**3),
                                "startup_available_ram_gib": START_AVAILABLE_GIB,
                                "config_sha256": hashlib.sha256((root / "taskviews-config.json").read_bytes()).hexdigest()}
    atomic(root / "plan.json", plan)
    require_recovery_probe(root, plan, root / "api-preflight.json")
    atomic(root / "state.json", {"status": "prepared", "repair_round": 0, "experiment_connection_retries": 0, "runs": []})
    command = shlex.join([str(python), str(pipeline), "run", "--run-dir", str(root)])
    shell_command = "source ~/osworld2/env.sh; exec " + command
    service_text = f"""[Unit]
Description=OSWorld Task035 {plan['model']} baseline then TaskViews; 5.75 GiB component caps

[Service]
Type=simple
WorkingDirectory={Path.home() / 'osworld2/OSWorld-V2'}
ExecStart=/bin/bash -ic {shlex.quote(shell_command)}
ExecStopPost={python} {pipeline} cleanup --run-dir {root}
MemoryMax=2G
MemoryHigh=1792M
MemorySwapMax=0
OOMPolicy=stop
KillMode=control-group
TimeoutStopSec=120
Restart=no
CPUQuota=100%
CPUWeight=50
IOWeight=50
Nice=10
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
"""
    directory = Path.home() / ".config/systemd/user"
    directory.mkdir(parents=True, exist_ok=True)
    service = directory / unit
    service.write_text(service_text)
    render_comparison(root)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "start", unit], check=True)
    print(json.dumps({"unit": unit, "run_dir": str(root), "service_file": str(service),
                      "report_path": plan["report_path"]}, indent=2))


if __name__ == "__main__":
    main()
