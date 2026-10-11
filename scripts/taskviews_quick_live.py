"""Real TaskViews micro-task on a reversible branch of the preserved VM.

No official source/reset/evaluator is changed. Parent Agent remains paused.
Finally reload its entire VM checkpoint and stop CPUs. Only the new actor's
unchanged official compiler commands control the GUI after blank initialization.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
REPO = Path.home() / 'osworld2/OSWorld-V2'
sys.path[:0] = [str(PROJECT), str(REPO), str(REPO / 'scripts/python')]
from scripts.osworld_native_experiment import (  # noqa: E402
    PYTHON, digest, host_status, load, project_snapshot, require_scope, write)
from ui_kobe.osworld.quick_checks import GEOGEBRA_POINT, TEXT_SAVE, TEXT_KEYBOARD_SAVE, TEXT_EDIT_SAVE  # noqa: E402
from ui_kobe.osworld.pointer_checks import POINTER_CASES  # noqa: E402

CONTRACT = dict(history_n=20, image_max=1, fold_size=1,
    context_max_text_chars=32000, context_max_payload_chars=2000000,
    context_rough_text_token_budget=12000, context_reserve_chars=10000,
    taskviews_context_bytes=8000)


def now():
    return datetime.now(timezone.utc).isoformat()


def parent_files(stage):
    return {str(p): digest(p) for p in [stage / name for name in
        ('manifest.json', 'state.json', 'paused.json', 'checkpoint-vm.json', 'checkpoints/latest.json')]}


def official_hash():
    from ui_kobe.osworld.runner import source_snapshot
    return hashlib.sha256(json.dumps(source_snapshot(REPO), sort_keys=True).encode()).hexdigest()


def verify_source(plan):
    from ui_kobe.osworld.official_base import verify_official_base
    checked = load(Path(plan['validation']))
    if (digest(Path(plan['validation'])) != plan['validation_sha256'] or checked['exit_code'] != 0
            or checked['project_source'] != project_snapshot()
            or not checked['official_source_unchanged']
            or verify_official_base(REPO) != checked['official_base']
            or official_hash() != plan['official_source_hash']):
        raise RuntimeError('Current source needs passing frozen validation')


def restore_parent(qmp, tag):
    """Stop even if restore raises; a failed restore needs human recovery."""
    try:
        qmp.load(tag)
    finally:
        qmp.call('stop')
    status = qmp.call('query-status')
    if status['running'] or status['status'] != 'paused':
        raise RuntimeError('Parent VM was not left paused after restore')
    return status


def prepare(directory, parent, validation, *, provider_confirmed=False, resume_stage=None,
            repair_blank_initialization=False, task_kind='geogebra'):
    require_scope(128 * 1024**2)
    if not provider_confirmed:
        raise RuntimeError('Human service-recovery confirmation required for this live test')
    if directory.exists():
        raise RuntimeError('Never replace a prepared/live test directory')
    if task_kind not in {'geogebra', 'text', 'keyboard-text', 'edit-text'} | POINTER_CASES.keys():
        raise ValueError('Unknown declared micro-task kind')
    task = {'geogebra': GEOGEBRA_POINT, 'text': TEXT_SAVE,
            'keyboard-text': TEXT_KEYBOARD_SAVE, 'edit-text': TEXT_EDIT_SAVE, **POINTER_CASES}[task_kind]
    from ui_kobe.osworld.checkpoints import Checkpoints, QMP, require_running_checkpoint_container
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.api.qwen_native import BASE_URL, MODEL, QwenGenerationProfile
    manifest = load(parent / 'manifest.json')
    if (load(parent / 'state.json')['status'] != 'checkpoint_paused'
            or load(parent / 'paused.json')['status'] != 'paused'):
        raise RuntimeError('Parent must remain checkpoint-paused')
    active = subprocess.check_output(['systemctl', '--user', 'show', manifest['unit'],
        '--property=ActiveState', '--value'], text=True).strip()
    if active == 'active':
        raise RuntimeError('Parent Agent is still active')
    dest, boundary = Checkpoints(parent, manifest).read(metadata_only=True)
    # A stopped Docker VM is not a resumable paused guest, and actor metadata
    # alone cannot establish that all writable disks retain the snapshot.
    import docker
    with closing(docker.from_env(timeout=15)) as client:
        container = client.containers.get(boundary['vm']['container'])
        require_running_checkpoint_container(container, boundary['vm'],
            boundary['vm']['path_to_vm'], manifest['run_id'])
        QMP(Path(boundary['vm']['storage'])/'taskviews.qmp').require_snapshot(boundary['tag'])
    directory.mkdir(parents=True)
    plan = {'created_utc': now(), 'run_id': 'taskviews-quick-' + uuid.uuid4().hex,
        'test_kind': task['test_kind'], 'task': task,
        'parent_stage': str(parent), 'parent_vm_owner_run_id': manifest['run_id'],
        'parent_unit': manifest['unit'], 'parent_checkpoint': boundary['tag'],
        'parent_completed_steps': boundary['completed_steps'], 'parent_commands': boundary['command_count'],
        'parent_checkpoint_manifest_sha256': digest(dest / 'manifest.json'),
        'parent_files_sha256': parent_files(parent), 'vm': load(parent / 'checkpoint-vm.json'),
        'model': MODEL, 'base_url': BASE_URL, 'api_key_env': 'QWEN_API_KEY',
        'service_recovery_confirmed_by_human': True,
        'validation': str(validation), 'validation_sha256': digest(validation),
        'official_source_hash': official_hash(),
        'cua_contract': CUAContract(**CONTRACT).snapshot(),
        'generation_profile': QwenGenerationProfile().__dict__,
        'native_decision_limit': 500, 'diagnostic_pause_after_decisions': 20,
        'expected_decisions': [5, 12] if task_kind == 'geogebra' else [4, 8], 'api_concurrency': 1,
        'parent_reset': False, 'parent_agent_resumed': False,
        'rollback': 'finally load parent whole-VM checkpoint and stop; preserve original files/snapshots',
        'score_policy': 'custom artifact score only after native terminal; official_score remains NULL'}
    if resume_stage is not None:
        old_plan = load(resume_stage.parent / 'plan.json')
        if (old_plan['vm']['container'] != plan['vm']['container']
                or old_plan['task'] != plan['task'] or not (resume_stage / 'paused.json').exists()):
            raise RuntimeError('Quick continuation needs the same goal/VM and a real paused boundary')
        old_dest, old_boundary = Checkpoints(resume_stage, {}).read(metadata_only=True)
        plan['quick_continuation'] = {'stage': str(resume_stage), 'tag': old_boundary['tag'],
            'manifest_sha256': digest(old_dest / 'manifest.json'),
            'completed_steps': old_boundary['completed_steps'], 'commands': old_boundary['command_count'],
            'original_plan_ref': str(resume_stage.parent / 'plan.json'), 'new_episode': False}
    if repair_blank_initialization:
        if not resume_stage or old_boundary['completed_steps'] != 0 or old_boundary['command_count'] != 0:
            raise RuntimeError('Blank fixture repair is allowed only at a saved pre-action zero boundary')
        plan['repair_blank_initialization'] = True
    verify_source(plan)
    write(directory / 'plan.json', plan)
    print(json.dumps({'status': 'prepared', 'directory': str(directory), 'parent_steps': boundary['completed_steps'],
                      'official_score': None}))


def launch(directory):
    # The worker's systemd WorkingDirectory is the official repository, not
    # the caller's project cwd. Persist an absolute plan/log location.
    directory = Path(directory).resolve()
    require_scope(128 * 1024**2)
    plan = load(directory / 'plan.json')
    verify_source(plan)
    if parent_files(Path(plan['parent_stage'])) != plan['parent_files_sha256']:
        raise RuntimeError('Parent boundary changed since preparation')
    if (directory / 'service.unit').exists():
        raise RuntimeError('This quick-test launch was already submitted')
    unit = plan['run_id'] + '.service'
    command = shlex.join([str(PYTHON), str(Path(__file__).resolve()), 'worker', '--directory', str(directory)])
    shell = 'source ~/osworld2/env.sh; exec ' + command
    text = ('[Unit]\nDescription=TaskViews reversible GUI micro-task\n[Service]\nType=simple\n'
        f'WorkingDirectory={REPO}\nExecStart=/bin/bash -ic {shlex.quote(shell)}\n'
        'MemoryMax=2G\nMemoryHigh=1792M\nMemorySwapMax=0\nOOMPolicy=stop\nRestart=no\n'
        'KillMode=control-group\nTimeoutStopSec=210\nCPUQuota=100%\nCPUWeight=50\nNice=10\n'
        f'StandardOutput=append:{directory}/console.log\nStandardError=append:{directory}/console.log\n'
        'Environment=PYTHONDONTWRITEBYTECODE=1\nEnvironment=PYTHONUNBUFFERED=1\n')
    service = Path.home() / '.config/systemd/user' / unit
    if service.exists():
        raise RuntimeError('Service identity collision')
    service.parent.mkdir(parents=True, exist_ok=True)
    service.write_text(text)
    (directory / 'service.unit').write_text(text)
    write(directory / 'service.json', {'unit': unit, 'submitted_utc': now()})
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'start', unit], check=True)
    print(json.dumps({'status': 'submitted', 'unit': unit}))


def setup_blank(controller, run_id):
    """Only blank initialization; never pre-create the target point or answer."""
    executable = '/home/user/.local/share/task059data/GeoGebra-Linux-Portable-5-4-925-3/geogebra-portable'
    blank = '/tmp/' + run_id + '.ggb'
    from scripts.taskviews_quick_setup import blank_setup_command
    command = blank_setup_command(executable, blank)
    from ui_kobe.osworld.runner import checked_execution_result
    receipt = checked_execution_result(controller.execute_python_command(command))
    return {'command': command, 'receipt': receipt, 'actor_action': False, 'target_object_precreated': False}


def setup_task(controller, plan):
    if plan['task']['id'] in {case['id'] for case in POINTER_CASES.values()}:
        from scripts.taskviews_pointer_fixture import pointer_setup_command
        from ui_kobe.osworld.runner import checked_execution_result
        command = pointer_setup_command(plan['task'])
        receipt = checked_execution_result(controller.execute_python_command(command))
        return {'command': command, 'receipt': receipt, 'actor_action': False,
                'input_fixture_precreated': True, 'target_answer_precreated': False}
    if plan['task']['id'] in {TEXT_SAVE['id'], TEXT_KEYBOARD_SAVE['id'], TEXT_EDIT_SAVE['id']}:
        from scripts.taskviews_quick_setup import blank_text_setup_command
        from ui_kobe.osworld.runner import checked_execution_result
        input_fixture = plan['task']['id'] == TEXT_EDIT_SAVE['id']
        command = blank_text_setup_command(plan['task']['expected_guest_artifact'], input_fixture=input_fixture)
        receipt = checked_execution_result(controller.execute_python_command(command))
        return {'command': command, 'receipt': receipt, 'actor_action': False,
                'target_file_precreated': input_fixture, 'requested_answer_precreated': False}
    return setup_blank(controller, plan['run_id'])


def restore_quick_actor(manager, actor, source_stage, tag, trace):
    """Keep original tool IDs/history but relocate only new writable storage."""
    from ui_kobe.osworld.checkpoints import Checkpoints
    source = Checkpoints(source_stage, {})
    (trace / 'transitions').mkdir(parents=True, exist_ok=True)
    original_reader = manager.read
    def relocated(checkpoint=None, *, metadata_only=False):
        dest, state = source.read(checkpoint or tag, metadata_only=metadata_only)
        if not metadata_only and state.get('journal'):
            state['journal_directory'] = str(trace / 'transitions')
        return dest, state
    manager.read, manager.resume_tag = relocated, tag
    try:
        return manager.restore_agent(actor)
    finally:
        manager.read = original_reader


def worker(directory):
    group = require_scope(2 * 1024**3)
    import docker
    from desktop_env.controllers.python import PythonController
    from scripts.native_resource_accounting import sample, reserve_ok
    from ui_kobe.osworld.checkpoints import Checkpoints, QMP, ReadAnomaly
    from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
    from ui_kobe.osworld.kimi_native import official_compile
    from ui_kobe.osworld.transitions import TransitionJournal, decision_tools
    from ui_kobe.osworld.runner import checked_execution_result
    from ui_kobe.osworld.quick_checks import grade_saved_point, grade_saved_text
    from ui_kobe.osworld.pointer_checks import grade_pointer_log
    from ui_kobe.osworld import telemetry
    plan = load(directory / 'plan.json')
    verify_source(plan)
    parent = Path(plan['parent_stage'])
    if not os.environ.get('QWEN_API_KEY'):
        raise RuntimeError('WSL QWEN_API_KEY absent; no live request made')
    if parent_files(parent) != plan['parent_files_sha256']:
        raise RuntimeError('Parent files changed; refuse VM mutation')
    if subprocess.check_output(['systemctl', '--user', 'show', plan['parent_unit'],
        '--property=ActiveState', '--value'], text=True).strip() == 'active':
        raise RuntimeError('Parent Agent became active')
    result = {'test_kind': plan['test_kind'], 'started_utc': now(), 'status': 'initializing',
        'official_score': None, 'custom_score': None, 'native_terminal': False,
        'decisions': 0, 'dispatched_commands': 0, 'actual_receipts': 0, 'parent_restored': False,
        'parent_agent_resumed': False, 'parent_reset': False}
    actor = journal = manager = None
    qmp = QMP(Path(plan['vm']['storage']) / 'taskviews.qmp')
    started = time.monotonic()
    cancelled = False
    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with closing(docker.from_env(timeout=15)) as client:
        container = client.containers.get(plan['vm']['container'])
        container.reload()
        if container.labels.get('ui-kobe.osworld.run') != plan['parent_vm_owner_run_id']:
            raise RuntimeError('Preserved VM ownership differs')
        _, boundary = Checkpoints(parent, load(parent / 'manifest.json')).read(
            plan['parent_checkpoint'], metadata_only=True)
        if boundary['vm']['container'] != container.id:
            raise RuntimeError('Parent checkpoint VM identity differs')
        resource_manifest = {'run_id': plan['parent_vm_owner_run_id'], 'cgroup': str(group),
                             'web_container_ids': [], 'web_owned': False}
        def resource_check(startup=False):
            receipt = sample(client, resource_manifest, host_status, group)
            with (directory / 'resources.jsonl').open('a') as stream:
                stream.write(json.dumps({'read_utc': now(), 'startup': startup, **receipt}) + chr(10))
            if cancelled:
                raise ReadAnomaly('Micro-test cancellation requested before dispatch; resource threshold was not the cause')
            if not reserve_ok(receipt['windows'], startup=startup):
                raise ReadAnomaly('Resource reserve below unchanged threshold before dispatch')
        resource_check(startup=True)
        before = qmp.call('query-status')
        if before['running'] or before['status'] != 'paused':
            raise RuntimeError('Parent VM must be paused before a reversible branch')
        blocks = qmp.call('query-block')
        if any(b.get('inserted') and not b['inserted']['ro'] and b['inserted']['drv'] != 'qcow2' for b in blocks):
            raise RuntimeError('Whole-VM rollback requires all writable disks qcow2')
        write(directory / 'rollback-preflight.json', {'time_utc': now(), 'vm': container.id,
            'parent_checkpoint': plan['parent_checkpoint'], 'parent_qmp': before,
            'writable_disks_qcow2': True, 'source_proof_verified': True})
        try:
            controller = PythonController('127.0.0.1', plan['vm']['ports']['server_port'])
            continuation = plan.get('quick_continuation')
            if continuation:
                origin = Path(continuation['stage'])
                prior_dest, prior = Checkpoints(origin, {}).read(continuation['tag'], metadata_only=True)
                if (digest(prior_dest / 'manifest.json') != continuation['manifest_sha256']
                        or prior['vm']['container'] != container.id):
                    raise RuntimeError('Quick continuation checkpoint/VM differs')
                qmp.load(continuation['tag'])
                if plan.get('repair_blank_initialization'):
                    if prior['completed_steps'] or prior['command_count']:
                        raise RuntimeError('Never reinitialize a branch after completed actions')
                    write(directory / 'setup.json', setup_task(controller, plan))
            else:
                qmp.load(plan['parent_checkpoint'])
                write(directory / 'setup.json', setup_task(controller, plan))
                time.sleep(8)
            os.environ.update(UI_KOBE_TELEMETRY_DIR=str(directory / 'telemetry'),
                UI_KOBE_TASK_ID=plan['task']['id'], UI_KOBE_CHECKPOINT_READS='1',
                UI_KOBE_TASKVIEWS_FEEDBACK_V10='1', UI_KOBE_ADVISORY_EFFORT='low')
            os.environ.pop('UI_KOBE_CUA_CONTRACT_JSON', None)
            (directory / 'telemetry').mkdir()
            telemetry._root = directory / 'telemetry'
            actor = QwenTaskViewsNativeAgent(model=plan['model'], base_url=plan['base_url'],
                temperature=0, max_tokens=16000, **plan['cua_contract'],
                stream=False, enable_thinking=False, top_p=0.9)
            journal = actor.execution_journal = TransitionJournal(directory / 'telemetry/transitions',
                task_id=plan['task']['id'], run_id=plan['run_id'], contract=actor.contract)
            manager = Checkpoints(directory / 'stage', {}, qmp=qmp)
            manager.vm = {**plan['vm'], 'worker_pid': os.getpid()}
            instruction = plan['task']['instruction'] + ' Use only the application GUI, without terminal, console or scripting.'
            first_step = 1
            if continuation:
                # Close the unused new journal, then restore the exact saved
                # actor/journal/graph into this independent continuation only.
                journal.close()
                restored = restore_quick_actor(manager, actor, origin, continuation['tag'], directory / 'telemetry')
                journal = actor.execution_journal
                instruction = restored['instruction']
                first_step = restored['completed_steps'] + 1
                write(directory / 'restore-history.json', {'time_utc': now(), 'reset': False,
                    'vm': container.id, 'completed_steps': restored['completed_steps'],
                    'commands': restored['command_count'], 'source_checkpoint': continuation,
                    'source_actor_history_and_tool_ids_preserved': True})
            for step in range(first_step, plan['diagnostic_pause_after_decisions'] + 1):
                resource_check()
                screenshot = controller.get_screenshot()
                if not isinstance(screenshot, bytes):
                    raise ReadAnomaly('No original guest screenshot')
                obs = {'screenshot': screenshot}
                manager.save(actor, instruction, obs)
                journal.begin(instruction, obs, step=step)
                response, commands = actor.predict(instruction, obs)
                if official_compile(actor.last_trace['native_actions'], actor.frame).commands != commands:
                    raise ReadAnomaly('Full commands differ from unchanged official compiler')
                journal.decide(response, commands, step=step, tools=decision_tools(actor))
                result['decisions'] = step
                if commands in (['DONE'], ['FAIL']):
                    journal.phase('native_terminal', original_command=commands[0])
                    result['native_terminal'] = True
                    result['status'] = 'native_done' if commands == ['DONE'] else 'native_fail'
                    break
                for command in commands:
                    resource_check()
                    receipt = None
                    if command == 'WAIT':
                        time.sleep(1)
                    else:
                        receipt = checked_execution_result(controller.execute_python_command(command))
                        result['actual_receipts'] += 1
                    post = controller.get_screenshot()
                    if not isinstance(post, bytes):
                        raise ReadAnomaly('Missing screenshot after actual command')
                    receipts = [receipt] if receipt is not None else []
                    actor.record_execution(command, receipts=receipts)
                    journal.result(command, step=step, observation={'screenshot': post}, receipts=receipts)
                    actor.sync_execution()
                    result['dispatched_commands'] += 1
                print(json.dumps({'time_utc': now(), 'step': step,
                    'commands': len(commands), 'status': 'running'}), flush=True)
                write(directory / 'live-status.json', result)
            if not result['native_terminal']:
                raise ReadAnomaly('20-decision diagnostic boundary reached; no score before native terminal')
            path = plan['task']['expected_guest_artifact']
            probe = checked_execution_result(controller.execute_python_command(
                "from pathlib import Path; import json; p=Path(" + repr(path) +
                "); print(json.dumps({'exists':p.is_file(),'size':p.stat().st_size if p.is_file() else None}))"))
            info = json.loads(probe['output'])
            is_text = plan['task']['id'] in {TEXT_SAVE['id'], TEXT_KEYBOARD_SAVE['id'], TEXT_EDIT_SAVE['id']}
            is_pointer = plan['task']['id'] in {case['id'] for case in POINTER_CASES.values()}
            artifact = directory / ('delivered-pointer.json' if is_pointer else 'delivered.txt' if is_text else 'delivered.ggb')
            if info['exists'] and info['size'] <= 2 * 1024**2:
                body = controller.get_file(path)
                if not isinstance(body, bytes):
                    raise RuntimeError('Terminal artifact download failed')
                artifact.write_bytes(body)
            if is_pointer:
                grade = grade_pointer_log(artifact, plan['task'], terminal=True)
            else:
                grader = grade_saved_text if is_text else grade_saved_point
                grade = grader(artifact, terminal=True)
            write(directory / 'custom-evaluation.json', {'time_utc': now(), 'native_terminal': True,
                'artifact_ref': str(artifact) if artifact.exists() else None,
                'artifact_sha256': digest(artifact) if artifact.exists() else None, **grade})
            result.update(custom_score=grade['custom_score'], checks=grade['checks'])
            if is_pointer:
                result['mouse_metrics'] = grade['mouse_metrics']
        except Exception as error:
            result.update(status='checkpoint_paused', error_type=type(error).__name__, error=str(error)[:1000])
            if manager is not None:
                manager.pause(error)
        finally:
            try:
                if journal is not None:
                    journal.finish_pending('quick branch ended; parent restore required')
                if actor is not None:
                    actor.close()
                if journal is not None:
                    journal.close()
            finally:
                try:
                    result['restored_parent_qmp'] = restore_parent(qmp, plan['parent_checkpoint'])
                    result['parent_files_unchanged'] = parent_files(parent) == plan['parent_files_sha256']
                    result['parent_restored'] = result['parent_files_unchanged']
                except Exception as failure:
                    result.update(parent_restored=False, rollback_error=str(failure)[:1000], needs_human_vm_recovery=True)
                result.update(finished_utc=now(), duration_s=round(time.monotonic() - started, 3))
                write(directory / 'result.json', result)
                print(json.dumps({k: result[k] for k in ('status', 'decisions', 'dispatched_commands',
                    'custom_score', 'official_score', 'parent_restored', 'duration_s')}), flush=True)
    return 0 if result['native_terminal'] and result['custom_score'] == 1 and result['parent_restored'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'launch', 'worker'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--parent-stage', type=Path)
    parser.add_argument('--validation', type=Path)
    parser.add_argument('--provider-confirmed', action='store_true')
    parser.add_argument('--resume-stage', type=Path)
    parser.add_argument('--repair-blank-initialization', action='store_true')
    parser.add_argument('--task-kind', choices=['geogebra', 'text', 'keyboard-text', 'edit-text', *POINTER_CASES], default='geogebra')
    args = parser.parse_args()
    if args.mode == 'prepare':
        if args.parent_stage is None or args.validation is None:
            parser.error('prepare needs --parent-stage and --validation')
        prepare(args.directory, args.parent_stage, args.validation,
                provider_confirmed=args.provider_confirmed, resume_stage=args.resume_stage,
                repair_blank_initialization=args.repair_blank_initialization, task_kind=args.task_kind)
        return 0
    if args.mode == 'launch':
        launch(args.directory)
        return 0
    return worker(args.directory)


if __name__ == '__main__':
    raise SystemExit(main())
