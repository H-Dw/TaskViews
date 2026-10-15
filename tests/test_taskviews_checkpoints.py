from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from kobe_views.task_memory import TaskMemory
from ui_kobe.api.kimi import generation_profile
from ui_kobe.api.kimi_stream import KimiStreamClient, RateLimitDeferred, retry_after_seconds
from ui_kobe.osworld.checkpoints import ACTOR_FIELDS, Checkpoints, configure_snapshot_cpu, resume_loop
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.task_control import PersistentTaskControl
from ui_kobe.osworld.transitions import TransitionJournal
from ui_kobe.osworld import checkpoints


@pytest.mark.parametrize('status', ['exited', 'dead', 'created', 'paused', 'restarting', 'removing'])
def test_resume_never_reboots_a_stopped_container(status):
    calls = []
    container = SimpleNamespace(id='full-owned-id', status=status,
        labels={'ui-kobe.osworld.run': 'original-run'}, reload=lambda: calls.append('reload'),
        start=lambda: pytest.fail('Container entrypoint would overwrite the checkpoint disk'))
    vm = {'container': 'full-owned-id', 'path_to_vm': '/original/base.qcow2'}
    with pytest.raises(checkpoints.ReadAnomaly, match='restarting may overwrite'):
        checkpoints.require_running_checkpoint_container(container, vm, vm['path_to_vm'], 'original-run')
    assert calls == ['reload']


@pytest.mark.parametrize('changed', ['id', 'path', 'owner', None])
def test_resume_checks_live_container_full_identity_base_and_owner(changed):
    container = SimpleNamespace(id='different' if changed == 'id' else 'full-owned-id', status='running',
        labels={'ui-kobe.osworld.run': 'different' if changed == 'owner' else 'original-run'},
        reload=lambda: None, start=lambda: pytest.fail('A live guest needs no reboot'))
    vm = {'container': 'full-owned-id', 'path_to_vm': '/original/base.qcow2'}
    path = '/different/base.qcow2' if changed == 'path' else vm['path_to_vm']
    if changed:
        with pytest.raises(checkpoints.ReadAnomaly):
            checkpoints.require_running_checkpoint_container(container, vm, path, 'original-run')
    else:
        checkpoints.require_running_checkpoint_container(container, vm, path, 'original-run')


@pytest.mark.parametrize('problem', ['missing-boot-tag', 'missing-firmware-tag', 'raw-disk', 'no-writable-disk', None])
def test_whole_vm_load_checks_all_writable_snapshot_tags_before_resume(problem):
    calls = []
    blocks = [{'device': name, 'inserted': {'ro': False, 'drv': 'qcow2',
        'image': {'snapshots': [{'name': 'safe-tag'}]}}} for name in ('boot', 'firmware')]
    if problem == 'missing-boot-tag':
        blocks[0]['inserted']['image'] = {}  # Valid actor hashes do not restore a recreated disk.
    elif problem == 'missing-firmware-tag':
        blocks[1]['inserted']['image']['snapshots'] = [{'name': 'different-tag'}]
    elif problem == 'raw-disk':
        blocks[0]['inserted']['drv'] = 'raw'
    elif problem == 'no-writable-disk':
        blocks = []
    blocks += [{'device': 'immutable-base', 'inserted': {'ro': True, 'drv': 'qcow2', 'image': {}}},
               {'device': 'empty-cd'}]
    monitor = checkpoints.QMP('/unused/socket')
    def call(operation, arguments=None):
        calls.append(operation)
        return deepcopy(blocks) if operation == 'query-block' else ''
    monitor.call = call
    if problem:
        with pytest.raises(checkpoints.ReadAnomaly, match='checkpoint disks|snapshot unavailable'):
            monitor.load('safe-tag')
        assert calls == ['query-block']  # No loadvm, CPU resume or GUI action.
    else:
        monitor.load('safe-tag')
        assert calls == ['query-block', 'stop', 'human-monitor-command', 'cont']


