"""Serial OSWorld-1 Mini graph/high-low campaign with bounded repair bookkeeping.

Only launch/start and qualify --live send requests or run a guest. inspect is a
single bounded read, never a daemon. A thread heartbeat performs code diagnosis;
this program records its allowance and makes comparison cohorts reproducible.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verified_invoice as pair  # noqa: E402
from ui_kobe.osworld.verified_serial import serial_lock, inherited_fds, process_identity  # noqa: E402

VERSION = 'verified-mini-graph-high-low40-v1'
TASK_ORDER = ('invoice', 'gimp', 'vlc')
MODES = ('legacy', 'flat', 'linked')
EFFORTS = ('high', 'low')
REPAIR_LIMIT = 10
INSPECTION_MINUTES = 40
ORDER = (
    ('invoice', 'legacy', 'high'), ('invoice', 'legacy', 'low'),
    ('invoice', 'flat', 'low'), ('invoice', 'flat', 'high'),
    ('invoice', 'linked', 'high'), ('invoice', 'linked', 'low'),
    ('gimp', 'flat', 'high'), ('gimp', 'flat', 'low'),
    ('gimp', 'linked', 'low'), ('gimp', 'linked', 'high'),
    ('gimp', 'legacy', 'low'), ('gimp', 'legacy', 'high'),
    ('vlc', 'linked', 'high'), ('vlc', 'linked', 'low'),
    ('vlc', 'legacy', 'low'), ('vlc', 'legacy', 'high'),
    ('vlc', 'flat', 'high'), ('vlc', 'flat', 'low'),
)
WRAPPER = PROJECT.parent / 'osworld_verified_setup/media-review-runtime-20261016.py'


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return pair.read(Path(path))


def write(path, value):
    pair.write(Path(path), value)


def optional(path, default=None):
    path = Path(path)
    return read(path) if path.is_file() else default


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def slots():
    return [dict(id=f'{i:02d}-{task}-{mode}-{effort}', task=task, mode=mode, reasoning=effort)
            for i, (task, mode, effort) in enumerate(ORDER, 1)]


def behavior_identity(source=None):
    source = pair.project_identity() if source is None else source
    # Monitoring/reporting/queue changes are separate from the actor/GUI method.
    return {name: value for name, value in source.items()
            if name.startswith(('ui_kobe/', 'kobe_views/'))
            and name != 'ui_kobe/osworld/verified_serial.py'} | {
                name: source[name] for name in ('scripts/verified_invoice.py',)
                if name in source}


def affected_tasks(before, after):
    changed = set(before) | set(after)
    changed = {name for name in changed if before.get(name) != after.get(name)}
    affected = set()
    support = {'scripts/verified_mini_graph_matrix.py', 'ui_kobe/osworld/verified_serial.py'}
    for name in changed - support:
        scoped = next((task for task in TASK_ORDER
                       if name.startswith(f'ui_kobe/osworld/task_specific/{task}/')), None)
        if scoped:
            affected.add(scoped)
        elif name.startswith(('ui_kobe/', 'kobe_views/')) or name in (
                'scripts/verified_invoice.py', 'scripts/run_official_native_tasks.py'):
            affected.update(TASK_ORDER)
        elif not name.startswith(('scripts/inspect_', 'scripts/analyze_')):
            # Unknown runtime changes are conservatively shared, never guessed local.
            affected.update(TASK_ORDER)
    return [task for task in TASK_ORDER if task in affected]


def affected_cohorts(root, source):
    # Compare against accepted plans, not just the previous failed patch. A
    # failed candidate may still be present when the next repair begins.
    affected = set()
    for entry in queue(root)['entries']:
        task = entry['slot']['task']
        before = read(root_path(root, entry['plan']) / 'plan.json')['project_source']
        if task in affected_tasks(before, source):
            affected.add(task)
    return [task for task in TASK_ORDER if task in affected]


@contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def sealed(path, value):
    path = Path(path)
    if path.exists():
        raise FileExistsError(str(path))
    write(path, value)
    write(path.with_suffix('.sha256.json'), {'sha256': pair.sha(path)})


def unseal(path):
    path = Path(path)
    if pair.sha(path) != read(path.with_suffix('.sha256.json'))['sha256']:
        raise ValueError('Frozen manifest changed: ' + str(path))
    return read(path)


def root_path(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Campaign path escapes its root')
    return path


def manifest(root):
    value = unseal(root / 'matrix.json')
    if (value.get('version') != VERSION or value.get('slots') != slots()
            or value.get('repair_limit') != REPAIR_LIMIT
            or value.get('inspection_minutes') != INSPECTION_MINUTES
            or value.get('provider') != 'sx' or value.get('model') != 'qwen3.8-max'
            or value.get('reasoning') != list(EFFORTS) or value.get('arms') != ['taskviews']
            or value.get('max_steps') != 40 or value.get('keyboard_research') is not False):
        raise ValueError('Campaign differs from its authorized eighteen-cell protocol')
    ledger(root)
    return value


def ledger(root):
    value = read(root / 'repair-ledger.json')
    entries = value.get('attempts', [])
    if (value.get('limit') != REPAIR_LIMIT or value.get('used') != len(entries)
            or not 0 <= value['used'] <= REPAIR_LIMIT
            or [e.get('number') for e in entries] != list(range(1, len(entries) + 1))
            or any(e.get('status') not in ('editing', 'passed', 'failed', 'rolled_back') for e in entries)
            or sum(e.get('status') == 'editing' for e in entries) > 1
            or any(e.get('status') == 'editing' for e in entries[:-1])):
        raise ValueError('Repair ledger is inconsistent; do not reset or infer an allowance')
    return value


def queue(root):
    value = unseal(root / read(root / 'state.json')['queue'])
    if [entry['slot'] for entry in value['entries']] != slots():
        raise ValueError('Queue omits, reorders or adds formal cells')
    for entry in value['entries']:
        path = root_path(root, entry['plan'])
        if pair.sha(path / 'plan.json') != entry['plan_sha256']:
            raise ValueError('A queued plan changed')
    return value


def check_cell_plan(plan, slot):
    if (plan['task_key'] != slot['task'] or plan['mini_graph_mode'] != slot['mode']
            or plan['generation_fields'] != {'enable_thinking': True, 'reasoning_effort': slot['reasoning']}
            or plan['experiment'] != f"sx-mini-max-{slot['reasoning']}40"
            or plan['model'] != 'qwen3.8-max' or plan['provider'] != 'sx'
            or plan['base_url_env'] != 'SX_URL_SB' or plan['coordinate_type'] != 'relative'
            or plan['arms'] != ['taskviews'] or plan['max_steps'] != 40
            or plan['arm_profiles']['taskviews']['max_bytes'] != 3000
            or plan.get('mini_keyboard_research') is not None):
        raise ValueError('A cell is outside the frozen Mini-only high/low protocol')
    expected_context = {'history_n': 20, 'image_max': 1, 'fold_size': 1,
        'model_screen_width': 1920, 'model_screen_height': 1080,
        'context_max_payload_chars': 12_000_000, 'context_max_text_chars': 32000,
        'context_rough_text_token_budget': 12000, 'context_reserve_chars': 10000,
        'tool_repair_retries': 2, 'advisory_repair_retries': 2}
    expected_generation = {'max_completion_tokens': 16000, 'step_output_tokens': 32000,
                           'executor_reserve_tokens': 16000, 'semantic_regenerations': 2}
    if (any(plan['cua_contract'].get(k) != v for k, v in expected_context.items())
            or any(plan['generation_profile'].get(k) != v for k, v in expected_generation.items())
            or plan['vm_memory_bytes'] != 3 * 1024**3 or plan['service_memory_bytes'] != 2 * 1024**3
            or plan['swap_bytes'] != 0):
        raise ValueError('A repair cannot change the frozen observation, output or resource budgets')


def asset_dir(config, task):
    return Path(config['assets_root']) / ('assets' if task == 'invoice'
                                         else f'media-assets-20261016/{task}/assets')


def evidence_dir(base, slot):
    return Path(base) / slot['task'] / slot['reasoning'] / slot['mode']


def archive_source(directory):
    source = pair.project_identity()
    sealed(directory / 'source.json', source)
    with zipfile.ZipFile(directory / 'source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(source):
            archive.write(PROJECT / name, name)
    sealed(directory / 'source-archive.json', {
        'sha256': pair.sha(directory / 'source.zip'), 'behavior_sha256': digest(behavior_identity(source)),
        'project_commit': subprocess.check_output(['git', '-C', str(PROJECT), 'rev-parse', 'HEAD'],
                                                  text=True).strip(),
        'working_tree_is_identified_by_file_hashes': True})
    return source


def prepare_cell(root, revision_dir, slot, config, validation):
    target = revision_dir / 'cells' / slot['id']
    args = SimpleNamespace(root=target, task=slot['task'], provider='sx', sx_url_env='SX_URL_SB',
        coordinate_type='relative', experiment=f"sx-mini-max-{slot['reasoning']}40",
        mini_graph_mode=slot['mode'], keyboard_mode='task_names', keyboard_toolset=[],
        keyboard_research=False, benchmark_repo=Path(config['benchmark_repo']),
        compiler_repo=Path(config['compiler_repo']), assets=asset_dir(config, slot['task']),
        image=Path(config['image']), image_proof=Path(config['image_proof']),
        validation_dir=evidence_dir(validation, slot))
    pair.prepare(args)
    plan = pair.validate_plan(target)
    check_cell_plan(plan, slot)
    return {'slot': slot, 'plan': str(target.relative_to(root)), 'plan_sha256': pair.sha(target / 'plan.json'),
            'revision': revision_dir.name, 'behavior_sha256': digest(behavior_identity(plan['project_source']))}


def prepare(args):
    root = args.root.resolve()
    if root.exists():
        raise FileExistsError('Use a new campaign root; never overwrite an attempted campaign')
    config = {'version': VERSION, 'created_utc': now(), 'campaign_id': str(uuid.uuid4()),
        'provider': 'sx', 'model': 'qwen3.8-max', 'reasoning': list(EFFORTS), 'arms': ['taskviews'],
        'max_steps': 40, 'slots': slots(), 'repair_limit': REPAIR_LIMIT,
        'inspection_minutes': INSPECTION_MINUTES, 'keyboard_research': False,
        'benchmark_repo': str(args.benchmark_repo.resolve()), 'compiler_repo': str(args.compiler_repo.resolve()),
        'assets_root': str(args.assets_root.resolve()), 'image': str(args.image.resolve()),
        'image_proof': str(args.image_proof.resolve()), 'runtime_wrapper': str(WRAPPER),
        'runtime_wrapper_sha256': pair.sha(WRAPPER),
        'authorization': 'Explicit human instruction: Implement the proposed plan; repairs <=10; affected-task cohorts rerun',
        'watchdog': {'source': 'frozen transport step deadline plus 120-second diagnostic grace',
                     'no_progress_alone_is_not_failure': True}}
    root.mkdir(parents=True)
    write(root / 'repair-ledger.json', {'limit': REPAIR_LIMIT, 'used': 0, 'attempts': []})
    sealed(root / 'matrix.json', config)
    revision = root / 'revisions/r000'
    revision.mkdir(parents=True)
    archive_source(revision)
    entries = [prepare_cell(root, revision, slot, config, args.validation_dir) for slot in slots()]
    sealed(revision / 'queue.json', {'entries': entries, 'created_utc': now(), 'repair_number': None})
    write(root / 'state.json', {'status': 'prepared_not_started', 'queue': 'revisions/r000/queue.json',
                               'active_slot': None, 'updated_utc': now()})
    report(root)
    return {'status': 'prepared_not_started', 'cells': len(entries), 'root': str(root)}


def bounded_command(command, log, *, memory='2G'):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = ['systemd-run', '--user', '--scope', '--quiet', f'--property=MemoryMax={memory}',
            '--property=MemorySwapMax=0', sys.executable, *map(str, command)]
    with log.open('x', encoding='utf-8') as stream:
        result = subprocess.run(argv, cwd=PROJECT, stdout=stream, stderr=subprocess.STDOUT,
                                check=False, pass_fds=inherited_fds())
    if result.returncode:
        raise RuntimeError(f'Bounded subprocess exited {result.returncode}; evidence: {log}')


def qualify(args):
    output = args.validation_dir.resolve()
    if args.live:
        return qualify_live(args.root.resolve(), output)
    if output.exists():
        raise FileExistsError('Use a fresh validation directory; failed evidence is retained')
    output.mkdir(parents=True)
    source = pair.project_identity()
    counts = {'runner_cases': 0, 'metric_cases': 0}
    with serial_lock():
        for task in TASK_ORDER:
            if task != 'invoice':
                metric = output / 'metrics' / task
                bounded_command([PROJECT / 'scripts/validate_verified_media_metrics.py', '--task', task,
                    '--output', metric, '--benchmark-repo', args.benchmark_repo,
                    '--compiler-repo', args.compiler_repo], output / f'metric-{task}.log', memory='128M')
                counts['metric_cases'] += 4
            for effort in EFFORTS:
                for mode in MODES:
                    folder = output / task / effort / mode
                    for case in ('limit', 'terminate', 'empty'):
                        bounded_command([PROJECT / 'scripts/validate_verified_invoice.py', '--provider', 'sx',
                            '--sx-url-env', 'SX_URL_SB', '--coordinate-type', 'relative', '--experiment',
                            f'sx-mini-max-{effort}40', '--task', task, '--mini-graph-mode', mode,
                            '--arm', 'taskviews', '--case', case, '--output', folder / f'taskviews-{case}',
                            '--benchmark-repo', args.benchmark_repo, '--compiler-repo', args.compiler_repo],
                            output / 'logs' / f'{task}-{effort}-{mode}-{case}.log')
                        counts['runner_cases'] += 1
                        print(json.dumps({'qualified': counts['runner_cases'], 'of': 54,
                                          'task': task, 'reasoning': effort, 'mode': mode, 'case': case}), flush=True)
                    if task != 'invoice':
                        (folder / 'metrics').mkdir(parents=True)
                        shutil.copyfile(output / 'metrics' / task / 'validation.json',
                                        folder / 'metrics/validation.json')
        if source != pair.project_identity():
            raise RuntimeError('Runtime code changed during offline qualification')
        value = {'passed': True, **counts, 'project_source': source,
                 'live_api_called': False, 'vm_started': False, 'benchmark_score': None, 'time_utc': now()}
        sealed(output / 'qualification.json', value)
    return {k: v for k, v in value.items() if k != 'project_source'}


def qualify_live(root, output):
    manifest(root)
    entries = queue(root)['entries']
    if output.exists():
        raise FileExistsError('Keep every live qualification attempt')
    output.mkdir(parents=True)
    evidence = {'provider': {}, 'grounding': {}, 'time_utc': now(), 'extra_benchmark_decisions': 0}
    pending = [e for e in entries if not valid_outcome(root_path(root, e['plan']))]
    if not pending:
        raise RuntimeError('No pending formal cells require fresh live probes')
    with serial_lock():
        for effort in EFFORTS:
            effort_entries = [e for e in pending if e['slot']['reasoning'] == effort]
            if not effort_entries:
                continue
            representative = effort_entries[0]
            plan_root = root_path(root, representative['plan'])
            bounded_command([PROJECT / 'scripts/probe_native_provider.py', '--provider', 'sx',
                '--root', plan_root, '--output', output / f'provider-{effort}'],
                output / f'provider-{effort}.log', memory='128M')
            proof = read(output / f'provider-{effort}/report.json')
            if not proof.get('complete'):
                raise RuntimeError('Provider probe did not complete; do not start a guest')
            evidence['provider'][effort] = str(output / f'provider-{effort}/report.json')
            for mode in MODES:
                candidates = [e for e in effort_entries if e['slot']['mode'] == mode]
                if not candidates:
                    continue
                representative = candidates[0]
                plan_root = root_path(root, representative['plan'])
                bounded_command([PROJECT / 'scripts/probe_mini_grounding.py', '--live', '--provider', 'sx',
                    '--root', plan_root, '--output', output / f'grounding-{effort}-{mode}',
                    '--compiler-repo', read(plan_root / 'plan.json')['sources']['actor_compiler']['repo']],
                    output / f'grounding-{effort}-{mode}.log', memory='128M')
                grounding = read(output / f'grounding-{effort}-{mode}/report.json')
                evidence['grounding'][f'{effort}/{mode}'] = str(output / f'grounding-{effort}-{mode}/report.json')
                for entry in entries:
                    slot = entry['slot']
                    if slot['reasoning'] != effort or slot['mode'] != mode:
                        continue
                    destination = root_path(root, entry['plan'])
                    if optional(destination / 'state.json', {}).get('status') != 'prepared_not_started':
                        continue  # Old completed proofs are immutable.
                    write(destination / 'live-provider-check.json', proof)
                    write(destination / 'mini-grounding-check.json', grounding)
                    pair.require_live_provider_check(destination, pair.validate_plan(destination))
        sealed(output / 'qualification.json', evidence)
    return {'live_qualification_complete': True, 'provider_checks': len(evidence['provider']),
            'grounding_suites': len(evidence['grounding'])}


def _check(root):
    config = manifest(root)
    if pair.sha(Path(config['runtime_wrapper'])) != config['runtime_wrapper_sha256']:
        raise ValueError('Runtime credential wrapper changed')
    entries = queue(root)['entries']
    common = None
    for entry in entries:
        folder = root_path(root, entry['plan'])
        plan = read(folder / 'plan.json') if valid_outcome(folder) else pair.validate_plan(folder)
        check_cell_plan(plan, entry['slot'])
        pair.require_live_provider_check(folder, plan)
        fields = {name: plan[name] for name in ('model', 'base_url', 'cua_contract', 'resource_policy',
            'image_identity', 'vm_memory_bytes', 'service_memory_bytes', 'transport_policy')}
        if common is not None and common != fields:
            raise ValueError('Cells differ in shared model, observation or resource budgets')
        common = fields
    # One full image/runtime check suffices: every cell above has the same image identity.
    pending = [e for e in entries if not valid_outcome(root_path(root, e['plan']))]
    if not pending:
        raise RuntimeError('All formal cells are already complete')
    first = root_path(root, pending[0]['plan'])
    index = len(list((root / 'checks').glob('check-*.log'))) + 1
    bounded_command([PROJECT / 'scripts/verified_invoice.py', 'check', '--root', first],
                    root / f'checks/check-{index:03}.log')
    from ui_kobe.osworld.verified_resources import resource_guard
    resource = resource_guard(startup=True, audit_path=root / 'resource-preflight.jsonl')
    value = {'ready': True, 'time_utc': now(), 'cells': 18, 'project_source': pair.project_identity(),
             'queue_sha256': pair.sha(root / read(root / 'state.json')['queue']), 'resource': resource}
    write(root / 'preflight.json', value)
    return {'ready': True, 'cells': 18, 'headroom_ok': resource['headroom_ok']}


def check(root):
    with serial_lock():
        return _check(root)


def valid_outcome(folder):
    value = optional(folder / 'taskviews/outcome.json', {})
    return bool(value.get('complete') and value.get('closed') and value.get('cleanup_ok')
                and value.get('source_unchanged') and value.get('official_score') is not None
                and optional(folder / 'cleanup-taskviews.json', {}).get('cleanup_ok')
                and optional(folder / 'state.json', {}).get('status') == 'completed')


def launch(root, approved):
    if not approved:
        raise PermissionError('--execute-approved-plan is required for the human-authorized campaign')
    from scripts.osworld_native_experiment import require_scope
    require_scope(128 * 1024**2)
    with serial_lock(), file_lock(root / 'launch.lock'):
        manifest(root)
        if any(e['status'] == 'editing' for e in ledger(root)['attempts']):
            raise RuntimeError('An unfinished repair owns this campaign')
        state = read(root / 'state.json')
        if state['status'] not in ('prepared_not_started', 'reprepared_not_started'):
            raise RuntimeError('No implicit retry, resume or replay of an attempted queue')
        ready = read(root / 'preflight.json')
        if (not ready.get('ready') or ready['project_source'] != pair.project_identity()
                or ready['queue_sha256'] != pair.sha(root / state['queue'])):
            raise ValueError('Fresh matching qualification and preflight required')
        receipt = {'started_utc': now(), 'process': process_identity(os.getpid()),
                   'queue': state['queue'], 'queue_sha256': ready['queue_sha256'],
                   'model': 'qwen3.8-max', 'serial_only': True}
        write(root / 'launch-receipt.json', receipt)
        completed = []
        try:
            for entry in queue(root)['entries']:
                folder = root_path(root, entry['plan'])
                if valid_outcome(folder):
                    completed.append(entry['slot']['id'])
                    continue
                if read(folder / 'state.json')['status'] != 'prepared_not_started':
                    raise RuntimeError('Attempted cell requires an audited repair/refreeze, not replay')
                plan = pair.validate_plan(folder)
                check_cell_plan(plan, entry['slot'])
                state.update(status='running', active_slot=entry['slot']['id'], active_plan=entry['plan'],
                             completed_slots=completed, updated_utc=now())
                write(root / 'state.json', state)
                started = time.monotonic()
                execution = {'started_utc': now(), 'slot': entry['slot'], 'plan_sha256': entry['plan_sha256']}
                write(folder / 'cell-execution.json', execution)
                with (folder / 'console.log').open('x', encoding='utf-8') as stream:
                    result = subprocess.run([sys.executable, str(PROJECT / 'scripts/verified_invoice.py'),
                        'launch', '--root', str(folder), '--execute-approved-plan'], cwd=PROJECT,
                        stdout=stream, stderr=subprocess.STDOUT, check=False, pass_fds=inherited_fds())
                execution.update(finished_utc=now(), duration_s=time.monotonic() - started,
                                 returncode=result.returncode)
                write(folder / 'cell-execution.json', execution)
                if result.returncode or not valid_outcome(folder):
                    state.update(status='stopped_on_error', returncode=result.returncode, updated_utc=now())
                    write(root / 'state.json', state)
                    report(root)
                    return 1
                completed.append(entry['slot']['id'])
                report(root)
            state.update(status='completed', active_slot=None, active_plan=None,
                         completed_slots=completed, updated_utc=now())
            write(root / 'state.json', state)
            report(root)
            return 0
        except BaseException as exc:
            state.update(status='stopped_on_error', updated_utc=now(),
                         error={'type': type(exc).__name__, 'message': str(exc)[:2000]})
            write(root / 'state.json', state)
            raise


def start(root, approved):
    if not approved:
        raise PermissionError('--execute-approved-plan is required')
    config = manifest(root)
    if read(root / 'state.json')['status'] not in ('prepared_not_started', 'reprepared_not_started'):
        raise RuntimeError('Campaign is already attempted; no duplicate service')
    with serial_lock():
        pass  # The background launcher takes its own lease after this process releases it.
    revision = Path(read(root / 'state.json')['queue']).parent.name
    unit = f'{root.name}-{revision}'
    index = len(list((root / 'service-starts').glob('*.json'))) + 1
    command = ['systemd-run', '--user', '--unit=' + unit, '--working-directory=' + str(PROJECT),
        '--property=MemoryMax=128M', '--property=MemorySwapMax=0',
        '--property=StandardOutput=append:' + str(root / 'console.log'),
        '--property=StandardError=append:' + str(root / 'console.log'),
        '--setenv=PYTHONDONTWRITEBYTECODE=1']
    if os.environ.get('PYTHONPATH'):
        command += ['--setenv=PYTHONPATH=' + os.environ['PYTHONPATH']]
    command += [sys.executable, config['runtime_wrapper'], str(Path(__file__).resolve()),
                'launch', '--root', str(root), '--execute-approved-plan']
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    value = {'time_utc': now(), 'service': unit + '.service', 'returncode': result.returncode,
             'stdout': result.stdout, 'stderr': result.stderr, 'queue': read(root / 'state.json')['queue']}
    sealed(root / f'service-starts/{index:03}.json', value)
    return value


def tail_events(path, limit=2 * 1024**2):
    """No full trajectory/API payload is loaded by periodic inspection."""
    with Path(path).open('rb') as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - limit))
        raw = stream.read(limit)
    lines = raw.splitlines()
    if size > limit:
        lines = lines[1:]
    for line in lines:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                yield value
        except (ValueError, UnicodeDecodeError):
            continue


def inspect(root):
    with file_lock(root / 'inspection.lock'):
        manifest(root)
        state = read(root / 'state.json')
        book = ledger(root)
        receipt = optional(root / 'launch-receipt.json', {})
        process = receipt.get('process')
        alive = bool(process and process_identity(process['pid']) == process)
        result = {'time_utc': now(), 'status': state['status'], 'active_slot': state.get('active_slot'),
                  'launcher_alive': alive, 'repair_used': book['used'], 'repair_limit': REPAIR_LIMIT,
                  'read_once': True, 'live_api_called': False, 'vm_started': False, 'issues': []}
        result['repair_in_progress'] = any(e['status'] == 'editing' for e in book['attempts'])
        result['next_action'] = ('continue_reserved_repair' if result['repair_in_progress']
            else 'refreeze_passed_repair' if state['status'] == 'paused_for_repair'
                and book['attempts'] and book['attempts'][-1]['status'] == 'passed'
            else 'qualify_check_start' if state['status'] == 'reprepared_not_started'
            else 'final_report' if state['status'] == 'completed' else None)
        if state['status'] == 'paused_for_repair' and not result['repair_in_progress']:
            result['issues'].append('repair_or_refreeze_pending')
        if state['status'] == 'running' and not alive:
            result['issues'].append('launcher_missing_or_identity_changed')
        if state['status'] == 'stopped_on_error':
            result['issues'].append('queue_stopped_on_error')
        if state.get('active_plan'):
            folder = root_path(root, state['active_plan'])
            plan = read(folder / 'plan.json')
            outcome = optional(folder / 'taskviews/outcome.json', {})
            result['outcome'] = {key: outcome.get(key) for key in
                ('official_score', 'complete', 'error', 'cleanup_ok', 'source_unchanged')}
            result['cell_status'] = optional(folder / 'state.json', {}).get('status')
            result['source_unchanged'] = pair.project_identity() == plan['project_source']
            if alive and not result['source_unchanged']:
                result['issues'].append('active_source_changed')
            if alive:
                from scripts.osworld_native_experiment import host_status
                result['current_windows_resources'] = host_status()
                current = result['current_windows_resources']
                if (current['available_ram_gib'] <= 2 or current['c_free_gib'] < 45
                        or current['d_free_gib'] < 12):
                    result['issues'].append('current_resource_headroom_failed')
            latest = []
            for log in sorted((folder / 'taskviews/telemetry').glob('events-*.jsonl'),
                              key=lambda p: p.stat().st_mtime, reverse=True)[:2]:
                latest.extend(tail_events(log))
            resources = list(tail_events(folder / 'taskviews/resource-monitor.jsonl')) \
                if (folder / 'taskviews/resource-monitor.jsonl').exists() else []
            if resources:
                result['resource'] = resources[-1]
                checkpoint = resources[-1]
                if checkpoint.get('headroom_ok') is False:
                    result['issues'].append('resource_headroom_failed')
                if checkpoint.get('phase') == 'before_predict' and alive:
                    timestamp = datetime.fromisoformat(checkpoint['time_utc'])
                    elapsed = (datetime.now(timezone.utc) - timestamp).total_seconds()
                    decision = checkpoint.get('decision')
                    finished = any(e.get('event') == 'decision' and e.get('step') == decision for e in latest)
                    bound = plan['transport_policy']['budget']['step_s'] + 120
                    if elapsed > bound and not finished:
                        result['issues'].append('decision_exceeded_frozen_deadline_requires_diagnosis')
            selected = [e for e in latest if e.get('event') in
                        ('decision', 'request_outcome', 'evaluation_start', 'evaluation_result', 'action_result')]
            result['latest_events'] = [{key: e.get(key) for key in
                ('time_utc', 'event', 'step', 'outcome', 'duration_s')} for e in selected[-8:]]
        result['requires_analysis'] = bool(result['issues'])
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        write(root / f'inspections/{stamp}.json', result)
        write(root / 'latest-inspection.json', result)
        return result


def no_owned_guest(root):
    import docker
    plans = [read(root_path(root, e['plan']) / 'plan.json') for e in queue(root)['entries']]
    labels = {p['run_ids']['taskviews'] for p in plans}
    with closing(docker.from_env(timeout=15)) as client:
        for container in client.containers.list(all=True):
            if container.labels.get('ui-kobe.verified.run') in labels:
                raise RuntimeError('Campaign guest still exists; preserve/clean its exact ownership before repair')


def abort(root, diagnosis, approved):
    """Bounded cleanup of a positively identified abnormal campaign, never another job."""
    if not approved or not diagnosis.strip():
        raise PermissionError('Aborting requires the explicit execution flag and recorded diagnosis')
    manifest(root)
    inspection = read(root / 'latest-inspection.json')
    if not inspection.get('requires_analysis'):
        raise RuntimeError('A normal score or healthy run is not an abort reason')
    state = read(root / 'state.json')
    if (state['status'] not in ('running', 'stopped_on_error')
            or inspection.get('active_slot') != state.get('active_slot')):
        raise RuntimeError('Inspection no longer identifies the active abnormal cell')
    actions = []
    with file_lock(root / 'repair.lock'):
        if state.get('active_plan'):
            folder = root_path(root, state['active_plan'])
            plan = read(folder / 'plan.json')
            receipt = optional(folder / 'taskviews/process-receipt.json', {})
            identity = receipt.get('process')
            if identity and process_identity(identity['pid']) == identity:
                if (receipt.get('run_id') != plan['run_ids']['taskviews']
                        or receipt.get('plan_sha256') != pair.sha(folder / 'plan.json')):
                    raise ValueError('Actor receipt does not identify this frozen cell')
                argv = Path(f"/proc/{identity['pid']}/cmdline").read_bytes().split(b'\0')
                if str(folder).encode() not in argv or b'_run-arm' not in argv:
                    raise ValueError('Actor command does not identify the frozen cell')
                os.kill(identity['pid'], signal.SIGTERM)
                actions.append({'signalled': identity})
            from ui_kobe.osworld.verified_resources import cleanup_owned_run
            cleanup = cleanup_owned_run(plan, plan['run_ids']['taskviews'])
            write(folder / 'abort-cleanup.json', cleanup)
            if not cleanup['cleanup_ok']:
                raise RuntimeError('Owned guest cleanup did not complete')
        starts = sorted((root / 'service-starts').glob('[0-9][0-9][0-9].json'))
        if starts:
            started = unseal(starts[-1])
            unit = started['service']
            expected = f"{root.name}-{Path(state['queue']).parent.name}.service"
            if unit != expected:
                raise ValueError('Service receipt differs from current revision')
            command = subprocess.check_output(['systemctl', '--user', 'show', unit,
                                               '--property=ExecStart', '--value'], text=True, timeout=15)
            if str(root) not in command or str(Path(__file__).resolve()) not in command:
                raise ValueError('Service command differs from this campaign')
            subprocess.run(['systemctl', '--user', 'stop', unit], check=True, timeout=30)
            actions.append({'stopped_service': unit})
        receipt = optional(root / 'launch-receipt.json', {})
        identity = receipt.get('process')
        if identity and process_identity(identity['pid']) == identity:
            raise RuntimeError('Launcher still alive; do not repair frozen code')
        no_owned_guest(root)
        state.update(status='stopped_on_error', updated_utc=now(), abort_reason=diagnosis[:4000])
        write(root / 'state.json', state)
        record = {'time_utc': now(), 'diagnosis': diagnosis[:4000], 'actions': actions,
                  'inspection_sha256': pair.sha(root / 'latest-inspection.json')}
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        write(root / f'aborts/{stamp}.json', record)
        return record


def repair_begin(root, diagnosis, evidence):
    with serial_lock(), file_lock(root / 'repair.lock'):
        manifest(root)
        state = read(root / 'state.json')
        receipt = optional(root / 'launch-receipt.json', {})
        process = receipt.get('process')
        if process and process_identity(process['pid']) == process:
            raise RuntimeError('Never edit frozen source while the campaign launcher is alive')
        if state['status'] not in ('stopped_on_error', 'paused_for_repair'):
            raise RuntimeError('Normal scores and healthy runs do not authorize a repair')
        no_owned_guest(root)
        evidence = evidence.resolve()
        if not evidence.is_relative_to(root) or not evidence.is_file() or not diagnosis.strip():
            raise ValueError('A repair needs an actual campaign evidence file and concrete diagnosis')
        value = ledger(root)
        if value['used'] >= REPAIR_LIMIT or any(e['status'] == 'editing' for e in value['attempts']):
            raise RuntimeError('Repair allowance exhausted or an attempt is already open')
        entry = {'number': value['used'] + 1, 'status': 'editing', 'started_utc': now(),
            'diagnosis': diagnosis[:4000], 'evidence': str(evidence.relative_to(root)),
            'evidence_sha256': pair.sha(evidence), 'before_source': pair.project_identity()}
        value['attempts'].append(entry)
        value['used'] += 1  # Reserve durably BEFORE any code modification.
        write(root / 'repair-ledger.json', value)
        state.update(status='paused_for_repair', updated_utc=now())
        write(root / 'state.json', state)
        return {'repair_number': entry['number'], 'used': value['used'], 'remaining': REPAIR_LIMIT - value['used']}


def repair_finish(root, result, validation):
    with serial_lock(), file_lock(root / 'repair.lock'):
        manifest(root)
        value = ledger(root)
        if not value['attempts'] or value['attempts'][-1]['status'] != 'editing':
            raise RuntimeError('No reserved repair attempt')
        proof = read(validation)
        source = pair.project_identity()
        if result == 'passed' and (proof.get('passed') is not True or proof.get('project_source') != source):
            raise ValueError('A passing repair needs current-source validation evidence')
        entry = value['attempts'][-1]
        entry.update(status=result, finished_utc=now(), after_source=source,
                     validation=str(validation.resolve()), validation_sha256=pair.sha(validation),
                     affected_tasks=affected_cohorts(root, source))
        write(root / 'repair-ledger.json', value)
        return {'repair_number': entry['number'], 'status': result, 'used': value['used'],
                'affected_tasks': entry['affected_tasks']}


def reprepare(args):
    root = args.root.resolve()
    with serial_lock(), file_lock(root / 'repair.lock'):
        config = manifest(root)
        book = ledger(root)
        if not book['attempts'] or book['attempts'][-1]['status'] != 'passed':
            raise RuntimeError('Reprepare requires a verified passing repair')
        repair = book['attempts'][-1]
        if repair.get('queue_created'):
            raise RuntimeError('This repair was already refrozen')
        if pair.project_identity() != repair['after_source']:
            raise ValueError('Source changed after repair validation')
        no_owned_guest(root)
        old = queue(root)
        revision = root / f"revisions/r{repair['number']:03d}"
        revision.mkdir(parents=True, exist_ok=False)
        archive_source(revision)
        entries = []
        for previous in old['entries']:
            folder = root_path(root, previous['plan'])
            if previous['slot']['task'] not in repair['affected_tasks'] and valid_outcome(folder):
                entries.append(previous)
            else:
                entries.append(prepare_cell(root, revision, previous['slot'], config, args.validation_dir))
        sealed(revision / 'queue.json', {'entries': entries, 'created_utc': now(),
                                        'repair_number': repair['number'], 'affected_tasks': repair['affected_tasks']})
        repair['queue_created'] = str((revision / 'queue.json').relative_to(root))
        write(root / 'repair-ledger.json', book)
        pending = sum(not valid_outcome(root_path(root, entry['plan'])) for entry in entries)
        status = 'reprepared_not_started' if pending else 'completed'
        write(root / 'state.json', {'status': status, 'queue': repair['queue_created'],
                                   'active_slot': None, 'updated_utc': now()})
        report(root)
        return {'status': status, 'affected_tasks': repair['affected_tasks'],
                'new_cells': sum(e['revision'] == revision.name for e in entries)}


def events(folder):
    for path in sorted((folder / 'taskviews/telemetry').glob('events-*.jsonl')):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                # Large request image payloads and private model text are not needed for statistics.
                if any(f'"event": "{name}"' in line[:1024] for name in
                       ('api_request', 'api_response', 'observation', 'action_result')):
                    if '"event": "api_request"' in line[:1024]:
                        yield {'event': 'api_request'}
                    continue
                if line.strip():
                    yield json.loads(line)


def summarize_cell(root, entry):
    folder = root_path(root, entry['plan'])
    outcome = optional(folder / 'taskviews/outcome.json', {})
    execution = optional(folder / 'cell-execution.json', {})
    valid = valid_outcome(folder)
    row = dict(entry['slot'], revision=entry['revision'], behavior_sha256=entry['behavior_sha256'],
        plan=entry['plan'], valid=valid, raw_official_score=outcome.get('official_score'),
        official_score=outcome.get('official_score') if valid else None,
        status=optional(folder / 'state.json', {}).get('status'), decisions=outcome.get('decisions'),
        error=outcome.get('error'), duration_s=execution.get('duration_s'), api_requests=0,
        transport_retries=0, semantic_regenerations=0, controller_action_receipts=0,
        tool_errors=0, consecutive_duplicate_actions=0, known_input_tokens=0, known_output_tokens=0,
        unknown_usage_requests=0, model_decision_s=0, evaluation_s=None,
        packets=0, delivered_packets=0, omitted_packets=0, unconfirmed_packets=0,
        packet_audit_errors=[], max_packet_bytes=0, report_rejections=0,
        report_recovery_exhaustions=0, last_report_failure=None,
        graph_link_observations=0, shared_reference_observations=0, omitted_records=0,
        keyboard_lookup_omitted=0, cost=None)
    previous = None
    request_outcomes = 0
    prepared, delivered, omitted = {}, {}, set()
    for event in events(folder):
        kind = event.get('event')
        frame = (event.get('pid'), event.get('frame_id'))
        if kind == 'api_request':
            row['api_requests'] += 1
        elif kind == 'request_outcome':
            request_outcomes += 1
            row['transport_retries'] += event.get('attempt', 1) > 1
            usage = event.get('usage')
            if isinstance(usage, dict):
                row['known_input_tokens'] += usage.get('prompt_tokens', usage.get('input_tokens', 0)) or 0
                row['known_output_tokens'] += usage.get('completion_tokens', usage.get('output_tokens', 0)) or 0
            else:
                row['unknown_usage_requests'] += 1
        elif kind in ('mini_report_regeneration', 'semantic_regeneration'):
            # Accounting snapshots are cumulative within each step. Each
            # explicit regeneration event represents exactly one new candidate.
            row['semantic_regenerations'] += 1
        elif kind == 'mini_report_rejected':
            row['report_rejections'] += 1
            row['last_report_failure'] = event.get('failure')
        elif kind == 'mini_report_recovery_exhausted':
            row['report_recovery_exhaustions'] += 1
        elif kind == 'decision':
            row['model_decision_s'] += event.get('duration_s', 0)
        elif kind == 'evaluation_result':
            row['evaluation_s'] = event.get('duration_s')
        elif kind == 'controller_result' and event.get('phase') == 'action':
            row['controller_action_receipts'] += 1
            command = event.get('command')
            row['consecutive_duplicate_actions'] += command is not None and command == previous
            previous = command
            result = event.get('result') or {}
            if isinstance(result, dict):
                row['tool_errors'] += bool(result.get('error') or result.get('returncode', 0)
                                          or result.get('status') in ('error', 'failed'))
        elif kind == 'mini_fixed_views':
            row['packets'] += 1
            if frame in prepared:
                row['packet_audit_errors'].append('duplicate_packet_frame')
            prepared[frame] = event
            row['max_packet_bytes'] = max(row['max_packet_bytes'], event.get('packet_bytes', 0) or 0)
            row['keyboard_lookup_omitted'] += bool(event.get('keyboard_lookup_omitted'))
            row['omitted_records'] += sum(v.get('omitted_records', 0) for v in event.get('views', {}).values())
            graph = event.get('graph') or {}
            row['graph_link_observations'] += graph.get('link_count', 0)
            row['shared_reference_observations'] += graph.get('shared_reference_count', 0)
        elif kind == 'mini_views_delivered':
            delivered.setdefault(frame, set()).add(event.get('packet_sha256'))
        elif kind == 'mini_views_request_omitted':
            omitted.add(frame)
    # mini_fixed_views is emitted BEFORE transport delivery. Its initial false
    # flag is neither an omission nor an actual delivery receipt.
    for frame, packet in prepared.items():
        receipts = delivered.get(frame, set())
        sha = packet.get('packet_sha256')
        absent = frame in omitted or bool(packet.get('omission_reason') and not sha)
        if receipts and (not sha or receipts != {sha} or absent):
            row['packet_audit_errors'].append('conflicting_packet_receipt')
            row['unconfirmed_packets'] += 1
        elif receipts:
            row['delivered_packets'] += 1
        elif absent:
            row['omitted_packets'] += 1
        else:
            row['unconfirmed_packets'] += 1
    if (set(delivered) | omitted) - set(prepared):
        row['packet_audit_errors'].append('receipt_without_prepared_packet')
    row['unknown_usage_requests'] += max(0, row['api_requests'] - request_outcomes)
    row['input_tokens'] = (row['known_input_tokens']
                           if row['api_requests'] and not row['unknown_usage_requests'] else None)
    row['output_tokens'] = (row['known_output_tokens']
                            if row['api_requests'] and not row['unknown_usage_requests'] else None)
    return row


def report(root):
    entries = queue(root)['entries']
    rows = [summarize_cell(root, entry) for entry in entries]
    complete = all(row['valid'] for row in rows)
    cohorts = {task: {'complete': all(r['valid'] for r in rows if r['task'] == task),
        'behavior_versions': sorted({r['behavior_sha256'] for r in rows if r['task'] == task})}
        for task in TASK_ORDER}
    comparable = complete and all(len(c['behavior_versions']) == 1 for c in cohorts.values())
    aggregate = comparable and len({r['behavior_sha256'] for r in rows}) == 1
    comparisons = []
    for task in TASK_ORDER:
        for mode in MODES:
            high = next(r for r in rows if (r['task'], r['mode'], r['reasoning']) == (task, mode, 'high'))
            low = next(r for r in rows if (r['task'], r['mode'], r['reasoning']) == (task, mode, 'low'))
            pair_ok = high['valid'] and low['valid'] and high['behavior_sha256'] == low['behavior_sha256']
            comparisons.append({'task': task, 'mode': mode, 'comparable': bool(pair_ok),
                'low_minus_high_score': low['official_score'] - high['official_score'] if pair_ok else None})
    value = {'generated_utc': now(), 'statistics_version': 'mini-event-receipts-v2',
        'formal_cells': 18, 'valid_cells': sum(r['valid'] for r in rows),
        'complete': complete, 'cohorts': cohorts, 'cross_task_aggregate_comparable': bool(aggregate),
        'rows': rows, 'high_low_differences': comparisons, 'repair_ledger': ledger(root),
        'macro_official_scores': {f'{effort}/{mode}': sum(r['official_score'] for r in rows
            if r['reasoning'] == effort and r['mode'] == mode) / 3
            for effort in EFFORTS for mode in MODES} if aggregate else None,
        'single_run_per_cell': True, 'statistical_significance_claimed': False,
        'historical_runs_used_as_actor_memory': False, 'probe_usage_included_in_formal_usage': False}
    write(root / 'results.json', value)
    with (root / 'results.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    text = ['# TaskViews-mini 三任务 High/Low 评测', '',
        f"当前有效正式格：{value['valid_cells']}/18；自动修复：{value['repair_ledger']['used']}/10。", '',
        '每格独立运行一次。发票/GIMP 保留官方 0/1；VLC 保留连续分数，不设置额外成功阈值。',
        'GIMP 官方分数不单独验证 alpha；透明度审查应与官方分数分开。', '',
        '|任务|模式|reasoning|官方分数|有效|决策|API请求|输入tokens|输出tokens|耗时秒|修订|',
        '|---|---|---|---:|---|---:|---:|---:|---:|---:|---|']
    for row in rows:
        values = [row[k] for k in ('task', 'mode', 'reasoning', 'official_score', 'valid', 'decisions',
                  'api_requests', 'input_tokens', 'output_tokens', 'duration_s', 'revision')]
        text.append('|' + '|'.join('—' if v is None else str(round(v, 3) if isinstance(v, float) else v)
                                   for v in values) + '|')
    text += ['', '## 解释边界', '',
        'legacy 是原四 View TaskViews-mini，不是 LLM baseline。flat/linked 的严格事实一致性仅用于离线同输入比较。',
        '在线不同模式可能产生不同轨迹。packet 变小若伴随遗漏增加，不能解释为无损压缩。',
        '不同代码行为版本不混算整体增益。保留全部失败与修复前记录，不按得分挑选版本。',
        '历史 baseline/Mini 使用不同代码和目录，仅作参考；未注入本轮 actor。',
        '单次案例评估不计算统计显著性。未知 usage/费用留空，已知部分另外记录。',
        'packet 投递按同帧、同哈希的投递回执计数；无回执且无明确省略时记为未确认。纠错次数按实际再生成事件计数。', '',
        '## 自动巡检', '', '每40分钟执行一次有界检查后退出，不驻留等待。健康运行不自动修改或重跑。',
        '代码修复最多10次；失败与回滚也计数。影响某任务时重新执行该任务的六格对照。', '']
    (root / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    return {key: value[key] for key in ('valid_cells', 'formal_cells', 'complete', 'cross_task_aggregate_comparable')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('qualify', 'prepare', 'check', 'start', 'launch', 'inspect', 'abort',
                                           'report', 'repair-begin', 'repair-finish', 'reprepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path)
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home() / 'osworld-verified/OSWorld')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home() / 'osworld2/OSWorld-V2')
    parser.add_argument('--assets-root', type=Path, default=PROJECT.parent / 'osworld_verified_setup')
    parser.add_argument('--image', type=Path, default=Path.home() / 'osworld-verified/images/Ubuntu.qcow2')
    parser.add_argument('--image-proof', type=Path, default=PROJECT.parent / 'osworld_verified_setup/image-proof.json')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--execute-approved-plan', action='store_true')
    parser.add_argument('--diagnosis')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--result', choices=('passed', 'failed', 'rolled_back'))
    parser.add_argument('--validation', type=Path)
    args = parser.parse_args()
    args.root = args.root.resolve()
    from scripts.osworld_native_experiment import require_scope
    require_scope(128 * 1024**2)
    if args.command in ('prepare', 'qualify', 'reprepare') and args.validation_dir is None:
        parser.error('--validation-dir is required')
    if args.command == 'qualify':
        value = qualify(args)
    elif args.command == 'prepare':
        value = prepare(args)
    elif args.command == 'check':
        value = check(args.root)
    elif args.command == 'start':
        value = start(args.root, args.execute_approved_plan)
    elif args.command == 'launch':
        raise SystemExit(launch(args.root, args.execute_approved_plan))
    elif args.command == 'inspect':
        try:
            value = inspect(args.root)
        except BlockingIOError:
            value = {'skipped': True, 'reason': 'prior inspection still owns its lease'}
    elif args.command == 'report':
        value = report(args.root)
    elif args.command == 'abort':
        value = abort(args.root, args.diagnosis or '', args.execute_approved_plan)
    elif args.command == 'repair-begin':
        if not args.diagnosis or args.evidence is None:
            parser.error('--diagnosis and --evidence are required')
        value = repair_begin(args.root, args.diagnosis, args.evidence)
    elif args.command == 'repair-finish':
        if args.result is None or args.validation is None:
            parser.error('--result and --validation are required')
        value = repair_finish(args.root, args.result, args.validation)
    else:
        value = reprepare(args)
    print(json.dumps(value, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
