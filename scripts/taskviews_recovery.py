"""Read-only inspection and audited checkpoint continuation for the v8 Task059 run."""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.osworld_native_experiment import (  # noqa: E402
    digest, event_stream, frozen_check, host_status, load, project_snapshot, require_scope, write)


def continuation_output(manifest, branch):
    """Keep previous official outputs away from upstream unfinished-task deletion."""
    initial = manifest.setdefault('initial_official_results', manifest['official_results'])
    output = Path(initial).parent/'continuations'/branch/'qwen'
    segments = manifest.setdefault('result_segments', [initial])
    segments.append(str(output))
    arguments = list(manifest['official_arguments'])
    for flag, value in (('--result_dir', str(output)), ('--cache_dir', str(output.parent/'cache'))):
        if arguments.count(flag) != 1:
            raise RuntimeError('Official output argument contract changed')
        arguments[arguments.index(flag)+1] = value
    manifest['official_arguments'] = arguments
    manifest['official_results'] = str(output)
    return output


def inspect_stage(stage):
    manifest = load(stage/'manifest.json')
    state = load(stage/'state.json') if (stage/'state.json').exists() else {}
    counters, pending, known, unknown = {}, set(), 0, []
    seen = set()
    for path, line, event in event_stream(stage):
        kind = event.get('event')
        counters[kind] = counters.get(kind, 0)+1
        rid = event.get('request_id')
        if kind == 'api_request':
            pending.add(rid)
        if kind == 'request_outcome':
            pending.discard(rid)
            if rid in seen:
                raise RuntimeError('Duplicate settled request identity')
            seen.add(rid)
            usage = event.get('usage')
            if usage is None:
                unknown.append(rid)
            else:
                known += usage['total_tokens']
    latest = load(stage/'checkpoints/latest.json') if (stage/'checkpoints/latest.json').exists() else None
    paused = load(stage/'paused.json') if (stage/'paused.json').exists() else None
    vm = load(stage/'checkpoint-vm.json') if (stage/'checkpoint-vm.json').exists() else None
    result = {'time': time.time(), 'unit': manifest['unit'], 'state': state.get('status'),
              'unit_state': subprocess.check_output(['systemctl','--user','show',manifest['unit'],
                 '--property=ActiveState,SubState,MainPID','--value'], text=True).splitlines(),
              'counters': counters, 'pending': sorted(pending), 'known_total_tokens': known,
              'unknown_request_ids': unknown, 'latest_checkpoint': latest, 'pause': paused,
              'vm_id': vm['container'] if vm else None,
              'windows': state.get('latest_resources', {}).get('windows'), 'score': None}
    # Grade may only come from the original official evaluation result, never
    # from runner success, a checkpoint or the summary's placeholder 0.
    for path, line, event in event_stream(stage):
        if event.get('event') == 'evaluation_result':
            result['score'] = event.get('score')
            result['official_evaluation_event'] = {'path':str(path),'line':line,'sha256':digest(path)}
            result['evaluation_returned'] = True
    write(stage/'current-status.json', result)
    return result


def configure_qwen_transport_retry(plan, manifest, attempts):
    """Explicit transport-only migration; never rewrite completed GUI commands."""
    from ui_kobe.api.qwen_native import QwenTransportBudget, transport_policy
    if manifest.get('agent_interface') != 'qwen-native' or plan.get('agent_interface') != 'qwen-native':
        raise ValueError('Qwen retry migration requires the Qwen native provider')
    budget = QwenTransportBudget(attempts=attempts)
    args = list(manifest['official_arguments'])
    if args.count('--max_api_retries') != 1:
        raise RuntimeError('Original retry argument is missing or duplicated')
    args[args.index('--max_api_retries') + 1] = str(attempts)
    for flag, value in (('--retry_sleep_base', '3'), ('--retry_sleep_cap', '60' if attempts > 2 else '15')):
        if args.count(flag) > 1:
            raise RuntimeError('Original backoff argument is duplicated')
        if flag in args:
            args[args.index(flag) + 1] = value
        else:
            args.extend([flag, value])
    plan['stream_budget'] = budget.__dict__
    plan['qwen_transport_policy'] = manifest['qwen_transport_policy'] = transport_policy(budget)
    manifest['official_arguments'] = args


