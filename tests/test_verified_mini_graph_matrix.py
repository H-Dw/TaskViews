"""Serial execution, bounded repair allowance and comparable rerun cohorts."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import verified_mini_graph_matrix as campaign
from scripts import verified_invoice as pair
from ui_kobe.osworld import verified_serial


@pytest.fixture(autouse=True)
def isolated_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(verified_serial, 'LOCK', tmp_path / 'host-eval.lock')
    monkeypatch.delenv(verified_serial.FD_ENV, raising=False)
    monkeypatch.setenv('SX_URL_SB', 'https://offline.example/v1')


def scaffold(root, monkeypatch):
    root.mkdir()
    source = {'ui_kobe/actor.py': 'old'}
    monkeypatch.setattr(pair, 'project_identity', lambda: dict(source))
    config = dict(version=campaign.VERSION, slots=campaign.slots(), repair_limit=10,
                  inspection_minutes=40, provider='sx', model='qwen3.8-max', reasoning=['high', 'low'],
                  arms=['taskviews'], max_steps=40, keyboard_research=False)
    campaign.sealed(root / 'matrix.json', config)
    campaign.write(root / 'repair-ledger.json', {'limit': 10, 'used': 0, 'attempts': []})
    entries = []
    for slot in campaign.slots():
        folder = root / 'revisions/r000/cells' / slot['id']
        plan = pair.specification('sx', 'SX_URL_SB', 'relative',
                                  f"sx-mini-max-{slot['reasoning']}40", slot['task'],
                                  mini_graph_mode=slot['mode'])
        plan['project_source'] = dict(source)
        plan['run_ids'] = {'taskviews': slot['id']}
        campaign.write(folder / 'plan.json', plan)
        campaign.write(folder / 'state.json', {'status': 'prepared_not_started'})
        entries.append(dict(slot=slot, plan=str(folder.relative_to(root)), revision='r000',
                            behavior_sha256=campaign.digest(campaign.behavior_identity(source)),
                            plan_sha256=pair.sha(folder / 'plan.json')))
    campaign.sealed(root / 'revisions/r000/queue.json', {'entries': entries})
    campaign.write(root / 'state.json', dict(status='prepared_not_started', queue='revisions/r000/queue.json'))
    campaign.write(root / 'preflight.json', dict(ready=True, project_source=dict(source),
        queue_sha256=pair.sha(root / 'revisions/r000/queue.json')))
    return entries, source


def complete(folder, score=0):
    campaign.write(folder / 'state.json', {'status': 'completed'})
    campaign.write(folder / 'cleanup-taskviews.json', {'cleanup_ok': True})
    campaign.write(folder / 'taskviews/outcome.json', dict(complete=True, closed=True, cleanup_ok=True,
        source_unchanged=True, official_score=score, decisions=40))


def test_schedule_has_eighteen_unique_cells_and_balances_mode_positions():
    slots = campaign.slots()
    assert len(slots) == len({s['id'] for s in slots}) == 18
    for task in campaign.TASK_ORDER:
        subset = [s for s in slots if s['task'] == task]
        assert {(s['mode'], s['reasoning']) for s in subset} == {
            (m, e) for m in campaign.MODES for e in campaign.EFFORTS}
        assert all(subset[i]['mode'] == subset[i + 1]['mode'] for i in (0, 2, 4))
    for mode in campaign.MODES:
        assert sorted(next(i // 2 for i, s in enumerate([s for s in slots if s['task'] == task])
                           if s['mode'] == mode) for task in campaign.TASK_ORDER) == [0, 1, 2]


@pytest.mark.parametrize('task', campaign.TASK_ORDER)
@pytest.mark.parametrize('mode', campaign.MODES)
def test_low_uses_same_max_model_and_budgets_without_baseline(task, mode):
    plans = [pair.specification('sx', 'SX_URL_SB', 'relative', f'sx-mini-max-{effort}40', task,
                                mini_graph_mode=mode) for effort in campaign.EFFORTS]
    for plan, effort in zip(plans, campaign.EFFORTS):
        campaign.check_cell_plan(plan, {'task': task, 'reasoning': effort, 'mode': mode})
        assert plan['arms'] == ['taskviews']
        assert plan['generation_fields'] == {'enable_thinking': True, 'reasoning_effort': effort}
        assert plan['generation_profile']['max_completion_tokens'] == 16000
        assert plan['generation_profile']['step_output_tokens'] == 32000
    for key in ('cua_contract', 'resource_policy', 'mini_keyboard_tools', 'mini_keyboard_selection',
                'mini_graph', 'arm_profiles', 'transport_policy'):
        assert plans[0][key] == plans[1][key]


def test_refreezing_cannot_expand_reasoning_or_history_budgets():
    slot = campaign.slots()[0]
    plan = pair.specification('sx', 'SX_URL_SB', 'relative', 'sx-mini-max-high40',
                              mini_graph_mode=slot['mode'])
    plan['generation_profile']['step_output_tokens'] = 64000
    with pytest.raises(ValueError, match='cannot change the frozen'):
        campaign.check_cell_plan(plan, slot)


def test_host_lease_rejects_other_process_and_allows_inherited_child(tmp_path):
    code = ("from pathlib import Path; from ui_kobe.osworld import verified_serial as s; "
            "import sys; s.LOCK=Path(sys.argv[1]); "
            "ctx=s.serial_lock(); ctx.__enter__(); ctx.__exit__(None,None,None)")
    with verified_serial.serial_lock():
        env = {k: v for k, v in os.environ.items() if k != verified_serial.FD_ENV}
        denied = subprocess.run([sys.executable, '-c', code, str(verified_serial.LOCK)],
                                env=env, capture_output=True, text=True)
        assert denied.returncode and 'Another local OSWorld' in denied.stderr
        allowed = subprocess.run([sys.executable, '-c', code, str(verified_serial.LOCK)],
                                 pass_fds=verified_serial.inherited_fds(), capture_output=True, text=True)
        assert allowed.returncode == 0, allowed.stderr
    assert verified_serial.FD_ENV not in os.environ


def test_standalone_official_entrypoint_resolves_project_without_pythonpath(tmp_path):
    script = campaign.PROJECT / 'scripts/run_official_native_tasks.py'
    result = subprocess.run([sys.executable, '-I', str(script), '--help'], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0 and '--manifest' in result.stdout, result.stderr


@pytest.mark.parametrize('fail_at', [None, 5])
def test_launch_is_serial_scores_zero_continue_and_failure_stops(tmp_path, monkeypatch, fail_at):
    root = tmp_path / 'campaign'
    entries, _ = scaffold(root, monkeypatch)
    from scripts import osworld_native_experiment
    monkeypatch.setattr(osworld_native_experiment, 'require_scope', lambda _: tmp_path)
    monkeypatch.setattr(pair, 'validate_plan', lambda folder: campaign.read(folder / 'plan.json'))
    monkeypatch.setattr(campaign, 'report', lambda root: {})
    calls = []
    def run(command, **kwargs):
        folder = Path(command[command.index('--root') + 1])
        if calls:
            assert campaign.valid_outcome(calls[-1])
        calls.append(folder)
        assert verified_serial.inherited_fds() == kwargs['pass_fds']
        if len(calls) == fail_at:
            campaign.write(folder / 'state.json', {'status': 'stopped_on_error'})
            return SimpleNamespace(returncode=1)
        complete(folder, score=0)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(campaign.subprocess, 'run', run)
    assert campaign.launch(root, True) == int(fail_at is not None)
    assert len(calls) == (fail_at or 18)
    assert calls == [root / e['plan'] for e in entries[:len(calls)]]
    assert campaign.read(root / 'state.json')['status'] == ('stopped_on_error' if fail_at else 'completed')
    with pytest.raises(RuntimeError, match='No implicit retry'):
        campaign.launch(root, True)


def test_failed_and_rolled_back_repairs_consume_global_allowance(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    scaffold(root, monkeypatch)
    state = campaign.read(root / 'state.json')
    state['status'] = 'stopped_on_error'
    campaign.write(root / 'state.json', state)
    evidence = root / 'failure.json'
    campaign.write(evidence, {'error': 'real runtime exception'})
    validation = root / 'failed-validation.json'
    campaign.write(validation, {'passed': False})
    monkeypatch.setattr(campaign, 'no_owned_guest', lambda _: None)
    for number in range(1, 11):
        result = campaign.repair_begin(root, 'Fix the recorded runtime exception', evidence)
        assert result['used'] == number
        with pytest.raises(RuntimeError, match='already open|exhausted'):
            campaign.repair_begin(root, 'Duplicate repair', evidence)
        campaign.repair_finish(root, 'failed' if number % 2 else 'rolled_back', validation)
        assert campaign.ledger(root)['used'] == number
    with pytest.raises(RuntimeError, match='exhausted'):
        campaign.repair_begin(root, 'Eleventh repair forbidden', evidence)
    assert campaign.ledger(root)['used'] == 10


def test_normal_completion_cannot_be_used_to_optimize_for_score(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    entries, _ = scaffold(root, monkeypatch)
    complete(root / entries[0]['plan'], score=0)
    state = campaign.read(root / 'state.json')
    state['status'] = 'completed'
    campaign.write(root / 'state.json', state)
    evidence = root / 'score-zero.json'
    campaign.write(evidence, {'official_score': 0})
    with pytest.raises(RuntimeError, match='Normal scores'):
        campaign.repair_begin(root, 'Increase the score', evidence)
    assert campaign.ledger(root)['used'] == 0


@pytest.mark.parametrize('owned', [False, True])
def test_ownership_check_closes_docker_client_without_context_manager_support(tmp_path, monkeypatch, owned):
    root = tmp_path / 'campaign'
    entries, _ = scaffold(root, monkeypatch)
    import docker
    calls = []
    guests = [SimpleNamespace(labels={'ui-kobe.verified.run': entries[0]['slot']['id']})] if owned else []
    client = SimpleNamespace(containers=SimpleNamespace(list=lambda **kwargs: guests),
                             close=lambda: calls.append('closed'))
    monkeypatch.setattr(docker, 'from_env', lambda **kwargs: client)
    if owned:
        with pytest.raises(RuntimeError, match='guest still exists'):
            campaign.no_owned_guest(root)
    else:
        campaign.no_owned_guest(root)
    assert calls == ['closed']


def test_repair_cannot_edit_live_source_and_corruption_never_resets_count(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    scaffold(root, monkeypatch)
    campaign.write(root / 'launch-receipt.json', {'process': campaign.process_identity(os.getpid())})
    evidence = root / 'failure.json'
    campaign.write(evidence, {'error': 'recorded'})
    with pytest.raises(RuntimeError, match='launcher is alive'):
        campaign.repair_begin(root, 'Fix', evidence)
    campaign.write(root / 'repair-ledger.json', {'limit': 10, 'used': 0,
        'attempts': [{'number': 1, 'status': 'failed'}]})
    with pytest.raises(ValueError, match='inconsistent'):
        campaign.ledger(root)


def test_repair_scope_is_conservative_for_shared_actor_changes():
    before = {'kobe_views/mini_graph.py': 'a', 'scripts/verified_mini_graph_matrix.py': 'b'}
    assert campaign.affected_tasks(before, before | {'kobe_views/mini_graph.py': 'c'}) == list(campaign.TASK_ORDER)
    assert campaign.affected_tasks(before, before | {'scripts/verified_mini_graph_matrix.py': 'c'}) == []
    after = before | {'ui_kobe/osworld/task_specific/gimp/export.py': 'new'}
    assert campaign.affected_tasks(before, after) == ['gimp']


def test_failed_candidate_left_on_disk_cannot_hide_its_affected_cohorts(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    _, source = scaffold(root, monkeypatch)
    source['ui_kobe/actor.py'] = 'failed-patch-left-on-disk'
    assert campaign.affected_tasks(source, dict(source)) == []
    assert campaign.affected_cohorts(root, source) == list(campaign.TASK_ORDER)


def test_inspection_is_single_read_and_missing_launcher_is_anomaly(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    scaffold(root, monkeypatch)
    state = campaign.read(root / 'state.json')
    state['status'] = 'running'
    campaign.write(root / 'state.json', state)
    monkeypatch.setattr(campaign, 'process_identity', lambda _: None)
    result = campaign.inspect(root)
    assert result['issues'] == ['launcher_missing_or_identity_changed']
    assert result['read_once'] and not result['live_api_called'] and not result['vm_started']
    assert len(list((root / 'inspections').glob('*.json'))) == 1
    with campaign.file_lock(root / 'inspection.lock'):
        with pytest.raises(BlockingIOError):
            campaign.inspect(root)


def test_abort_refuses_healthy_or_outdated_inspection(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    scaffold(root, monkeypatch)
    campaign.write(root / 'latest-inspection.json', {'requires_analysis': False})
    with pytest.raises(RuntimeError, match='healthy run'):
        campaign.abort(root, 'diagnosis', True)
    campaign.write(root / 'latest-inspection.json', {'requires_analysis': True, 'active_slot': 'old'})
    with pytest.raises(RuntimeError, match='no longer identifies'):
        campaign.abort(root, 'diagnosis', True)


def test_report_keeps_invalid_scores_null_and_versions_separate(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    entries, _ = scaffold(root, monkeypatch)
    folder = root / entries[0]['plan']
    complete(folder, score=0)
    bad = root / entries[1]['plan']
    campaign.write(bad / 'taskviews/outcome.json', {'official_score': 1, 'complete': False})
    campaign.report(root)
    result = campaign.read(root / 'results.json')
    assert result['valid_cells'] == 1
    assert result['rows'][0]['official_score'] == 0
    assert result['rows'][1]['official_score'] is None and result['rows'][1]['raw_official_score'] == 1
    assert result['macro_official_scores'] is None
    assert all(not row['comparable'] for row in result['high_low_differences'])
    for entry in entries[1:]:
        complete(root / entry['plan'], score=1)
    campaign.report(root)
    assert campaign.read(root / 'results.json')['cross_task_aggregate_comparable']


def test_report_uses_delivery_receipts_and_regeneration_events_not_initial_or_cumulative_flags(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    entries, _ = scaffold(root, monkeypatch)
    history = []
    def emit(event, frame_id='frame-1', pid=42, **fields):
        history.append(dict(event=event, frame_id=frame_id, pid=pid, **fields))
    emit('mini_fixed_views', delivered=False, packet_sha256='a', packet_bytes=2998)
    emit('mini_views_delivered', packet_sha256='a')
    emit('mini_views_delivered', packet_sha256='a')  # Same packet on a retry counts once.
    emit('mini_fixed_views', 'frame-2', delivered=False, omission_reason='whole_envelope_budget')
    emit('mini_fixed_views', 'frame-3', delivered=False, packet_sha256='b')
    emit('mini_views_request_omitted', 'frame-3', reason='native_budget')
    emit('mini_fixed_views', 'frame-4', delivered=False, packet_sha256='c')  # No outcome receipt.
    emit('mini_fixed_views', 'frame-1', pid=43, delivered=False, packet_sha256='d')
    emit('mini_views_delivered', 'frame-1', pid=43, packet_sha256='d')
    emit('step_token_accounting', semantic_regenerations=0)
    emit('mini_report_regeneration', generation_attempt=2)
    emit('step_token_accounting', semantic_regenerations=1)
    emit('semantic_regeneration', generation_attempt=3)
    emit('step_token_accounting', semantic_regenerations=2)
    emit('step_token_accounting', semantic_regenerations=2)  # Additional accounting snapshot.
    for failure in ('missing_tag', 'invalid_reference', 'missing_tag'):
        emit('mini_report_rejected', failure=failure)
    emit('mini_report_recovery_exhausted', failures=['missing_tag', 'invalid_reference', 'missing_tag'])
    monkeypatch.setattr(campaign, 'events', lambda _: iter(history))
    row = campaign.summarize_cell(root, entries[0])
    assert (row['packets'], row['delivered_packets'], row['omitted_packets'], row['unconfirmed_packets']) == (5, 2, 2, 1)
    assert row['packet_audit_errors'] == [] and row['max_packet_bytes'] == 2998
    assert row['semantic_regenerations'] == 2 and row['report_rejections'] == 3
    assert row['report_recovery_exhaustions'] == 1 and row['last_report_failure'] == 'missing_tag'


@pytest.mark.parametrize('conflict', ['hash', 'omission', 'orphan'])
def test_report_never_silently_certifies_conflicting_or_unbound_packet_receipts(tmp_path, monkeypatch, conflict):
    root = tmp_path / 'campaign'
    entries, _ = scaffold(root, monkeypatch)
    history = [{'event': 'mini_fixed_views', 'frame_id': 'a', 'packet_sha256': 'sha-a', 'delivered': False},
               {'event': 'mini_views_delivered', 'frame_id': 'a', 'packet_sha256': 'sha-a'}]
    if conflict == 'hash':
        history[1]['packet_sha256'] = 'sha-b'
    elif conflict == 'omission':
        history.append({'event': 'mini_views_request_omitted', 'frame_id': 'a'})
    else:
        history[1]['frame_id'] = 'other'
    monkeypatch.setattr(campaign, 'events', lambda _: iter(history))
    row = campaign.summarize_cell(root, entries[0])
    assert row['packet_audit_errors'] and row['delivered_packets'] == 0
    assert row['unconfirmed_packets'] == 1 and row['omitted_packets'] == 0


def test_reprepare_replaces_entire_affected_cohort_and_preserves_old_results(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    entries, source = scaffold(root, monkeypatch)
    for entry in entries:
        complete(root / entry['plan'], score=1)
    before = dict(source)
    source['scripts/verified_mini_graph_matrix.py'] = 'repair'
    record = {'number': 1, 'status': 'passed', 'before_source': before,
              'after_source': dict(source), 'affected_tasks': ['gimp']}
    campaign.write(root / 'repair-ledger.json', {'limit': 10, 'used': 1, 'attempts': [record]})
    state = campaign.read(root / 'state.json')
    state['status'] = 'paused_for_repair'
    campaign.write(root / 'state.json', state)
    monkeypatch.setattr(campaign, 'no_owned_guest', lambda _: None)
    monkeypatch.setattr(campaign, 'archive_source', lambda _: None)
    def new_cell(root, revision, slot, config, validation):
        previous = next(e for e in entries if e['slot'] == slot)
        target = revision / 'cells' / slot['id']
        campaign.write(target / 'plan.json', campaign.read(root / previous['plan'] / 'plan.json'))
        campaign.write(target / 'state.json', {'status': 'prepared_not_started'})
        return dict(previous, plan=str(target.relative_to(root)), revision=revision.name,
                    plan_sha256=pair.sha(target / 'plan.json'))
    monkeypatch.setattr(campaign, 'prepare_cell', new_cell)
    result = campaign.reprepare(SimpleNamespace(root=root, validation_dir=tmp_path))
    assert result['new_cells'] == 6
    for entry in campaign.queue(root)['entries']:
        assert entry['revision'] == ('r001' if entry['slot']['task'] == 'gimp' else 'r000')
    assert all(campaign.valid_outcome(root / e['plan']) for e in entries)
    assert campaign.read(root / 'results.json')['valid_cells'] == 12
    with pytest.raises(RuntimeError, match='already refrozen'):
        campaign.reprepare(SimpleNamespace(root=root, validation_dir=tmp_path))
