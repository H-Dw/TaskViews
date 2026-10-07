from io import BytesIO
import json
import sqlite3

from PIL import Image
import pytest

from kobe_views.adapters import UIKobeAdapter
from kobe_views.execution_modules import ExecutionModules
from kobe_views.task_memory import TaskMemory
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.transitions import TransitionJournal


def image(color='white'):
    buffer = BytesIO()
    Image.new('RGB', (64, 48), color).save(buffer, 'PNG')
    return {'screenshot': buffer.getvalue()}


def journal(tmp_path):
    return TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
        contract=CUAContract(model_screen_width=64, model_screen_height=48))


def test_each_official_command_has_paired_evidence_and_unexecuted_tail(tmp_path):
    log = journal(tmp_path)
    log.begin('literal instruction', image(), step=1)
    decision = log.decide('model intent', ['move', 'WAIT', 'unexecuted'], step=1,
                         tools=[{'id': 'call1', 'arguments': {'action': 'mouse_move'}, 'command_indices': [0]}])
    first = log.result('move', step=1, observation=image('red'), receipts=[{'result': {'returncode': 0}}])
    second = log.result('WAIT', step=1, observation=image('blue'))
    log.phase('evaluation_start')
    export = log.export_ui_kobe()
    assert first['decision_id'] == decision['id'] and first['tool']['id'] == 'call1'
    assert first['target'] == second['source'] and first['effect_status'] == 'unknown'
    assert second['controller_receipts'] == [] and second['dispatch_observed']
    pending = next(r for r in log.read() if r['kind'] == 'unexecuted_command')
    assert pending['action'] == 'unexecuted' and not pending['dispatch_observed']
    assert len(export['edges']) == 2 and all(r['metadata_alignment'] == 'paired_event' for r in export['edges'])
    assert len(UIKobeAdapter().convert(export).edges) == 2
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        log.db.execute('DELETE FROM events')
    path = log.path
    log.close()
    stored = json.loads(path.with_suffix('.ui-kobe.json').read_text())
    assert stored['edges'] == export['edges']
    replay = TransitionJournal.open_readonly(path)
    assert replay.export_ui_kobe() == export
    with pytest.raises(sqlite3.OperationalError):
        replay.append('forbidden')
    replay.close()


def test_missing_observations_never_reuse_a_stale_source_or_fabricate_targets(tmp_path):
    log = journal(tmp_path)
    log.begin('goal', image(), step=1)
    log.decide('intent', ['x', 'y'], step=1)
    failed = log.result('x', step=1, error='controller timeout')
    following = log.result('y', step=1, observation=image('red'))
    assert failed['target'] is None and 'missing_target' in failed['gaps']
    assert following['source'] is None and 'missing_source' in following['gaps']
    log.begin('goal', {}, step=2)
    assert log.decide('intent', ['WAIT'], step=2)['source'] is None
    adapter = UIKobeAdapter()
    adapter.convert(log.export_ui_kobe())
    assert len(adapter.gaps) == 2
    log.close()


def test_optional_state_delta_distinguishes_null_missing_and_model_proposals(tmp_path):
    log = journal(tmp_path)
    log.begin('goal', image(), step=1)
    source = log.current['id']
    log.decide('intent', ['x'], step=1)
    edge = log.result('x', step=1, observation=image('red'))
    assert log.export_ui_kobe()['edges'][0]['schema_delta'] is None
    log.annotate(source, logical_page='editor', state_schema={'name': None, 'old': 1}, evidence_ref='proposal:1')
    log.annotate(edge['target'], logical_page='editor', state_schema={'new': None}, evidence_ref='proposal:2')
    delta = log.export_ui_kobe()['edges'][0]
    assert delta['schema_delta']['name']['before_present'] and not delta['schema_delta']['name']['after_present']
    assert not delta['schema_delta']['new']['before_present'] and delta['schema_delta']['new']['after_present']
    assert delta['schema_delta_grade'] == 'model_proposal'
    log.close()


