"""Frozen medium/low baseline/Mini serial evaluation; no retries or resume."""
from __future__ import annotations

import argparse
import fcntl
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.verified_invoice import read, write, sha, project_identity, validate_plan  # noqa: E402

ORDER = ('medium', 'low')
ARMS = ('baseline', 'taskviews')


def manifest(root):
    config = read(root/'matrix.json')
    if sha(root/'matrix.json') != read(root/'matrix.sha256.json')['sha256']:
        raise ValueError('Reasoning matrix changed after preparation')
    if (config.get('version') != 'verified-invoice-max-medium-low40-v1'
            or config.get('order') != list(ORDER) or config.get('arms') != list(ARMS)
            or config.get('max_steps') != 40 or config.get('project_source') != project_identity()):
        raise ValueError('Unexpected reasoning matrix or changed source')
    baseline = None
    for effort in ORDER:
        pair = root/effort
        if sha(pair/'plan.json') != config['plan_sha256'][effort]:
            raise ValueError('A reasoning pair changed')
        plan = validate_plan(pair)
        if (plan['experiment'] != 'sx-max-'+effort+'40' or plan['arms'] != list(ARMS)
                or plan['model'] != 'qwen3.8-max' or plan['max_steps'] != 40
                or plan['generation_fields'] != {'enable_thinking': True, 'reasoning_effort': effort}):
            raise ValueError('A pair differs from the authorized model, reasoning or order')
        comparison = {k: plan[k] for k in ('cua_contract','arm_profiles','resource_policy','vm_memory_bytes',
            'service_memory_bytes','swap_bytes','base_url','api_key_env','sources','asset_identity','task_sha256')}
        if baseline is not None and comparison != baseline:
            raise ValueError('Reasoning pairs do not share the same task, actors and budgets')
        baseline = comparison
    return config


def launch(root, approved):
    if not approved:
        raise PermissionError('An explicit user instruction and execution flag are required')
    from scripts.osworld_native_experiment import require_scope
    require_scope(128*1024**2)
    with (root/'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest(root)
        state = read(root/'state.json')
        if state['status'] != 'prepared_not_started' or any(
                read(root/effort/'state.json')['status'] != 'prepared_not_started' for effort in ORDER):
            raise RuntimeError('Matrix already attempted; no implicit retry or resume')
        for index, effort in enumerate(ORDER):
            write(root/'state.json', {'status':'running','active_effort':effort,
                'completed_efforts':list(ORDER[:index]),'execution_authorized':True})
            result = subprocess.run([sys.executable, str(PROJECT/'scripts/verified_invoice.py'), 'launch',
                '--root', str(root/effort), '--execute-approved-plan'], check=False)
            pair = read(root/effort/'state.json')
            if result.returncode or pair['status'] != 'completed':
                write(root/'state.json', {'status':'stopped_on_error','effort':effort,
                    'returncode':result.returncode,'completed_efforts':list(ORDER[:index])})
                return 1
        write(root/'state.json', {'status':'completed','completed_efforts':list(ORDER)})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--execute-approved-plan', action='store_true')
    args = parser.parse_args()
    return launch(args.root.resolve(), args.execute_approved_plan)


if __name__ == '__main__':
    raise SystemExit(main())