def configure_qwen_reasoning(plan, manifest, saved, effort):
    """Explicit human-authorized UI-KOBE-like migration, with no history replay."""
    from ui_kobe.api.qwen_native import generation_profile, generation_request_fields, reasoning_migration_matches
    from ui_kobe.osworld.taskviews_profiles import UI_KOBE_PROFILE, checkpoint_profile
    if (plan.get('agent_interface') != 'qwen-native' or manifest.get('agent_interface') != 'qwen-native'
            or checkpoint_profile(manifest) != UI_KOBE_PROFILE
            or saved.get('checkpoint_actor_profile') != UI_KOBE_PROFILE
            or plan['generation_profile'] != manifest['generation_profile']
            or saved['generation_profile'] != manifest['generation_profile']):
        raise ValueError('Reasoning migration needs the exact current Qwen UI-KOBE-like checkpoint profile')
    profile = generation_profile(f'qwen-native-{effort}-16k').__dict__
    migration = {'version': 'qwen-reasoning-migration-v1', 'checkpoint': saved['tag'],
                 'before': saved['generation_profile'], 'after': profile}
    if not reasoning_migration_matches(migration, tag=saved['tag'],
                                      before=saved['generation_profile'], after=profile):
        raise ValueError('Reasoning migration may only change reasoning within frozen generation bounds')
    arguments = list(manifest['official_arguments'])
    flags = ('--enable_thinking', '--no-enable_thinking')
    if sum(arguments.count(flag) for flag in flags) != 1:
        raise ValueError('Original thinking flag is missing or duplicated')
    arguments[arguments.index(next(flag for flag in flags if flag in arguments))] = '--enable_thinking'
    plan['generation_profile'] = manifest['generation_profile'] = profile
    plan['qwen_reasoning_migration'] = manifest['qwen_reasoning_migration'] = migration
    plan['provider_request'] = {**plan['provider_request'],
                               **generation_request_fields(generation_profile(profile['name']))}
    manifest['official_arguments'] = arguments