def test_repeated_actions_and_different_instructions_are_distinct_attempts(tmp_path):
    log = journal(tmp_path)
    for step, goal in enumerate(('goal one', 'goal two'), 1):
        log.begin(goal, image(), step=step)
        log.decide('intent', ['WAIT'], step=step)
        log.result('WAIT', step=step, observation=image())
    edges = log.export_ui_kobe()['edges']
    assert len(edges) == 2 and edges[0]['id'] != edges[1]['id']
    assert edges[0]['instruction_ref'] != edges[1]['instruction_ref']
    log.close()


def test_modules_replay_events_and_preserve_subgoals_without_geometry_or_fake_success(tmp_path):
    log = journal(tmp_path)
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('original goal')
    modules = ExecutionModules(memory, log)
    log.begin('original goal', image(), step=1)
    modules.sync()
    needs = [{'purpose': 'prepare result', 'anchors': ['task']}]
    active = modules.select('prepare', needs, frame='one', ref='frame:one')
    log.decide('intent', ['move'], step=1, tools=[{'arguments': {'action': 'mouse_move', 'coordinate': [1, 2]},
                                               'command_indices': [0]}])
    edge = log.result('move', step=1, observation=image('red'), receipts=[{'returncode': 0}])
    modules.sync()
    modules.report('verifier', {'assessment': 'verified', 'quotes': ['visible'], 'gaps': ['missing output']}, frame='two')
    assert modules.modules[active]['state'] == 'active'
    assert modules.modules[active]['outputs'][0]['transition_id'] == edge['id']
    assert modules.packet()['recent_transitions'][0]['action_semantics'] == {'action': 'mouse_move'}
    assert 'missing output' in modules.modules[active]['needed_evidence']
    second = modules.select('deliver', needs, frame='two', ref='frame:two')
    assert second != active and modules.modules[active]['state'] == 'paused'
    replay = ExecutionModules(memory, log)
    old_revision = memory.snapshot.revision
    replay.sync()
    assert memory.snapshot.revision == old_revision and replay.modules == modules.modules
    assert replay.packet()['active_module'] == second
    log.close()
    memory.close()


def test_projection_changes_advance_only_after_delivery(tmp_path):
    log = journal(tmp_path)
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('goal')
    modules = ExecutionModules(memory, log)
    packet = {'consumer': 'executor', 'task_id': 'task', 'contract_revision': 'role1', 'revision': 1,
              'needs': [{'id': 'need', 'purpose': 'inspect', 'instances': []}]}
    assert modules.view_changes({'packets': [packet]})['executor']['reset']
    assert modules.view_changes({'packets': [packet]})['executor']['reset']
    modules.delivered()
    packet['revision'] = 2
    assert not modules.view_changes({'packets': [packet]})['executor']['changed']
    packet['needs'][0]['purpose'] = 'deliver'
    delta = modules.view_changes({'packets': [packet]})['executor']
    assert delta['changed'] and delta['base_revision'] == 1
    log.close()
    memory.close()