@pytest.mark.parametrize('state', ['inactive','unknown','failed','active'])
def test_resume_handles_systemd_unloaded_and_failed_units(monkeypatch, state):
    from scripts import taskviews_recovery
    calls = []
    def run(command, **kwargs):
        calls.append(command[2])
        return SimpleNamespace(stdout=state, returncode=0)
    monkeypatch.setattr(taskviews_recovery.subprocess, 'run', run)
    if state == 'active':
        with pytest.raises(RuntimeError, match='became active'):
            taskviews_recovery.restart_checkpoint_unit('owned.service')
        assert 'start' not in calls
    else:
        taskviews_recovery.restart_checkpoint_unit('owned.service')
        assert ('reset-failed' in calls) == (state == 'failed')
        assert calls[-1] == 'start'


def test_resume_does_not_expand_or_contact_paused_guest_before_loadvm():
    calls = []
    def original(env): calls.append(env)
    checkpoints.checkpoint_volume_finalizer(original, True)('paused-saved-vm')
    assert calls == []
    checkpoints.checkpoint_volume_finalizer(original, False)('fresh-vm')
    assert calls == ['fresh-vm']


class VM:
    def __init__(self):
        self.calls = []
        self.fail = False

    def save(self, tag):
        if self.fail:
            raise RuntimeError('snapshot failed')
        self.calls.append(('save', tag))

    def hmp(self, command):
        self.calls.append(('hmp', command))

    def load(self, tag):
        self.calls.append(('load', tag))

    def call(self, command):
        self.calls.append(('call', command))


def agent_at_boundary(tmp_path):
    actor = SimpleNamespace(**{k: [] for k in ACTOR_FIELDS})
    actor.total_steps = actor._ui_kobe_trace_step = 17
    actor.folded_prefix_count = 0
    actor.pending = ['native-call-17']
    actor.turns = [[{'role': 'assistant', 'reasoning_content': 'original reasoning',
                    'tool_calls': [{'id': 'native-call-17'}]}]]
    actor.last_trace = {}
    actor.contract = CUAContract()
    actor.profile = generation_profile('max-16k')
    actor.control = PersistentTaskControl({'enabled':True,'memory_dir':str(tmp_path/'memory'),
                                         'task_id':'task059'}, context_bytes=32000)
    actor.control.compact_core = True
    actor.control.initialize('Original user goal')
    actor.execution_journal = TransitionJournal(tmp_path/'execution',task_id='059',run_id='new-v8',contract=actor.contract)
    actor.modules = None
    actor.flush_execution = lambda: None
    actor.sync_execution = lambda: None
    return actor


def test_restore_keeps_original_tool_ids_steps_graph_and_failed_branch(tmp_path):
    vm = VM()
    manager = Checkpoints(tmp_path/'stage', {}, qmp=vm)
    manager.vm = {'container': 'full-owned-id'}
    agent = agent_at_boundary(tmp_path)
    before = deepcopy(agent.turns)
    tag = manager.save(agent, 'Original user goal', {'screenshot':b'raw-input'})
    original_db = agent.execution_journal.path
    agent.execution_journal.append('bad_read', error='unknown selector')
    agent.total_steps = 18
    agent.turns.append([{'role':'assistant','content':'failed branch'}])
    manager.pause(ValueError('bad read'))
    restored = agent_at_boundary(tmp_path/'second')
    saved = manager.restore_agent(restored)
    assert saved['tag'] == tag
    assert restored.total_steps == 17 and restored.pending == ['native-call-17']
    assert restored.turns == before
    assert restored.execution_journal.path != original_db
    assert 'bad_read' not in [e['kind'] for e in restored.execution_journal.read()]
    with TransitionJournal.open_readonly(original_db).db as db:
        assert db.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='bad_read'").fetchone()[0] == 1
    assert restored.control._core()['facts'][0]['value'] == 'Original user goal'
    assert json.loads((manager.stage/'paused.json').read_text())['score'] is None
    agent.control.close()
    restored.control.close()


def test_checkpoint_fails_closed_on_corruption_and_incomplete_vm_save(tmp_path):
    vm = VM()
    manager = Checkpoints(tmp_path/'stage', {}, qmp=vm)
    manager.vm = {}
    agent = agent_at_boundary(tmp_path)
    tag = manager.save(agent, 'Original user goal', {'screenshot':b'screen'})
    latest = (manager.root/'latest.json').read_bytes()
    vm.fail = True
    with pytest.raises(RuntimeError, match='snapshot failed'):
        manager.save(agent, 'Original user goal', {'screenshot':b'screen'})
    assert (manager.root/'latest.json').read_bytes() == latest
    (manager.root/tag/'actor.json').write_text('{}')
    with pytest.raises(ValueError, match='hash mismatch'):
        manager.read()
    with pytest.raises(ValueError, match='hash mismatch'):
        manager.read(metadata_only=True)
    agent.control.close()