def resume(stage, validation, reason, checkpoint=None, provider_ready=False, controls_view=False,
           qwen_transport_attempts=None, qwen_reasoning_effort=None):
    import docker
    from scripts.native_resource_accounting import sample, reserve_ok
    from scripts.osworld_task035_background import cgroup
    from ui_kobe.osworld.checkpoints import Checkpoints, QMP, require_running_checkpoint_container
    from ui_kobe.osworld.taskviews_profiles import MINI_PROFILE, FULL_PROFILE, checkpoint_profile
    manifest = load(stage/'manifest.json')
    previous_manifest = deepcopy(manifest)
    if manifest.get('taskviews_profile', FULL_PROFILE) == MINI_PROFILE:
        from scripts.osworld_native_experiment import require_mini_branch
        require_mini_branch()
    if manifest.get('task_id') != '059' or not manifest.get('checkpoint_policy', {}).get('enabled'):
        raise ValueError('Not a checkpoint-enabled Task059 run')
    active = subprocess.run(['systemctl','--user','is-active',manifest['unit']],
                            text=True, capture_output=True, check=False).stdout.strip()
    if active == 'active':
        raise RuntimeError('Task is still running; cannot replay a checkpoint')
    if not (stage/'paused.json').exists():
        raise RuntimeError('No paused checkpoint; never relaunch a terminal/fresh episode')
    require_provider_recovery(stage, provider_ready)
    if time.time() < load(stage/'paused.json').get('retry_not_before', 0):
        return {'status':'waiting_for_provider_cooldown'}
    checked = load(validation)
    if checked['exit_code'] != 0 or checked['project_source'] != project_snapshot():
        raise RuntimeError('Current repair needs passing bounded validation')
    cp = Checkpoints(stage, manifest)
    _, saved = cp.read(checkpoint, metadata_only=True)
    if saved.get('checkpoint_actor_profile', FULL_PROFILE) != checkpoint_profile(manifest):
        raise RuntimeError('Cannot migrate a checkpoint between full, Mini and UI-KOBE-like profiles')
    cp.require_no_replay(saved)
    old = Path(manifest['plan_root'])
    # Official files and assets are still frozen. A repair gets a new source
    # revision; original plans/manifests/failed branch data remain intact.
    old_plan = load(old/'plan.json')
    if controls_view and (manifest.get('taskviews_profile') != MINI_PROFILE or manifest.get('arm') != 'taskviews'):
        raise ValueError('Read-only controls extension can only be enabled for TaskViews Mini')
    repair_commit = None
    if old_plan.get('iteration_commit_required'):
        from scripts.osworld_native_experiment import committed_source
        repair_commit = committed_source()
    from ui_kobe.osworld.runner import source_snapshot
    from scripts.osworld_native_experiment import REPO
    if source_snapshot(REPO) != load(old/'osworld-source-planned.json'):
        raise RuntimeError('Official source changed')
    for path, expected in old_plan['asset_sha256'].items():
        if digest(Path(path)) != expected:
            raise RuntimeError('Original task asset changed')
    with closing(docker.from_env()) as client:
        owned = client.containers.get(saved['vm']['container'])
        require_running_checkpoint_container(owned, saved['vm'], saved['vm']['path_to_vm'], manifest['run_id'])
        QMP(Path(saved['vm']['storage'])/'taskviews.qmp').require_snapshot(saved['tag'])
        windows = sample(client, {**manifest, 'cgroup': None}, host_status, cgroup(), teardown=False)['windows']
        if not reserve_ok(windows, startup=True):
            return {'status':'waiting_for_resources','windows':windows,'checkpoint':saved['tag']}
    revision = stage/'repair-plans'/uuid.uuid4().hex
    revision.mkdir(parents=True)
    plan = {**old_plan, 'repair': {'reason':reason, 'parent_plan':str(old),
                                 'checkpoint':saved['tag'], 'time':time.time()}}
    if qwen_transport_attempts is not None:
        configure_qwen_transport_retry(plan, manifest, qwen_transport_attempts)
    if qwen_reasoning_effort is not None:
        configure_qwen_reasoning(plan, manifest, saved, qwen_reasoning_effort)
    if repair_commit:
        plan['source_commit'] = repair_commit
    if controls_view:
        from kobe_views.controls_view import policy
        plan['mini_controls_view'] = policy()
        manifest['mini_controls_view'] = policy()
    write(revision/'plan.json', plan)
    write(revision/'project-source-planned.json', project_snapshot())
    write(revision/'osworld-source-planned.json', source_snapshot(REPO))
    write(revision/'preparation.json', {'plan_sha256':digest(revision/'plan.json')})
    write(revision/'validation.json', checked)
    write(revision/'previous-manifest.json', previous_manifest)
    continuation_output(manifest, revision.name)
    manifest['plan_root'] = str(revision)
    if repair_commit:
        manifest['source_commit'] = repair_commit
    write(stage/'manifest.json', manifest)
    frozen_check(revision)
    request = {'checkpoint':saved['tag'], 'reason':reason, 'validation':str(validation),
               'validation_sha256':digest(validation), 'time':time.time(), 'reset':False}
    write(stage/'resume-history'/(uuid.uuid4().hex+'.json'), request)
    write(stage/'resume-request.json', request)
    if (stage/'provider-access-block.json').exists():
        write(stage/'provider-recovery-confirmations'/(uuid.uuid4().hex+'.json'),
              {'time':time.time(),'reason':reason,'user_confirmed_provider_ready':provider_ready,
               'block_sha256':digest(stage/'provider-access-block.json'),'checkpoint':saved['tag']})
    (stage/'pause-request.json').unlink(missing_ok=True)
    restart_checkpoint_unit(manifest['unit'])
    return {'status':'resuming','checkpoint':saved['tag'],'completed_steps':saved['completed_steps'], 'reset':False}


