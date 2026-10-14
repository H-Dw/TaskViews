"""Serial UI-KOBE-like -> Mini dispatch after the original service fully exits.

The systemd completion callback is an event handler, not another polling job.
Every Python invocation runs in the same registered 128 MiB/zero-swap scope.
Provider exhaustion retains the VM and requires new human retry authorization.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import fcntl
import json
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.osworld_native_experiment import (PYTHON, digest, event_stream, frozen_check, launch,  # noqa: E402
                                              load, require_scope, write)


def completion_hook(root, run_id, directory):
    root, directory = Path(root).resolve(), Path(directory)
    if not (root / 'pipeline.json').is_file() or not (root / 'state.json').is_file():
        raise ValueError('Completion controller must be prepared before launching')
    name = run_id + '-followup.service'
    controller = 'task059_reasoning_matrix.py' if load(root / 'pipeline.json').get('version') == 'qwen-task059-reasoning-matrix-v1' else 'task059_low50_pipeline.py'
    command = ['systemd-run', '--user', '--scope', '--quiet', '--property=MemoryMax=128M',
               '--property=MemorySwapMax=0', str(PYTHON), str(PROJECT / 'scripts' / controller),
               'advance', '--root', str(root)]
    text = ('[Unit]\nDescription=Serial Task059 completion dispatch\n\n[Service]\nType=oneshot\n'
            f'WorkingDirectory={PROJECT}\nExecStart={shlex.join(command)}\n'
            'MemoryMax=128M\nMemorySwapMax=0\nRestart=no\nTimeoutStartSec=240\n')
    path = directory / name
    if path.exists() and path.read_text() != text:
        raise RuntimeError('Refuse to overwrite a different completion unit')
    path.write_text(text)
    return name


def unit_state(name):
    return dict(line.split('=', 1) for line in subprocess.check_output([
        'systemctl', '--user', 'show', name, '--property=MainPID,ControlPID,ActiveState,SubState'
    ], text=True).splitlines())


def record(root, state, **values):
    state.update(values, time=time.time())
    write(root / 'state.json', state)
    with (root / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(values | {'time': state['time']}, ensure_ascii=False) + '\n')


def retire_checkpoint_payloads(stage):
    cp = stage / 'checkpoints'
    report = stage / 'finished-checkpoint-cleanup.json'
    if report.exists():
        return
    if not cp.exists():
        write(report, {'time': time.time(), 'already_absent': True})
        return
    assert cp.resolve() == stage.resolve() / 'checkpoints' and not cp.is_symlink()
    dest = stage / 'retired-checkpoint-metadata'
    dest.mkdir(exist_ok=False)
    for folder in cp.glob('tv-*'):
        if folder.is_dir():
            saved = dest / folder.name
            saved.mkdir()
            for name in ('manifest.json', 'expired.json', 'boundary.json', 'incomplete.json'):
                if (folder / name).is_file():
                    shutil.copyfile(folder / name, saved / name)
    if (cp / 'latest.json').exists():
        shutil.copyfile(cp / 'latest.json', dest / 'latest.json')
    shutil.rmtree(cp)
    write(report, {'time': time.time(), 'removed': str(cp), 'metadata': str(dest), 'no_vm_or_actor_restore': True})


def settled_requests(stage):
    requests, outcomes = set(), set()
    for _, _, event in event_stream(stage):
        if event.get('event') == 'api_request':
            requests.add(event['request_id'])
        elif event.get('event') == 'request_outcome':
            outcomes.add(event['request_id'])
    return requests, outcomes


def active_plan(cfg, state, arm):
    """A validated replacement plan can be prepared without editing old plans."""
    override = state.get('plan_overrides', {}).get(arm)
    if override is None:
        return Path(cfg['plans'][arm]).resolve()
    if arm != 'taskviews' and (Path(cfg['plans'][arm]) / arm).exists():
        raise ValueError('The existing UI episode must keep its original stage')
    root = Path(override['root']).resolve()
    if (digest(root / 'plan.json') != override['plan_sha256']
            or digest(root / 'validation.json') != override['validation_sha256']):
        raise RuntimeError('Replacement Mini plan/proof changed')
    return root


def advance(root):
    root = Path(root).resolve()
    cfg = load(root / 'pipeline.json')
    state = load(root / 'state.json')
    if state['config_sha256'] != digest(root / 'pipeline.json'):
        raise RuntimeError('Pipeline configuration changed')
    if cfg['order'] != ['ui_kobe_like', 'taskviews'] or cfg['max_steps'] != 50 or cfg['evaluation_steps'] != [15, 30, 50]:
        raise ValueError('Not the authorized Task059 low50 pipeline')
    if cfg['generation_profile'] not in ('qwen-sse-low-total16k', 'qwen-sse-high-total16k', 'qwen-sse-xhigh-total16k'):
        raise ValueError('Both arms require one explicit frozen SSE reasoning profile')
    if state.get('phase') == 'complete':
        return state
    if state.get('formal_actor_resume_authorized') is False:
        return state  # Independent API diagnostics/source repair do not authorize actor continuation.
    for arm in cfg['order']:
        plan_root = active_plan(cfg, state, arm)
        if not plan_root.is_relative_to(root):
            raise ValueError('Arm plan escaped its pipeline')
        stage = plan_root / arm
        if not stage.exists():
            frozen_check(plan_root)
            record(root, state, phase=arm + '_launch_submitted', current_arm=arm)
            launch(plan_root, arm)
            return state
        m = load(stage / 'manifest.json')
        if m['generation_profile']['name'] != cfg['generation_profile']:
            raise RuntimeError('Actual arm reasoning profile differs from its serial pair')
        current = unit_state(m['unit'])
        if current['ControlPID'] != '0' or current['MainPID'] != '0' or current['ActiveState'] in ('active', 'activating', 'deactivating'):
            return state
        if (stage / 'paused.json').exists():
            paused = load(stage / 'paused.json')
            requests, outcomes = settled_requests(stage)
            if (paused.get('error_type') == 'StartupRecoveryProbe' and not requests
                    and not state.get(arm + '_startup_resumed')):
                from scripts.taskviews_recovery import resume
                result = resume(stage, Path(m['plan_root']) / 'validation.json', 'Verify the authorized new episode initial checkpoint in the same VM')
                if result['status'] == 'resuming':
                    record(root, state, phase=arm + '_initial_checkpoint_resume_submitted', current_arm=arm,
                           **{arm + '_startup_resumed': True}, last_resume=result)
                else:
                    record(root, state, phase=arm + '_waiting_startup_resources', current_arm=arm, last_resume=result)
                return state
            record(root, state, phase=arm + '_paused', current_arm=arm,
                   pause={'error_type': paused.get('error_type'), 'error': paused.get('error'),
                          'requires_new_human_retry_authorization': True},
                   requests=len(requests), settled=len(outcomes), no_automatic_retry=True)
            return state
        if not (stage / 'audit.json').exists():
            record(root, state, phase=arm + '_failed_before_audit', current_arm=arm, unit=current)
            return state
        audit = load(stage / 'audit.json')
        if not all(audit.get(k) for k in ('valid_score', 'source_unchanged', 'cleanup_ok')):
            record(root, state, phase=arm + '_audit_failed', current_arm=arm,
                   audit_checks={k: audit.get(k) for k in ('valid_score', 'source_unchanged', 'cleanup_ok')})
            return state
        completed = state.get(arm + '_completed')
        if completed and (completed.get('audit') != str(stage / 'audit.json')
                          or completed.get('audit_sha256') != digest(stage / 'audit.json')
                          or completed.get('cleanup_verified') is not True):
            raise RuntimeError('Completed predecessor cleanup receipt changed')
        requests, outcomes = settled_requests(stage)
        if requests != outcomes:
            raise RuntimeError('An API request is unsettled; cannot advance the serial pipeline')
        if len(Path('/proc/swaps').read_text().splitlines()) != 1:
            raise RuntimeError('Swap is enabled')
        import docker
        with closing(docker.from_env(timeout=15)) as client:
            if client.containers.list(all=True, filters={'label': 'ui-kobe.osworld.run=' + m['run_id']}):
                raise RuntimeError('Owned predecessor VM still exists')
        for runtime in m.get('runtime_paths', []):
            if Path(runtime).exists():
                raise RuntimeError('Owned predecessor overlay remains')
        # Ports were checked before recording completion. A successor may now
        # legitimately reuse them; continue checking the old VM/overlay identity.
        if not completed and (stage / 'checkpoint-vm.json').exists():
            for port in load(stage / 'checkpoint-vm.json')['ports'].values():
                with socket.socket() as s:
                    s.settimeout(1)
                    if s.connect_ex(('127.0.0.1', port)) == 0:
                        raise RuntimeError('Owned predecessor port still bound')
        retire_checkpoint_payloads(stage)
        result = {'score': audit['score'], 'audit': str(stage / 'audit.json'), 'audit_sha256': digest(stage / 'audit.json'),
                  'milestones': audit.get('evaluation_milestones', []),
                  'all_requested_milestones_scored': audit.get('all_requested_milestones_scored'),
                  'decisions': audit['counters']['decisions'], 'cleanup_verified': True}
        if not state.get(arm + '_completed'):
            record(root, state, phase=arm + '_complete', **{arm + '_completed': result})
    record(root, state, phase='complete', current_arm=None, no_remaining_owned_vm=True)
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['advance'])
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    require_scope(128 * 1024**2)
    root = args.root.resolve()
    with (root / '.dispatch.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = advance(root)
    print(json.dumps({k: state.get(k) for k in ('phase', 'current_arm', 'pause', 'requests', 'settled')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
