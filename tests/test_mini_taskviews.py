from copy import deepcopy
import hashlib
from io import BytesIO
import json

from PIL import Image
import pytest

from kobe_views.fixed_views import MAX_BYTES, PROFILE, VIEW_IDS, materialize
from ui_kobe.api.kimi_stream import Completion
from ui_kobe.api.qwen_native import BASE_URL, MODEL
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.kimi_native import KimiNativeAgent
from ui_kobe.osworld.mini_taskviews_native import QwenMiniTaskViewsNativeAgent
from ui_kobe.osworld.qwen_native_base import QwenNativeAgent, QwenNativeProvider
from ui_kobe.osworld.transitions import TransitionJournal, decision_tools

TASK = 'Original public task'


class OfflineTransport:
    last_timing = {}

    def __init__(self, actions=None):
        self.requests = []
        self.actions = iter(actions or [{'action': 'left_click'}] * 8)

    def create(self, **kwargs):
        self.requests.append({key: deepcopy(value) for key, value in kwargs.items()
                              if key in {'messages', 'budget_role', 'generation_attempt', 'max_tokens'}})
        action = next(self.actions)
        return Completion({'choices': [{'finish_reason': 'tool_calls', 'message': {
            'role': 'assistant', 'content': 'Look at the current image', 'tool_calls': [{
                'id': 'original-' + str(len(self.requests)), 'type': 'function', 'function': {
                    'name': 'computer_use', 'arguments': json.dumps(action)}}]}}]})

    def close(self):
        pass


