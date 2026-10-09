"""Task059 safe boundaries: whole-VM snapshots plus aligned actor/graph state.

No checkpoint is a claim of task success. Failed branches and API fees remain
append-only audit evidence. Only this local task (no external web effects) can
rewind its desktop. Resume never calls the official task reset.
"""
from __future__ import annotations

import ast
import base64
from copy import deepcopy
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import time
import uuid


class ReadAnomaly(RuntimeError):
    pass


class CheckpointPaused(RuntimeError):
    pass


class StartupRecoveryProbe(RuntimeError):
    pass


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False)
        f.write(chr(10))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


class QMP:
    def __init__(self, path):
        self.path = str(path)

    def call(self, execute, arguments=None):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(180)
            s.connect(self.path)
            with s.makefile('rwb') as f:
                hello = json.loads(f.readline())
                if 'QMP' not in hello:
                    raise RuntimeError('Invalid QMP greeting')
                def request(command, args=None):
                    rid = uuid.uuid4().hex
                    f.write(json.dumps({'execute': command, 'id': rid, **({'arguments': args} if args else {})}).encode()+b'\n')
                    f.flush()
                    while True:
                        line = f.readline(1024*1024)
                        if not line:
                            raise RuntimeError('QMP disconnected')
                        value = json.loads(line)
                        if value.get('id') == rid:
                            if 'error' in value:
                                raise RuntimeError('QMP: ' + str(value['error']))
                            return value['return']
                request('qmp_capabilities')
                return request(execute, arguments)

    def hmp(self, command):
        result = self.call('human-monitor-command', {'command-line': command})
        if result.strip():
            # savevm/loadvm/delvm return an empty string on success. Never
            # commit a checkpoint when QEMU returns an error as plain text.
            raise RuntimeError('QEMU snapshot failed: ' + result[:2000])

    def save(self, tag):
        self.call('stop')
        try:
            self.hmp('savevm ' + tag)
        finally:
            self.call('cont')

    def load(self, tag):
        self.call('stop')
        self.hmp('loadvm ' + tag)
        self.call('cont')


CHECKPOINT_CPU_FLAGS = 'migratable=on,-invtsc'


def configure_snapshot_cpu(environment):
    # The image appends explicit CPU_FLAGS after its automatic host flags.
    # Its default migratable=no,+invtsc blocks savevm in QEMU 9.1.
    # Configure this only before boot; never alter an initialized CPU/guest.
    environment['CPU_FLAGS'] = CHECKPOINT_CPU_FLAGS
    environment['ARGUMENTS'] = '-qmp unix:/storage/taskviews.qmp,server=on,wait=off'


def snapshot_preflight(container, stage):
    container.reload()
    storage = next(m['Source'] for m in container.attrs['Mounts'] if m['Destination'] == '/storage')
    for command in (['chown', f'{os.getuid()}:{os.getgid()}', '/storage/taskviews.qmp'],
                    ['chmod', '600', '/storage/taskviews.qmp']):
        code, _ = container.exec_run(command)
        if code:
            raise RuntimeError('Cannot secure checkpoint preflight socket')
    qmp = QMP(Path(storage)/'taskviews.qmp')
    cpus = qmp.call('query-cpus-fast')
    properties = [{name: qmp.call('qom-get', {'path':cpu['qom-path'], 'property':name})
                   for name in ('migratable','invtsc')} for cpu in cpus]
    if len(properties) != 2 or any(not p['migratable'] or p['invtsc'] for p in properties):
        raise RuntimeError('Checkpoint CPU flags not applied; refuse task initialization')
    tag = 'preflight-'+uuid.uuid4().hex
    qmp.save(tag)
    qmp.load(tag)
    qmp.hmp('delvm '+tag)
    atomic(Path(stage)/'snapshot-preflight.json', {
        'whole_vm_save_load': True, 'container': container.id, 'before_task_reset': True,
        'cpu_flags': CHECKPOINT_CPU_FLAGS, 'cpu_properties': properties,
        'version': qmp.call('query-version'), 'time': time.time()})


ACTOR_FIELDS = ('turns', 'pending', 'last_trace', 'executions', 'command_call_indices',
                'action_descriptions', 'total_steps', 'folded_prefix_count', '_ui_kobe_trace_step')
JOURNAL_FIELDS = ('task_id', 'run_id', 'episode_id', 'current', 'decision', 'task_input', 'position')
ENV_FIELDS = ('_step_no', '_traj_no', 'action_history', 'is_environment_used')