def test_passive_hook_captures_even_when_analysis_fails_and_preserves_actual_returns(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import sys
    from ui_kobe.osworld import telemetry
    obs = image()
    original_return = (image('red'), 0, False, {'official': True})
    score, closed = object(), object()
    class Agent:
        contract = CUAContract(model_screen_width=64, model_screen_height=48)
        transition_recording = True
        responses = ['']
        def predict(self, instruction, observation):
            # Experimental recording survives unavailable optional analysis.
            return 'intent', ['WAIT']
    class Controller:
        def execute_python_command(self, command):
            return {'returncode': 0}
    class Env:
        def step(self, action):
            return original_return
        def evaluate(self):
            return score
        def close(self):
            return closed
    monkeypatch.setitem(sys.modules, 'mm_agents.qwen', SimpleNamespace(QwenAgent=Agent))
    monkeypatch.setitem(sys.modules, 'desktop_env.desktop_env', SimpleNamespace(DesktopEnv=Env))
    monkeypatch.setitem(sys.modules, 'desktop_env.controllers.python', SimpleNamespace(PythonController=Controller))
    monkeypatch.setattr(telemetry, '_installed', False)
    monkeypatch.setattr(telemetry, 'install_api', lambda _: None)
    monkeypatch.setattr(telemetry, '_root', tmp_path)
    telemetry.install(tmp_path)
    agent, env = Agent(), Env()
    assert agent.predict('literal goal', obs)[1] == ['WAIT']
    result = env.step('WAIT')
    assert result == original_return and result[0] is original_return[0] and result[3] is original_return[3]
    edge = agent.execution_journal.export_ui_kobe()['edges'][0]
    assert edge['source'] and edge['target'] and edge['instruction'] == 'literal goal'
    assert edge['controller_receipts'] == [] and edge['effect_status'] == 'unknown'
    assert env.evaluate() is score and env.close() is closed
    assert agent.execution_journal.closed
    def broken(*args, **kwargs):
        raise OSError('passive disk failure')
    monkeypatch.setattr(TransitionJournal, 'result', broken)
    agent = Agent()
    agent.predict('literal goal', obs)
    result = env.step('WAIT')
    assert result == original_return and result[0] is original_return[0] and result[3] is original_return[3]
    env.close()


def test_redaction_failure_is_an_observer_warning_not_an_execution_gate(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from ui_kobe.osworld import telemetry
    log = journal(tmp_path)
    log.begin('goal', image(), step=1)
    def malformed(_):
        raise ValueError('invalid embedded image')
    monkeypatch.setattr(telemetry, 'safe', malformed)
    monkeypatch.setattr(telemetry, 'emit', lambda *args, **kwargs: None)
    assert telemetry.record_transition(SimpleNamespace(execution_journal=log), 'result', 'WAIT',
                                       step=1, observation=image()) is None
    log.close()


def test_real_emitter_matches_sqlite_records_and_keeps_evidence_grades(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from ui_kobe.osworld import telemetry
    log = journal(tmp_path)
    monkeypatch.setattr(telemetry, '_root', tmp_path)
    monkeypatch.setattr(telemetry, '_context', SimpleNamespace(step=1, phase='agent'))
    agent = SimpleNamespace(execution_journal=log)
    telemetry.record_transition(agent, 'begin', 'literal instruction', image(), step=1)
    decision = telemetry.record_transition(agent, 'decide', 'model proposal', ['move'], step=1,
        tools=[{'id': 'native-call', 'arguments': {'action': 'mouse_move', 'coordinate': [1, 2]},
                'command_indices': [0]}])
    receipt = {'result': {'returncode': 0, 'output': 'actual command response'}}
    edge = telemetry.record_transition(agent, 'result', 'move', step=1,
        observation=image('red'), receipts=[receipt], info={'official': True})
    evaluation = telemetry.record_transition(agent, 'phase', 'evaluation_result', score=0.2)
    rows = [json.loads(line) for path in tmp_path.glob('events-*.jsonl') for line in path.read_text().splitlines()]
    assert [row['event'] for row in rows] == ['execution_journal_event'] * 3
    assert [row['journal_kind'] for row in rows] == ['decision', 'transition', 'evaluation_result']
    assert [row['ref'] for row in rows] == [log.reference(record) for record in (decision, edge, evaluation)]
    persisted = {row['id']: row for row in log.read()}
    assert edge['id'] in persisted and edge['source'] != edge['target']
    assert edge['instruction'] == 'literal instruction' and edge['controller_receipts'] == [receipt]
    assert edge['tool']['id'] == 'native-call' and edge['effect_status'] == 'unknown'
    assert persisted[edge['target']]['phase'] == 'action_output'
    exported = log.export_ui_kobe()['edges'][0]
    assert exported['schema_delta'] is None and exported['target_observation']
    log.close()