def make_actor(monkeypatch, tmp_path, *, actions=None, tiny=False, cls=QwenMiniTaskViewsNativeAgent):
    monkeypatch.setenv('QWEN_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_PROFILE', PROFILE)
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_FEEDBACK_V10', '0')
    contract = CUAContract(history_n=20, image_max=1, fold_size=1, context_max_text_chars=32000,
        context_max_payload_chars=2000000, context_reserve_chars=10000,
        context_rough_text_token_budget=12000, taskviews_context_bytes=1 if tiny else 8000)
    monkeypatch.setenv('UI_KOBE_CUA_CONTRACT_JSON', json.dumps(contract.snapshot()))
    transport = OfflineTransport(actions)
    monkeypatch.setattr(QwenNativeProvider, 'provider_transport', lambda *a: transport)
    actor = cls(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
    image = BytesIO()
    Image.new('RGB', (1920, 1080)).save(image, format='PNG')
    obs = {'screenshot': image.getvalue()}
    if cls is QwenMiniTaskViewsNativeAgent:
        actor.execution_journal = TransitionJournal(tmp_path / 'journal', task_id='059',
                                                   run_id='offline-mini', contract=contract)
    return actor, obs, transport


def predict(actor, obs, *, dispatch=True, error=None):
    if actor.total_steps:
        actor.flush_execution()
    journal = actor.execution_journal
    journal.begin(TASK, obs, step=actor.total_steps + 1)
    response, commands = actor.predict(TASK, obs)
    journal.decide(response, commands, step=actor.total_steps, tools=decision_tools(actor))
    if dispatch:
        for command in commands:
            receipts = [{'command': command, 'result': {'success': error is None, 'error': error}}]
            journal.result(command, step=actor.total_steps, observation=obs, receipts=receipts, error=error)
            actor.record_execution(command, receipts=receipts, error=error)
    return commands


def packet(transport):
    return json.loads(transport.requests[-1]['messages'][-1]['content'][-1]['text'].split('\n', 1)[1])


def test_fixed_views_use_one_actor_and_no_full_control(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    assert actor.predict.__func__ is KimiNativeAgent.predict
    assert not hasattr(actor, 'control') and not hasattr(actor, 'modules')
    predict(actor, obs)
    value = packet(transport)
    assert set(value['views']) == set(VIEW_IDS)
    assert value['views']['attempts']['records'] == value['views']['lessons']['records'] == []
    assert len(transport.requests) == 1 and transport.requests[0]['budget_role'] == 'executor'
    assert actor.mini_context.trace['delivered'] and actor.mini_context.delivery['count'] == 1
    assert sum(part['type'] == 'image_url' for part in transport.requests[0]['messages'][-1]['content']) == 1
    actor.close()


def test_current_geometry_is_literal_current_frame_and_does_not_transform_native_arguments(monkeypatch, tmp_path):
    original = {'action': 'left_click', 'coordinate': [698, 248]}
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[original, original])
    commands = predict(actor, obs)
    value = packet(transport)
    current = value['views']['current']['records'][0]
    assert current['frame_geometry'] == {key: actor.frame.metadata[key] for key in
        ('coordinate_type', 'original_size', 'model_size', 'coordinate_bounds')}
    assert current['frame_geometry']['coordinate_type'] == 'absolute'
    assert current['frame_geometry']['original_size'] == current['frame_geometry']['model_size'] == [1920, 1080]
    assert current['frame_geometry']['coordinate_bounds'] == [1920, 1080]
    assert commands == ['pyautogui.click(698, 248)']
    first_frame = value['frame_id']
    predict(actor, obs)
    assert packet(transport)['frame_id'] != first_frame
    assert packet(transport)['views']['current']['records'][0]['original_sha256'] == actor.frame.original_sha256
    assert len(transport.requests) == 2 and actor.contract.taskviews_context_bytes == 8000
    actor.close()


def test_real_edges_errors_and_prose_have_distinct_source_grades(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    predict(actor, obs, error='Original controller error')
    predict(actor, obs)
    value = packet(transport)
    attempt = value['views']['attempts']['records'][0]
    assert attempt['tool']['id'] == 'original-1'
    assert attempt['tool']['arguments'] == {'action': 'left_click'}
    encoded = actor.execution_journal.db.execute('SELECT payload FROM events WHERE id=?',
                                               (attempt['source_event_id'],)).fetchone()[0]
    assert attempt['source_sha256'] == hashlib.sha256(encoded.encode()).hexdigest()
    lessons = value['views']['lessons']['records']
    error = next(row for row in lessons if row['grade'] == 'execution_error_record')
    prose = next(row for row in lessons if row['grade'] == 'model_intent_proposal')
    assert error['error'] == 'Original controller error' and prose['text'] == 'Look at the current image'
    assert attempt['effect_status'] == 'unknown' and not any('assessment' in row for row in lessons)
    tools = [msg for msg in transport.requests[-1]['messages'] if msg['role'] == 'tool']
    assert tools[0]['tool_call_id'] == 'original-1' and 'Original controller error' in tools[0]['content']
    actor.close()


@pytest.mark.parametrize('result', [
    {'status': 'error', 'returncode': 0}, {'status': 'failed'},
    {'status': 'success', 'returncode': 1, 'stderr': 'Original command stderr'}])
def test_original_controller_status_and_returncode_enter_lessons_without_visual_claims(monkeypatch, tmp_path, result):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    commands = predict(actor, obs, dispatch=False)
    receipts = [{'command': commands[0], 'result': deepcopy(result)}]
    actor.execution_journal.result(commands[0], step=1, observation=obs, receipts=receipts)
    actor.record_execution(commands[0], receipts=receipts)
    predict(actor, obs)
    errors = [row for row in packet(transport)['views']['lessons']['records']
              if row['grade'] == 'execution_error_record']
    assert len(errors) == 1 and errors[0]['controller_receipts'] == receipts
    assert errors[0]['error'] is None and 'assessment' not in errors[0]
    actor.close()


def test_too_small_optional_view_is_exactly_the_common_native_input(monkeypatch, tmp_path):
    mini, obs, mini_transport = make_actor(monkeypatch, tmp_path / 'mini', tiny=True)
    predict(mini, obs)
    baseline, obs, native_transport = make_actor(monkeypatch, tmp_path / 'baseline', tiny=True, cls=QwenNativeAgent)
    baseline.predict(TASK, obs)
    assert mini_transport.requests == native_transport.requests
    assert mini.cached_context is None and mini.mini_context.trace['omission_reason'] == 'whole_envelope_budget'
    mini.close()
    baseline.close()


@pytest.mark.parametrize('problem', ['frame', 'episode', 'missing_journal', 'closed_journal'])
def test_integrity_errors_pause_before_supplier(monkeypatch, tmp_path, problem):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    journal = actor.execution_journal
    journal.begin(TASK, obs, step=1)
    if problem == 'frame':
        journal.current['frame']['original_sha256'] = 'different'
    elif problem == 'episode':
        journal.append('transition', episode_id='another', error='original')
    elif problem == 'missing_journal':
        actor.execution_journal = None
    else:
        journal.close()
    with pytest.raises(ReadAnomaly):
        actor.predict(TASK, obs)
    assert not transport.requests
    if not journal.closed:
        if problem == 'episode':
            journal.db.close()  # Deliberately corrupt fixture cannot be exported as a valid graph.
            journal.closed = True
        else:
            journal.close()
    actor.execution_journal = None
    actor.close()


def test_incomplete_command_cannot_become_a_checkpoint(monkeypatch, tmp_path):
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs, dispatch=False)
    with pytest.raises(ReadAnomaly, match='unconfirmed command'):
        actor.flush_execution()
    actor.close()


def test_whole_omission_preserves_long_record_and_source_order():
    rows = [{'seq': 3, 'source_event_id': 'new', 'text': 'long' * 2000},
            {'seq': 2, 'source_event_id': 'second', 'text': 'visible'},
            {'seq': 1, 'source_event_id': 'first', 'text': 'original'}]
    original = deepcopy(rows)
    result = materialize(episode_id='episode', frame_id='frame', current={'original': True},
        attempts=rows, lessons=[], totals={'attempts': 20, 'lessons': 0}, max_bytes=MAX_BYTES)
    assert rows == original and len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_BYTES
    view = result['views']['attempts']
    assert [row['seq'] for row in view['records']] == [1, 2]
    assert view['omitted_records'] == 18 and 'long' not in json.dumps(result)


def test_original_native_repair_pool_and_rejected_tool_ids_are_preserved(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'made_up'}, {'action': 'key', 'keys': ['Escape']}])
    commands = predict(actor, obs)
    assert commands == ['pyautogui.press("escape")'] and len(transport.requests) == 2
    repaired = transport.requests[-1]['messages']
    original = next(msg for msg in repaired if msg['role'] == 'assistant')
    assert original['tool_calls'][0]['id'] == 'original-1'
    assert any(msg.get('tool_call_id') == 'original-1' for msg in repaired)
    assert actor.pending == 'original-2' and actor.contract.tool_repair_retries == 2
    actor.close()


def test_full_workflow_flag_cannot_silently_enter_mini(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_FEEDBACK_V10', '1')
    with pytest.raises(ValueError, match='without full feedback'):
        QwenMiniTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)


def test_oversized_repair_history_pauses_without_an_extra_supplier_call(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[{'action': 'made_up'}])
    original = transport.create

    def large_candidate(**kwargs):
        result = original(**kwargs).model_dump()
        result['choices'][0]['message']['content'] = 'original' * 5000
        return Completion(result)

    transport.create = large_candidate
    with pytest.raises(ReadAnomaly, match='Mandatory native history'):
        predict(actor, obs)
    assert len(transport.requests) == 1
    actor.close()


def test_late_optional_omission_records_accepted_request_gap(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    trace = actor.mini_context.trace
    assert trace['delivered']
    actor.client.create(messages=[{'role': 'user', 'content': [{'type': 'text', 'text': 'x' * 31500}]}])
    assert len(transport.requests) == 2 and not trace['delivered']
    assert trace['omission_reason'] == 'actor_request_budget'
    actor.close()