def copy_state(source, target):
    """SQLite backup transactions; stream/copy evidence without holding it in RAM."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=False)
    for path in source.rglob('*'):
        if not path.is_file() or path.name.endswith(('-wal', '-shm', '-journal')):
            continue
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.sqlite':
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as src, sqlite3.connect(dest) as dst:
                src.backup(dst)
        else:
            shutil.copyfile(path, dest)


class Checkpoints:
    def __init__(self, stage, manifest, *, qmp=None):
        self.stage, self.manifest = Path(stage), manifest
        self.root = self.stage / 'checkpoints'
        self.root.mkdir(parents=True, exist_ok=True)
        self.qmp = qmp
        self.env = None
        self.resume_state = None
        self.pause_requested = False
        self.restoring = False
        self.resume_tag = None

    def bind(self, env):
        self.env = env
        c = env.provider.container
        c.reload()
        storage = next(m['Source'] for m in c.attrs['Mounts'] if m['Destination'] == '/storage')
        # QEMU creates this host-mounted socket as root inside the container.
        # Restrict it to the host runner's owner; no guest action is involved.
        for command in (['chown', f'{os.getuid()}:{os.getgid()}', '/storage/taskviews.qmp'],
                        ['chmod', '600', '/storage/taskviews.qmp']):
            code, _ = c.exec_run(command)
            if code:
                raise RuntimeError('Cannot secure checkpoint monitor socket')
        self.qmp = QMP(Path(storage)/'taskviews.qmp')
        self.vm = {'container': c.id, 'storage': storage, 'worker_pid': os.getpid(),
                   'path_to_vm': env.path_to_vm,
                   'ports': {k: getattr(env.provider, k) for k in
                             ('server_port', 'vnc_port', 'chromium_port', 'vlc_port')}}
        atomic(self.stage/'checkpoint-vm.json', self.vm)

    def save(self, agent, instruction, obs):
        agent.flush_execution()
        journal = agent.execution_journal
        if agent.total_steps and journal is None:
            raise ReadAnomaly('Missing execution journal at checkpoint boundary')
        if journal and journal.decision and journal.position != len(journal.decision['commands']):
            raise ReadAnomaly('Checkpoint has an unconfirmed command; refuse continuation')
        tag = 'tv-' + uuid.uuid4().hex
        dest = self.root / tag
        dest.mkdir()
        try:
            # No GUI command is dispatched between this snapshot and state copy.
            self.qmp.save(tag)
            restored_probe = False
            if agent.total_steps == 0:
                # A real save/load round trip before the first API/GUI action.
                # Failure leaves the task paused instead of promising a fake
                # disk-only/agent-only recovery capability.
                self.qmp.load(tag)
                restored_probe = True
            state = {k: deepcopy(getattr(agent, k)) for k in ACTOR_FIELDS}
            state.update(instruction=instruction, observation={k: v for k, v in obs.items() if k != 'screenshot'},
                         screenshot=base64.b64encode(obs['screenshot']).decode(), vm=self.vm,
                         tag=tag, completed_steps=agent.total_steps,
                         environment={k: deepcopy(getattr(self.env, k)) for k in ENV_FIELDS} if self.env else {},
                         generation_profile=agent.profile.__dict__, cua_contract=agent.contract.snapshot())
            if journal is not None:
                with sqlite3.connect(dest/'execution.sqlite') as db:
                    journal.db.backup(db)
                state['journal'] = {k: deepcopy(getattr(journal, k)) for k in JOURNAL_FIELDS}
                state['journal_directory'] = str(journal.directory)
                state['command_count'] = journal.db.execute(
                    "SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='transition'").fetchone()[0]
            else:
                state['command_count'] = 0
            control = agent.control
            if control.memory:
                copy_state(control.directory, dest/'task-memory')
                state['control'] = {'directory': str(control.directory), 'settings': control.settings,
                                    'stage': control.stage, 'last_trace': control.last_trace,
                                    'feedback_gaps': control.feedback_gaps,
                                    'last_verified_resource': control.last_verified_resource,
                                    'verified_after': control.verified_after}
            atomic(dest/'actor.json', state)
            atomic(dest/'environment.json', state['environment'])
            # Auxiliary inspection never materializes the growing actor history.
            atomic(dest/'boundary.json', {k: state[k] for k in
                   ('tag', 'completed_steps', 'command_count', 'vm', 'generation_profile', 'cua_contract')})
            hashes = {str(p.relative_to(dest)): sha(p) for p in dest.rglob('*') if p.is_file()}
            atomic(dest/'manifest.json', {'tag': tag, 'files': hashes, 'completed_steps': agent.total_steps,
                                         'snapshot_scope': 'guest RAM and all writable qcow2 disks',
                                         'live_save_load_probe': restored_probe,
                                         'semantic_success': False, 'time': time.time()})
            atomic(self.root/'latest.json', {'tag': tag, 'manifest_sha256': sha(dest/'manifest.json')})
            # Retain three usable VM snapshots. All small manifests and failed
            # branch events survive; disk pressure cannot grow with 500 turns.
            self.prune(tag)
        except BaseException:
            atomic(dest/'incomplete.json', {'usable': False, 'time': time.time()})
            raise
        return tag

    def prune(self, current):
        committed = sorted((p for p in self.root.iterdir() if p.is_dir() and (p/'manifest.json').exists()
                            and not (p/'expired.json').exists()), key=lambda p: p.stat().st_mtime)
        for old in committed[:-3]:
            if old.name == current:
                continue
            self.qmp.hmp('delvm ' + old.name)
            atomic(old/'expired.json', {'usable': False, 'reason': 'three-checkpoint retention', 'time': time.time()})
            # Keep manifest/hash, remove only copied checkpoint payload within
            # this manager's root, never original telemetry/memory/evidence.
            if old.parent.resolve() != self.root.resolve():
                raise RuntimeError('Checkpoint deletion escaped root')
            for child in old.iterdir():
                if child.name not in ('manifest.json', 'expired.json'):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

    def read(self, tag=None, *, metadata_only=False):
        latest = json.loads((self.root/'latest.json').read_text())
        tag = tag or latest['tag']
        if not tag.startswith('tv-') or len(tag) != 35 or not all(c in '0123456789abcdef' for c in tag[3:]):
            raise ValueError('Invalid checkpoint identity')
        dest = self.root/tag
        if (dest/'expired.json').exists():
            raise ValueError('Checkpoint snapshot expired')
        if tag == latest['tag'] and sha(dest/'manifest.json') != latest['manifest_sha256']:
            raise ValueError('Checkpoint manifest hash mismatch')
        manifest = json.loads((dest/'manifest.json').read_text())
        for rel, expected in manifest['files'].items():
            path = dest/rel
            if not path.resolve().is_relative_to(dest.resolve()) or sha(path) != expected:
                raise ValueError('Checkpoint file hash mismatch: '+rel)
        return dest, json.loads((dest/('boundary.json' if metadata_only else 'actor.json')).read_text())

    def restore_agent(self, agent):
        dest, state = self.read(self.resume_tag)
        if state['generation_profile'] != agent.profile.__dict__ or state['cua_contract'] != agent.contract.snapshot():
            raise ValueError('Checkpoint actor contract changed')
        for key in ACTOR_FIELDS:
            setattr(agent, key, state[key])
        if state.get('journal'):
            from .transitions import TransitionJournal
            journal = TransitionJournal.__new__(TransitionJournal)
            for k, value in state['journal'].items():
                setattr(journal, k, value)
            journal.directory = Path(state['journal_directory'])
            journal.path = journal.directory/(journal.episode_id+'-resume-'+uuid.uuid4().hex+'.sqlite')
            shutil.copyfile(dest/'execution.sqlite', journal.path)
            journal.db = sqlite3.connect(journal.path)
            journal.contract = agent.contract
            journal.closed = journal.read_only = False
            agent.execution_journal = journal
            journal.append('checkpoint_resume', checkpoint=state['tag'], original_episode=journal.episode_id)
        if state.get('control'):
            from .task_control import PersistentTaskControl
            data = state['control']
            directory = self.stage/'working-memory'/uuid.uuid4().hex
            copy_state(dest/'task-memory', directory)
            settings = {**data['settings'], 'memory_dir': str(directory)}
            agent.control.close()
            agent.control = PersistentTaskControl(settings, context_bytes=agent.contract.taskviews_context_bytes)
            agent.control.compact_core = True
            agent.control.initialize(state['instruction'])
            for k in ('stage','last_trace','feedback_gaps','last_verified_resource','verified_after'):
                setattr(agent.control, k, data[k])
            agent.modules = None
            agent.sync_execution()
        self.resume_state = state
        return state

    def pause(self, exc):
        # Mark preservation before monitor I/O: a broken QMP connection must
        # not let env.close/ExecStopPost delete the recovery overlay.
        self.pause_requested = True
        monitor_error = None
        if self.qmp:
            try:
                self.qmp.call('stop')
            except Exception as failure:
                monitor_error = str(failure)[:2000]
        latest = json.loads((self.root/'latest.json').read_text()) if (self.root/'latest.json').exists() else None
        record = {'status': 'paused', 'checkpoint': latest, 'error_type': type(exc).__name__,
               'error': str(exc)[:2000], 'time': time.time(), 'score': None,
               'next_action': 'inspect failed read; validate repair; resume this checkpoint; never reset'}
        if monitor_error:
            record['hypervisor_pause_error'] = monitor_error
        import httpx
        from ui_kobe.api.kimi_stream import retry_after_seconds
        cause = exc
        for _ in range(8):
            if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 429:
                delay = retry_after_seconds(cause.response.headers.get('retry-after'))
                record['retry_not_before'] = time.time()+max(60, delay if delay is not None else 60)
                break
            cause = cause.__cause__
            if cause is None:
                break
        atomic(self.stage/'pause-history'/(uuid.uuid4().hex+'.json'), record)
        atomic(self.stage/'paused.json', record)


def resume_loop(function):
    """Keep the pinned official loop; change only its two resume counters."""
    tree = ast.parse(inspect.getsource(function))
    changed = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('step_idx', 'global_action_index') and isinstance(node.value, ast.Constant) and node.value.value == 0:
                node.value = ast.parse('getattr(agent, "_resume_'+name+'", 0)', mode='eval').body
                changed.append(name)
    if sorted(changed) != ['global_action_index', 'step_idx']:
        raise RuntimeError('Pinned official loop counters changed; refuse unsafe resume')
    namespace = dict(function.__globals__)
    exec(compile(ast.fix_missing_locations(tree), '<official-loop-with-resume-counters>', 'exec'), namespace)
    return namespace[function.__name__]


def install(stage, manifest):
    if manifest['task_id'] != '059' or manifest['arm'] != 'taskviews':
        raise ValueError('Desktop rewind currently supports only isolated Task059 TaskViews')
    from desktop_env.desktop_env import DesktopEnv
    from desktop_env.providers.docker import provider
    from desktop_env.providers.docker import local_budget
    from .kimi_taskviews_native import KimiTaskViewsNativeAgent
    import lib_run_single
    manager = Checkpoints(stage, manifest)
    # The existing guard shares the same adjusted reserve formula. It requests
    # a safe checkpoint pause instead of destroying the only resumable desktop.
    def watch(container, event):
        failures = 0
        while not event.wait(15):
            try:
                container.reload()
                if container.status != 'running':
                    return
                status = local_budget.host_status()
                failures = 0
                if status['available_ram_gib'] >= 4 and status['c_free_gib'] >= 35 and status['d_free_gib'] >= 10:
                    continue
                reason = 'VM guard adjusted reserve below runtime threshold'
            except Exception:
                failures += 1
                if failures < 3:
                    continue
                reason = 'VM resource monitoring unavailable after three attempts'
            atomic(Path(stage)/'pause-request.json', {'reason': reason, 'time': time.time()})
            if manager.env:
                os.kill(os.getpid(), signal.SIGUSR1)
            return
    local_budget.watch = watch
    resuming = (Path(stage)/'resume-request.json').exists()
    if resuming:
        manager.resume_tag = json.loads((Path(stage)/'resume-request.json').read_text())['checkpoint']
        vm = json.loads((Path(stage)/'checkpoint-vm.json').read_text())
        manager.qmp = QMP(Path(vm['storage'])/'taskviews.qmp')
    old_start = provider.DockerProvider.start_emulator
    def start(self, path_to_vm, headless, os_type):
        if resuming:
            vm = json.loads((Path(stage)/'checkpoint-vm.json').read_text())
            self.container = self.client.containers.get(vm['container'])
            self.container.reload()
            if path_to_vm != vm['path_to_vm']:
                raise RuntimeError('Preserved VM missing or base disk changed; no fresh VM allowed')
            for key, value in vm['ports'].items():
                setattr(self, key, value)
            self.container._osworld_storage = Path(vm['storage']).parent
            if self.container.status == 'exited':
                self.container.start()
                self._wait_for_vm_ready()
            elif self.container.status != 'running':
                raise RuntimeError('Preserved VM is not resumable')
            import threading
            event = threading.Event()
            local_budget.STOP_EVENTS[self.container.id] = event
            threading.Thread(target=watch, args=(self.container, event), daemon=True).start()
            return
        configure_snapshot_cpu(self.environment)
        result = old_start(self, path_to_vm, headless, os_type)
        snapshot_preflight(self.container, stage)
        return result
    provider.DockerProvider.start_emulator = start
    old_reset = DesktopEnv.reset
    def reset(env, *args, **kwargs):
        if resuming:
            try:
                env._set_task_info(kwargs['task_config'])
                manager.bind(env)
                dest, state = manager.read(manager.resume_tag, metadata_only=True)
                manager.qmp.load(state['tag'])
                for key, value in json.loads((dest/'environment.json').read_text()).items():
                    setattr(env, key, value)
                result = env._get_obs()
                atomic(Path(stage)/'restore-history'/(uuid.uuid4().hex+'.json'), {
                    'checkpoint': state['tag'], 'completed_steps': state['completed_steps'],
                    'vm_id': state['vm']['container'], 'reset': False, 'time': time.time()})
                (Path(stage)/'paused.json').unlink(missing_ok=True)
                return result
            except Exception as exc:
                manager.pause(exc)
                raise CheckpointPaused('Desktop checkpoint restore failed; preserved for inspection') from exc
        result = old_reset(env, *args, **kwargs)
        manager.bind(env)
        return result
    DesktopEnv.reset = reset
    old_close = DesktopEnv.close
    def close(env):
        if manager.pause_requested:
            return  # supervisor preserves this owned VM and snapshot directory
        return old_close(env)
    DesktopEnv.close = close
    old_agent_reset = KimiTaskViewsNativeAgent.reset
    def agent_reset(agent, *args, **kwargs):
        if resuming and agent.control is not None and not getattr(agent, '_checkpoint_restored', False):
            try:
                state = manager.restore_agent(agent)
            except Exception as exc:
                manager.pause(exc)
                raise CheckpointPaused('Checkpoint restore failed; preserved for inspection') from exc
            agent._resume_step_idx = state['completed_steps']
            agent._resume_global_action_index = state['command_count']
            agent._checkpoint_restored = True
            return
        return old_agent_reset(agent, *args, **kwargs)
    KimiTaskViewsNativeAgent.reset = agent_reset
    old_predict = KimiTaskViewsNativeAgent.predict
    @functools.wraps(old_predict)
    def predict(agent, instruction, obs):
        try:
            if manager.pause_requested or (Path(stage)/'pause-request.json').exists():
                raise ReadAnomaly('Resource or inspection pause requested')
            tag = manager.save(agent, instruction, obs)
            probe = Path(stage)/'startup-recovery-probe.json'
            if (manifest.get('checkpoint_policy', {}).get('startup_resume_probe')
                    and agent.total_steps == 0 and not probe.exists()):
                atomic(probe, {'checkpoint': tag, 'completed_steps': 0, 'api_actions_before_probe': 0,
                               'purpose': 'verify full process continuation before inference', 'time': time.time()})
                raise StartupRecoveryProbe('Initial checkpoint committed; verify same-VM process resume before inference')
            return old_predict(agent, instruction, obs)
        except Exception as exc:
            manager.pause(exc)
            raise CheckpointPaused(str(exc)) from exc
    KimiTaskViewsNativeAgent.predict = predict
    def interrupt(signum, frame):
        exc = ReadAnomaly('Supervisor resource threshold pause')
        manager.pause(exc)
        raise CheckpointPaused(str(exc))
    signal.signal(signal.SIGUSR1, interrupt)
    official_source = inspect.getsourcefile(lib_run_single.run_single_example)
    lib_run_single.run_single_example = resume_loop(lib_run_single.run_single_example)
    atomic(Path(stage)/'runner-checkpoint-contract.json', {
        'official_function': 'lib_run_single.run_single_example',
        'official_source_sha256': sha(official_source),
        'changed_assignments': ['step_idx = saved completed steps', 'global_action_index = saved commands'],
        'reset_on_resume': False, 'official_loop_body_preserved': True, 'resuming': resuming})
    return manager
