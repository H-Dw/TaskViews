"""Prepare/check GIMP and VLC baseline/Mini pairs. Launch is explicit opt-in.

Preparation uses existing local assets and offline evidence. It never calls a
model, starts a guest, performs GUI actions, or computes a benchmark score.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verified_invoice as pair  # noqa: E402

CONFIG = PROJECT / 'configs/verified-media-max-high40.json'
TASKS = ('gimp', 'vlc')
ARMS = ('baseline', 'taskviews')
SNAPSHOT = '49fefeb8b9d028f420b986790fa25d534409a3bf'
MINI_FILES = (
    'ui_kobe/osworld/mini_taskviews_native.py', 'ui_kobe/osworld/mini_taskviews_context.py',
    'ui_kobe/osworld/mini_interaction.py', 'ui_kobe/osworld/taskviews_profiles.py',
    'kobe_views/fixed_views.py', 'kobe_views/keyboard_view.py',
)


def configuration(path=CONFIG):
    value = pair.read(path)
    expected = {'version': 'verified-media-max-high40-v1', 'tasks': list(TASKS), 'provider': 'sx',
        'experiment': 'sx-pair-max-high40', 'sx_url_env': 'SX_URL_SB', 'coordinate_type': 'relative',
        'model': 'qwen3.8-max', 'generation_fields': {'enable_thinking': True, 'reasoning_effort': 'high'},
        'arms': list(ARMS), 'max_steps': 40, 'one_run_per_slot': True, 'mini_snapshot_commit': SNAPSHOT,
        'human_review_required': True, 'execution_authorized': False}
    if value != expected:
        raise ValueError('Media configuration differs from the review scope')
    return value


def mini_identity():
    import hashlib
    from scripts.osworld_native_experiment import require_mini_branch
    require_mini_branch()
    subprocess.run(['git', '-C', str(PROJECT), 'merge-base', '--is-ancestor', SNAPSHOT, 'HEAD'], check=True)
    result = {}
    for name in MINI_FILES:
        original = subprocess.check_output(['git', '-C', str(PROJECT), 'show', f'{SNAPSHOT}:{name}'])
        expected = hashlib.sha256(original).hexdigest()
        if pair.sha(PROJECT / name) != expected:
            raise ValueError('Mini implementation changed since its checkpoint: ' + name)
        result[name] = expected
    return result


def prepare(args):
    config = configuration(args.config)
    identity = mini_identity()
    if args.root.exists():
        raise FileExistsError('Use a new immutable media plan directory')
    # Validate both task/evidence/asset sets before publishing the matrix.
    for key in TASKS:
        task = pair.verify_task(args.benchmark_repo, key)
        spec = pair.specification('sx', 'SX_URL_SB', 'relative', config['experiment'], key)
        pair.validation_evidence(args.validation_dir/key, 'sx', spec['base_url'], spec['cua_contract'], spec)
        for item in pair.asset_files(task):
            if not (args.assets_root/key/'assets'/item['name']).is_file():
                raise FileNotFoundError('Missing task asset: ' + item['name'])
    args.root.mkdir(parents=True)
    for key in TASKS:
        pair.prepare(SimpleNamespace(root=args.root/key, task=key, provider='sx', sx_url_env='SX_URL_SB',
            coordinate_type='relative', experiment=config['experiment'], benchmark_repo=args.benchmark_repo,
            compiler_repo=args.compiler_repo, assets=args.assets_root/key/'assets', image=args.image,
            image_proof=args.image_proof, validation_dir=args.validation_dir/key))
    matrix = {'configuration': config, 'config_sha256': pair.sha(args.config),
        'project_source': pair.project_identity(), 'mini_source': identity,
        'project_commit': subprocess.check_output(['git','-C',str(PROJECT),'rev-parse','HEAD'],text=True).strip(),
        'plan_sha256': {key: pair.sha(args.root/key/'plan.json') for key in TASKS},
        'order': [{'task': key, 'arm': arm} for key in TASKS for arm in ARMS],
        'old_episodes_used_as_actor_memory': False}
    pair.write(args.root/'matrix.json', matrix)
    pair.write(args.root/'matrix.sha256.json', {'sha256': pair.sha(args.root/'matrix.json')})
    pair.write(args.root/'state.json', {'status': 'prepared_not_started', 'completed_tasks': [],
        'execution_authorized': False, 'model_calls': 0, 'vm_starts': 0, 'gui_actions': 0, 'evaluations': 0})
    manifest(args.root)


def manifest(root):
    config = configuration()
    matrix = pair.read(root/'matrix.json')
    if pair.sha(root/'matrix.json') != pair.read(root/'matrix.sha256.json')['sha256']:
        raise ValueError('Media matrix changed after preparation')
    if (matrix.get('configuration') != config or matrix.get('config_sha256') != pair.sha(CONFIG)
            or matrix.get('project_source') != pair.project_identity() or matrix.get('mini_source') != mini_identity()
            or matrix.get('order') != [{'task': key, 'arm': arm} for key in TASKS for arm in ARMS]
            or matrix.get('old_episodes_used_as_actor_memory') is not False):
        raise ValueError('Media matrix configuration, Mini checkpoint or source changed')
    common = None
    for key in TASKS:
        if pair.sha(root/key/'plan.json') != matrix['plan_sha256'][key]:
            raise ValueError('Task pair changed: ' + key)
        plan = pair.validate_plan(root/key)
        if any(plan.get(k) != config[k] for k in ('provider','experiment','model','generation_fields','arms','max_steps')):
            raise ValueError('Pair differs from the frozen comparison: ' + key)
        if plan['task_key'] != key:
            raise ValueError('Task pairs were exchanged')
        comparison = {k: plan[k] for k in ('cua_contract','arm_profiles','resource_policy','vm_memory_bytes',
            'service_memory_bytes','swap_bytes','base_url','api_key_env','image_identity')}
        if common is not None and comparison != common:
            raise ValueError('Task pairs do not share actor and resource budgets')
        common = comparison
    return matrix


def check(root):
    import json
    manifest(root)
    if (pair.read(root/'state.json')['status'] != 'prepared_not_started'
            or any(pair.read(root/key/'state.json')['status'] != 'prepared_not_started' for key in TASKS)):
        raise RuntimeError('Review check requires an unstarted matrix')
    reports = {}
    for key in TASKS:
        result = subprocess.run([sys.executable, str(PROJECT/'scripts/verified_invoice.py'), 'check',
                                 '--root', str(root/key)], check=False, capture_output=True, text=True)
        path = root/key/'preflight.json'
        if result.returncode not in (0, 1) or not path.is_file():
            raise RuntimeError('Task runtime check failed: ' + key + '\n' + result.stderr[-2000:])
        try:
            report = json.loads(result.stdout.splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise RuntimeError('Runtime check did not produce fresh evidence: ' + key) from exc
        if report != pair.read(path):
            raise ValueError('Runtime check output differs from saved evidence')
        if not report.get('image_verified'):
            raise ValueError('Official image is not ready: ' + key)
        reports[key] = report
    report = {'status': 'ready_for_user_review', 'ready_for_launch': all(
        not item['launch_prerequisites'] for item in reports.values()), 'tasks': reports,
        'formal_evaluation_started': False, 'execution_authorized': False,
        'model_calls_during_check': 0, 'vm_starts_during_check': 0, 'gui_actions_during_check': 0,
        'official_evaluations_during_check': 0}
    pair.write(root/'review.json', report)
    return report


def launch(root, approved):
    if not approved:
        raise PermissionError('User review is pending; no evaluation was started')
    import fcntl
    from scripts.osworld_native_experiment import require_scope
    require_scope(128*1024**2)
    with (root/'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest(root)
        if (pair.read(root/'state.json')['status'] != 'prepared_not_started'
                or any(pair.read(root/key/'state.json')['status'] != 'prepared_not_started' for key in TASKS)):
            raise RuntimeError('Matrix already attempted; no implicit retry or resume')
        for key in TASKS:
            pair.require_live_provider_check(root/key, pair.validate_plan(root/key))
        for index, key in enumerate(TASKS):
            pair.write(root/'state.json', {'status':'running', 'active_task':key,
                'completed_tasks':list(TASKS[:index]), 'execution_authorized':True})
            result = subprocess.run([sys.executable, str(PROJECT/'scripts/verified_invoice.py'), 'launch',
                '--root', str(root/key), '--execute-approved-plan'], check=False)
            if result.returncode or pair.read(root/key/'state.json')['status'] != 'completed':
                pair.write(root/'state.json', {'status':'stopped_on_error', 'task':key,
                    'completed_tasks':list(TASKS[:index]), 'returncode':result.returncode})
                return 1
        pair.write(root/'state.json', {'status':'completed', 'completed_tasks':list(TASKS)})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'check', 'launch'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--validation-dir', type=Path)
    parser.add_argument('--assets-root', type=Path)
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home()/'osworld-verified/OSWorld')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home()/'osworld2/OSWorld-V2')
    parser.add_argument('--image', type=Path, default=Path.home()/'osworld-verified/images/Ubuntu.qcow2')
    parser.add_argument('--image-proof', type=Path, default=PROJECT.parent/'osworld_verified_setup/image-proof.json')
    parser.add_argument('--execute-approved-plan', action='store_true')
    args = parser.parse_args()
    args.root = args.root.resolve()
    if args.command == 'prepare':
        if args.validation_dir is None or args.assets_root is None:
            parser.error('prepare requires --validation-dir and --assets-root')
        prepare(args)
        print('Prepared four slots; model calls=0, VM starts=0, evaluations=0')
        return 0
    if args.command == 'check':
        import json
        print(json.dumps(check(args.root), ensure_ascii=False))
        return 0
    return launch(args.root, args.execute_approved_plan)


if __name__ == '__main__':
    raise SystemExit(main())
