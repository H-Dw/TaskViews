from copy import deepcopy
import json

from kobe_views.fixed_views import MAX_BYTES, PROFILE
from ui_kobe.api.kimi_stream import Completion
from ui_kobe.osworld.checkpoints import Checkpoints
from test_mini_taskviews import TASK, make_actor, predict
from test_taskviews_checkpoints import VM


class BoundedTransport:
    """Mock completions only; retain one request, not 500 copies of image/history."""
    last_timing = {}

    def __init__(self, completed=0):
        self.completed = completed
        self.requests = 0
        self.last = None

    def create(self, **request):
        assert request['budget_role'] == 'executor' and request['generation_attempt'] == 1
        self.requests += 1
        self.completed += 1
        self.last = deepcopy(request['messages'])
        identifier = f'original-{self.completed}'
        return Completion({'choices': [{'finish_reason': 'tool_calls', 'message': {
            'role': 'assistant', 'content': 'Observe current frame', 'tool_calls': [{
                'id': identifier, 'type': 'function', 'function': {'name': 'computer_use',
                    'arguments': '{"action":"mouse_move","coordinate":[1,1]}'}}]}}]})

    def close(self):
        pass


def use(actor, completed=0):
    value = BoundedTransport(completed)
    actor.client.transport = actor.transport = value
    return value


def close_without_graph_materialization(actor):
    actor.execution_journal.db.close()
    actor.execution_journal.closed = True
    actor.close()


def test_500_mock_decisions_and_midpoint_restore_keep_original_sequence_and_errors(tmp_path, monkeypatch):
    actor, obs, _ = make_actor(monkeypatch, tmp_path / 'first')
    transport = use(actor)
    for step in range(1, 251):
        commands = predict(actor, obs, error='Original early controller failure' if step == 2 else None)
        assert commands == ['pyautogui.moveTo(1, 1)'] and actor.pending == f'original-{step}'
        assert actor.mini_context.trace['packet_bytes'] <= MAX_BYTES
    assert transport.requests == 250
    cp = Checkpoints(tmp_path / 'stage', {'taskviews_profile': PROFILE, 'arm': 'taskviews'}, qmp=VM())
    cp.vm = {'container': 'offline-fake-guest'}
    tag = cp.save(actor, TASK, obs)
    original_db = actor.execution_journal.path
    actor.execution_journal.append('bad_read', error='Immutable branch after safe boundary')
    restored, _, _ = make_actor(monkeypatch, tmp_path / 'resumed')
    next_transport = use(restored, 250)
    state = cp.restore_agent(restored)
    assert state['tag'] == tag and restored.total_steps == 250 and restored.pending == 'original-250'
    assert cp.qmp.calls == [('save', tag)]  # Fake guest adapter; no real QMP/VM or reset.
    assert restored.execution_journal.path != original_db
    for step in range(251, 501):
        predict(restored, obs)
        assert restored.pending == f'original-{step}'
        assert restored.mini_context.trace['packet_bytes'] <= MAX_BYTES
    assert next_transport.requests == 250 and restored.total_steps == 500
    assert restored.mini_context.delivery['count'] == 500
    tools = [row for row in next_transport.last if row['role'] == 'tool']
    assert tools[-1]['tool_call_id'] == 'original-499'
    encoded = next_transport.last[-1]['content'][-1]['text'].split('\n', 1)[1]
    packet = json.loads(encoded)
    assert len(encoded.encode()) <= MAX_BYTES
    for row in packet['views']['attempts']['records']:
        original = restored.execution_journal.db.execute('SELECT payload FROM events WHERE id=?',
                                                        (row['source_event_id'],)).fetchone()[0]
        assert json.loads(original)['step'] < 500
    error = next(row for row in packet['views']['lessons']['records'] if row['grade'] == 'execution_error_record')
    assert error['error'] == 'Original early controller failure'
    db = restored.execution_journal.db
    assert db.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='transition'").fetchone()[0] == 500
    assert len(restored.turns) <= 21 and restored.folded_prefix_count > 0
    # No evaluator, score fixture, adviser or live API was used in this trajectory.
    close_without_graph_materialization(actor)
    close_without_graph_materialization(restored)
