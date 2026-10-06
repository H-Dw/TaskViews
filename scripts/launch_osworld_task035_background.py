"""Install/start one bounded user service from WSL; never auto-restart a task."""
from datetime import datetime
from pathlib import Path
import json
import shlex
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = Path.home() / "osworld2/OSWorld-V2/.venv/bin/python"
run_id = "osworld21-qwen-task035-full-" + datetime.now().strftime("%Y%m%d-%H%M%S")
unit = run_id + ".service"
run_dir = PROJECT / "docs/experiments" / run_id
supervisor = PROJECT / "scripts/osworld_task035_background.py"
command = shlex.join([str(PYTHON), str(supervisor), "run", "--run-dir", str(run_dir), "--unit", unit])
shell_command = "source ~/osworld2/env.sh && exec " + command
service_text = f"""[Unit]
Description=OSWorld v2.1 Task035 Qwen full evaluation under 5.75 GiB component caps
After=docker.service

[Service]
Type=simple
WorkingDirectory={Path.home() / 'osworld2/OSWorld-V2'}
ExecStart=/bin/bash -ic {shlex.quote(shell_command)}
ExecStopPost={PYTHON} {supervisor} cleanup --run-dir {run_dir}
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
"""
directory = Path.home() / ".config/systemd/user"
directory.mkdir(parents=True, exist_ok=True)
service = directory / unit
service.write_text(service_text, encoding="utf-8")
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
subprocess.run(["systemctl", "--user", "start", unit], check=True)
print(json.dumps({"unit": unit, "run_dir": str(run_dir), "service_file": str(service)}, indent=2))