def restart_checkpoint_unit(unit):
    # A successfully paused inactive service may already be garbage-collected
    # by systemd. reset-failed rejects that unloaded unit; only failed services
    # require clearing failure state before starting the saved unit file.
    subprocess.run(['systemctl','--user','daemon-reload'], check=True)
    state = subprocess.run(['systemctl','--user','is-active',unit],
                           text=True, capture_output=True, check=False).stdout.strip()
    if state == 'active':
        raise RuntimeError('Checkpoint unit became active before continuation')
    if state == 'failed':
        subprocess.run(['systemctl','--user','reset-failed',unit], check=True)
    subprocess.run(['systemctl','--user','start',unit], check=True)


def require_provider_recovery(stage, provider_ready):
    if (stage/'provider-access-block.json').exists() and not provider_ready:
        raise RuntimeError('Provider billing/quota blocked; user must confirm recovery before checkpoint continuation')


def pause(stage, reason):
    import os
    import signal
    manifest = load(stage/'manifest.json')
    if manifest.get('task_id') != '059' or not manifest.get('checkpoint_policy', {}).get('enabled'):
        raise ValueError('Not this checkpoint-enabled Task059 run')
    vm = load(stage/'checkpoint-vm.json')
    pid = vm['worker_pid']
    group = Path('/proc')/str(pid)/'cgroup'
    if not group.exists() and (stage/'paused.json').exists():
        from ui_kobe.osworld.checkpoints import Checkpoints
        _, saved = Checkpoints(stage,manifest).read(metadata_only=True)
        return {'status':'already_paused','checkpoint':saved['tag'],'completed_steps':saved['completed_steps']}
    relative = group.read_text().strip().split('::',1)[1]
    if str(Path('/sys/fs/cgroup')/relative.lstrip('/')) != manifest['cgroup']:
        raise RuntimeError('Checkpoint worker no longer belongs to this run')
    write(stage/'pause-request.json', {'reason':reason,'time':time.time()})
    os.kill(pid,signal.SIGUSR1)
    return {'status':'pause_requested','worker_pid':pid,'reason':reason}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action', choices=('inspect','resume','pause'))
    p.add_argument('--stage',type=Path,required=True)
    p.add_argument('--validation',type=Path)
    p.add_argument('--reason')
    p.add_argument('--checkpoint', help='Exact retained checkpoint tag; default is last safe boundary')
    p.add_argument('--provider-ready', action='store_true', help='Only after the user confirms provider billing/quota recovery')
    p.add_argument('--controls-view', action='store_true', help='Explicitly enable the checkpoint-compatible Mini controls view')
    p.add_argument('--qwen-transport-attempts', type=int, choices=range(1, 7),
                   help='Explicitly migrate Qwen transport retries within the unchanged output/time budgets')
    p.add_argument('--qwen-reasoning-effort', choices=('low', 'medium', 'xhigh'),
                   help='Explicitly migrate the same UI-KOBE-like checkpoint to Qwen reasoning')
    args=p.parse_args()
    require_scope(128*1024**2)
    if args.action == 'resume':
        if not args.validation or not args.reason:
            p.error('Resume requires validation and a specific repair/cooldown reason')
        result=resume(args.stage,args.validation,args.reason,args.checkpoint,args.provider_ready,args.controls_view,
                      args.qwen_transport_attempts, args.qwen_reasoning_effort)
    elif args.action == 'pause':
        if not args.reason:
            p.error('Pause requires a specific anomaly reason')
        result=pause(args.stage,args.reason)
    else:
        result=inspect_stage(args.stage)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
