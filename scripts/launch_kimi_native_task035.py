"""New, explicitly authorized native-tool baseline; preserve all former trials."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.prepare_kimi_native_task035 import code_hashes, OFFICIAL, write  # noqa: E402 - repository path is initialized first
from scripts import osworld_task035_background as supervisor  # noqa: E402 - repository path is initialized first
from ui_kobe.osworld.runner import source_snapshot  # noqa: E402 - repository path is initialized first


def load(path):
    return json.loads(path.read_text())


def require_preparation(prep):
    validation, replay, native = [load(prep / name) for name in
                                  ('validation.json', 'replay.json', 'native-probe.json')]
    current = code_hashes()
    if validation['exit_code'] or validation['code_hashes'] != current:
        raise RuntimeError('Passing tests for the current interface are required')
    if not replay.get('passed') or len(replay['cases']) != 3 or not native.get('passed'):
        raise RuntimeError('Three real-context replays and a native-tool probe must pass')
    if any(replay['code_hashes'].get(p) != current[p] or native['code_hashes'].get(p) != current[p]
           for p in ('ui_kobe/api/kimi_stream.py', 'ui_kobe/osworld/kimi_native.py')):
        raise RuntimeError('Validated Agent transport/interface changed after real replay')
    if time.time() - (prep / 'native-probe.json').stat().st_mtime > 7200:
        raise RuntimeError('Real API validation is older than two hours')
    if source_snapshot(OFFICIAL) != load(prep / 'osworld-source-before.json'):
        raise RuntimeError('OSWorld source changed since preparation')
    if len(Path('/proc/swaps').read_text().splitlines()) > 1:
        raise RuntimeError('Host swap must be disabled before this experiment')
    status = supervisor.host_status()
    if status['available_ram_gib'] < 6 or status['c_free_gib'] < 45 or status['d_free_gib'] < 12:
        raise RuntimeError('Original 6 GiB / disk startup protection is not met')
    if not Path('/dev/kvm').exists():
        raise RuntimeError('KVM is required')
    active = subprocess.check_output(['systemctl', '--user', 'list-units', '--type=service',
                                     '--state=active', '--no-legend', '--no-pager'], text=True)
    if any(line.strip().startswith('osworld21-') for line in active.splitlines()):
        raise RuntimeError('Another OSWorld evaluation service is active')
    return status


def launch(prep):
    lock = Path.home() / '.cache/ui-kobe-native-task035-launch.lock'
    lock.parent.mkdir(exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = require_preparation(prep)
        run_id = 'osworld21-kimi-k3-native-tools-task035-' + datetime.now().strftime('%Y%m%d-%H%M%S')
        root = PROJECT / 'docs/experiments' / run_id
        root.mkdir(parents=True, exist_ok=False)
        unit = run_id + '.service'
        plan = {'name': 'K3 原生工具协议 baseline', 'run_id': run_id, 'unit': unit,
            'created_utc': datetime.now(timezone.utc).isoformat(), 'arm': 'baseline',
            'agent_protocol': 'kimi-k3-native-tools-stream-v1', 'model': 'kimi-k3',
            'base_url': 'https://api.moonshot.ai/v1', 'max_steps': 500, 'heartbeat_minutes': 60,
            'report_path': str(PROJECT / 'docs' / (run_id + '-report.md')),
            'preparation': str(prep), 'project_hashes': code_hashes(), 'startup_windows': status,
            'aggregate_hard_cap_bytes': int(5.75 * 1024**3), 'startup_available_ram_gib': 6,
            'scope': 'Agent interface only; same official compiler/controller/task/rubric and existing K3 judge transport',
            'user_authorization': 'User explicitly requested a new native tools baseline with full streaming and real-task-size replay; preserve former XML results',
            'automatic_taskviews': False, 'automatic_retries': False}
        write(root / 'plan.json', plan)
        write(root / 'osworld-source-planned.json', load(prep / 'osworld-source-before.json'))
        command = shlex.join([str(supervisor.PYTHON), str(Path(__file__).resolve()), 'run', '--run-dir', str(root)])
        text = f'''[Unit]
Description=K3 native tools Task035 baseline, 5.75 GiB component limits

[Service]
Type=simple
WorkingDirectory={OFFICIAL}
ExecStart=/bin/bash -ic {shlex.quote('source ~/osworld2/env.sh; exec ' + command)}
ExecStopPost={supervisor.PYTHON} {PROJECT / 'scripts/osworld_task035_background.py'} cleanup --run-dir {root}
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
'''
        service = Path.home() / '.config/systemd/user' / unit
        service.parent.mkdir(parents=True, exist_ok=True)
        service.write_text(text)
        (root / 'service.unit').write_text(text)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'start', unit], check=True)
        result = {'run_dir': str(root), 'unit': unit, 'report': plan['report_path']}
        write(prep / 'launch.json', result)
        print(json.dumps(result))


def run(root):
    plan = load(root / 'plan.json')
    if code_hashes() != plan['project_hashes'] or source_snapshot(OFFICIAL) != load(root / 'osworld-source-planned.json'):
        raise RuntimeError('Frozen code changed before startup')
    if len(Path('/proc/swaps').read_text().splitlines()) > 1:
        raise RuntimeError('Host swap was re-enabled')
    supervisor.run(root, plan['unit'], options=plan)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['launch', 'run'])
    parser.add_argument('--preparation', type=Path)
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if args.action == 'launch':
        launch(args.preparation.resolve())
    else:
        run(args.run_dir.resolve())