def test_checkpoint_retains_three_and_does_not_delete_original_evidence(tmp_path):
    import os

    manager = Checkpoints(tmp_path/'stage', {}, qmp=VM())
    manager.vm = {}
    agent = agent_at_boundary(tmp_path)
    tags = []
    for index in range(4):
        tag = manager.save(agent, 'Original user goal', {'screenshot':b's'})
        tags.append(tag)
        # Model strictly successive snapshots even on filesystems with coarse mtimes.
        os.utime(manager.root / tag, (index + 1, index + 1))
    assert (manager.root/tags[0]/'expired.json').exists()
    assert not (manager.root/tags[0]/'actor.json').exists()
    assert agent.execution_journal.path.exists()
    assert len([p for p in manager.root.iterdir() if p.is_dir() and (p/'actor.json').exists()]) == 3
    agent.control.close()


def official_like_loop(agent):
    step_idx = 0
    global_action_index = 0
    while step_idx < 500:
        agent.calls += 1
        step_idx += 1
        global_action_index += 1
    return step_idx, global_action_index


def test_resume_preserves_cumulative_official_limit_instead_of_500_new_steps():
    agent = SimpleNamespace(_resume_step_idx=498,_resume_global_action_index=800,calls=0)
    assert resume_loop(official_like_loop)(agent) == (500,802)
    assert agent.calls == 2


def test_auxiliary_metadata_read_never_materializes_actor_history(tmp_path, monkeypatch):
    from pathlib import Path
    manager = Checkpoints(tmp_path/'stage', {}, qmp=VM())
    manager.vm = {'container': 'owned'}
    agent = agent_at_boundary(tmp_path)
    manager.save(agent, 'Original goal', {'screenshot':b's'})
    original = Path.read_text
    def bounded_read(path, *args, **kwargs):
        assert path.name != 'actor.json'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', bounded_read)
    _, boundary = manager.read(metadata_only=True)
    assert boundary['completed_steps'] == 17 and 'turns' not in boundary
    agent.control.close()


def test_monitor_failure_still_preserves_pause_and_checkpoint(tmp_path):
    class BrokenMonitor(VM):
        def call(self, command):
            raise RuntimeError('monitor disconnected')
    manager = Checkpoints(tmp_path/'stage', {}, qmp=BrokenMonitor())
    manager.pause(ValueError('read rejected'))
    record = json.loads((manager.stage/'paused.json').read_text())
    assert manager.pause_requested
    assert record['hypervisor_pause_error'] == 'monitor disconnected'
    assert record['score'] is None and record['checkpoint'] is None


def test_resume_output_is_separate_so_official_filter_cannot_delete_failed_branch(tmp_path):
    from scripts.taskviews_recovery import continuation_output
    from scripts.osworld_native_experiment import official_arguments
    original = tmp_path/'results'/'qwen'
    failed = original/'computer_13'/'screenshot'/'kimi-k3'/'tasks'/'059'
    failed.mkdir(parents=True)
    (failed/'traj.jsonl').write_text('original failed branch')
    manifest = {'official_results': str(original), 'official_arguments': official_arguments('059',original)}
    before = list(manifest['official_arguments'])
    output = continuation_output(manifest, 'resume-one')
    assert output != original and not output.exists()
    assert not output.is_relative_to(original)
    assert (failed/'traj.jsonl').read_text() == 'original failed branch'
    for index, item in enumerate(before):
        if index and before[index-1] in ('--result_dir','--cache_dir'):
            continue
        assert manifest['official_arguments'][index] == item
    second = continuation_output(manifest, 'resume-two')
    assert manifest['result_segments'] == [str(original),str(output),str(second)]


def test_snapshot_cpu_is_declared_before_boot_without_changing_resource_limits():
    environment = {'RAM_SIZE':'2G','CPU_CORES':'2','DISK_SIZE':'32G'}
    configure_snapshot_cpu(environment)
    assert environment['CPU_FLAGS'] == 'migratable=on,-invtsc'
    assert environment['RAM_SIZE'] == '2G' and environment['CPU_CORES'] == '2'
    assert '-qmp' in environment['ARGUMENTS']


@pytest.mark.parametrize('firmware_format', ['raw', 'qcow2'])
def test_preflight_covers_writable_firmware_before_task_reset(tmp_path, monkeypatch, firmware_format):
    calls = []
    class Probe:
        def __init__(self, path): pass
        def call(self, name, args=None):
            if name == 'query-cpus-fast':
                return [{'qom-path':'cpu0'}, {'qom-path':'cpu1'}]
            if name == 'qom-get':
                return args['property'] == 'migratable'
            if name == 'query-block':
                return [{'device':'pflash0','inserted':{'ro':False,'drv':firmware_format}}]
            return {'qemu':{'major':9,'minor':1}}
        def save(self, tag): calls.append('save')
        def load(self, tag): calls.append('load')
        def hmp(self, command): calls.append('delete')
    monkeypatch.setattr(checkpoints, 'QMP', Probe)
    container = SimpleNamespace(id='original-vm', attrs={'Mounts':[{'Source':str(tmp_path),'Destination':'/storage'}]},
                                reload=lambda:None, exec_run=lambda command:(0,b''))
    if firmware_format == 'raw':
        with pytest.raises(RuntimeError, match='not qcow2'):
            checkpoints.snapshot_preflight(container, tmp_path)
        assert calls == []
    else:
        checkpoints.snapshot_preflight(container, tmp_path)
        assert calls == ['save','load','delete']
    record = json.loads((tmp_path/'snapshot-preflight.json').read_text())
    assert record['whole_vm_save_load'] == (firmware_format == 'qcow2')
    assert record['before_task_reset'] and record['container'] == 'original-vm'


def test_checkpoint_entrypoint_refuses_second_boot_before_destructive_entry(tmp_path):
    import subprocess
    from ui_kobe.osworld.checkpoints import SNAPSHOT_FIRMWARE_BOOT
    prefix = SNAPSHOT_FIRMWARE_BOOT.split('flash=')[0].replace('/storage/', str(tmp_path)+'/')
    script = prefix + "printf '%s' 'would-enter-original-image'"
    first = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
    assert first.returncode == 0 and first.stdout == 'would-enter-original-image'
    second = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
    assert second.returncode == 78 and not second.stdout
    assert 'recreates boot disk' in second.stderr


def test_execution_history_does_not_displace_original_task_contract(tmp_path):
    memory = TaskMemory('t',tmp_path)
    memory.initialize('Original goal')
    memory.observe('f',b's',{'summary':'visible','elements':[]})
    for n in range(20):
        memory.append_action_semantics({'type':'type','text':'old-'+str(n)},frame_id='f')
    core = memory.core_packet(8000,contract_only=True)
    assert all(f['grade'] == 'task_contract' for f in core['facts'])
    assert any(f['category']=='goal' and f['value']=='Original goal' for f in core['facts'])
    assert not any(g.get('code')=='core_budget_exceeded' for g in core['gaps'])
    memory.close()


def test_429_captures_bounded_redacted_body_and_honors_provider_wait(monkeypatch):
    events, sleeps = [], []
    monkeypatch.setattr('ui_kobe.api.kimi_stream.time.sleep',sleeps.append)
    def handler(request):
        return httpx.Response(429,headers={'retry-after':'120','authorization':'secret-hidden'},
                              text='quota detail test-key')
    c = KimiStreamClient(api_key='test-key',http_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),**kw),
                         emit=lambda event,**fields:events.append((event,fields)))
    with pytest.raises(httpx.HTTPStatusError):
        c.create(messages=[],max_completion_tokens=16000)
    assert sleeps == [120]
    bodies = [f['body'] for e,f in events if e=='http_error_body']
    assert bodies == ['quota detail [REDACTED]']*2
    assert 'secret-hidden' not in str(events)
    assert sum(e=='request_outcome' and f['usage'] is None for e,f in events) == 2


def test_429_defers_without_exceeding_role_deadline():
    import time
    def handler(request):
        return httpx.Response(429,headers={'retry-after':'3600'},text='rate limited')
    c=KimiStreamClient(api_key='offline',http_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(RateLimitDeferred):
        c.create(deadline=time.monotonic()+10,messages=[],max_completion_tokens=16000)
    assert retry_after_seconds('-1') is None
    assert retry_after_seconds('nonsense') is None


def test_billing_quota_429_pauses_without_retry_and_redacts_escaped_ids(monkeypatch):
    from ui_kobe.api.kimi_stream import ProviderQuotaBlocked
    from scripts.taskviews_recovery import require_provider_recovery
    events, calls = [], []
    monkeypatch.setattr('ui_kobe.api.kimi_stream.time.sleep', lambda seconds:pytest.fail('Billing error must not sleep/retry'))
    def handler(request):
        calls.append(request)
        return httpx.Response(429, text='{"error":{"type":"exceeded_current_quota_error","message":"org-private \\u003cak-private\\u003e insufficient balance"}}')
    c=KimiStreamClient(api_key='offline',http_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),**kw),
                       emit=lambda event,**fields:events.append((event,fields)))
    with pytest.raises(ProviderQuotaBlocked):
        c.create(messages=[],max_completion_tokens=16000)
    assert len(calls)==1
    assert 'ak-private' not in str(events) and 'org-private' not in str(events)
    assert sum(e=='request_outcome' and f['usage'] is None for e,f in events)==1
    assert require_provider_recovery is not None


def test_account_block_requires_explicit_recovery_before_resuming(tmp_path):
    from scripts.taskviews_recovery import require_provider_recovery
    (tmp_path/'provider-access-block.json').write_text('{}')
    with pytest.raises(RuntimeError, match='user must confirm'):
        require_provider_recovery(tmp_path,False)
    require_provider_recovery(tmp_path,True)


def test_invalid_view_read_stops_before_any_actor_or_command(tmp_path, monkeypatch):
    from test_cua_contract import build_agent, png
    from test_native_task_experiment import Transport, response
    from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
    from ui_kobe.osworld.checkpoints import ReadAnomaly
    class InvalidRead(Transport):
        def create(self, **kwargs):
            result = super().create(**kwargs)
            if 'You are the task controller' in kwargs['messages'][0]['content']:
                bad = {'stage':'s','needs':[{'id':'n','consumer':'executor','purpose':'read',
                       'anchors':['invented-module-id'], 'focus_predicates':['*'], 'max_hops':0}]}
                return response({'content':json.dumps(bad)})
            return result
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS','1')
    agent = build_agent(KimiTaskViewsNativeAgent,monkeypatch,tmp_path)
    wire = InvalidRead()
    agent.transport = agent.client.transport = wire
    try:
        with pytest.raises(ReadAnomaly, match='Unknown semantic anchor'):
            agent.predict('original goal',{'screenshot':png()})
        assert wire.actor == 0
        assert all(not r.get('tools') for r in wire.requests)
        assert len(wire.requests) == 4  # perception, bounded controller repairs
        table = json.loads(wire.requests[1]['messages'][-1]['content'][0]['text'])['role_evidence']['consumer_allowed_anchors']
        assert 'task' in table['executor']['anchors']
    finally:
        agent.close()


def test_positive_context_budget_with_growing_execution_history(tmp_path, monkeypatch):
    from test_cua_contract import build_agent, png
    from test_native_task_experiment import Transport
    from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS','1')
    agent = build_agent(KimiTaskViewsNativeAgent,monkeypatch,tmp_path)
    wire = Transport()
    agent.transport = agent.client.transport = wire
    try:
        agent.control.initialize('original goal')
        agent.control.memory.observe('old',b's',{'summary':'visible','elements':[]})
        for n in range(60):
            agent.control.memory.append_action_semantics({'type':'type','text':'history-'+str(n)},frame_id='old')
        agent.predict('original goal',{'screenshot':png()})
        assert wire.actor == 1
        assert 'assigned_views' in agent.view_trace['executor_context']
        assert len(json.dumps(agent.view_trace['executor_context']).encode()) <= 32000
        assert agent.view_trace['dispatch']['budget_bytes'] > 0
    finally:
        agent.close()
