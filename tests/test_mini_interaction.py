"""Semantic regressions derived from successful and failed saved GUI transitions."""
from copy import deepcopy
import json

import pytest

from ui_kobe.api.kimi_stream import Completion, StreamProtocolError
from ui_kobe.osworld.mini_interaction import interaction_contract, validate_keys
from test_mini_taskviews import make_actor, packet, predict


@pytest.mark.parametrize('action', ['key', 'key_down', 'key_up'])
@pytest.mark.parametrize('key,correct', [('Page_Down', 'pagedown'), ('page_up', 'pageup'), ('minus', '-')])
def test_silent_alias_rejected_before_dispatch(action, key, correct):
    response = Completion({'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant'}}]})
    with pytest.raises(StreamProtocolError, match=correct if correct != '-' else 'silently ignored') as caught:
        validate_keys([{'action': action, 'keys': ['ctrl', key]}], response)
    assert caught.value.code == 'mini_silent_key_alias' and caught.value.retryable


@pytest.mark.parametrize('keys', [['pagedown'], ['pageup'], ['ctrl', '-'], ['return'], ['alt', 'F10']])
def test_valid_names_pass_through_without_rewriting(keys):
    arguments = [{'action': 'key', 'keys': keys}]
    before = deepcopy(arguments)
    validate_keys(arguments, Completion({'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant'}}]}))
    assert arguments == before


def test_saved_bad_page_down_repairs_to_baseline_key_with_existing_budget(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'key', 'keys': ['Page_Down']}, {'action': 'key', 'keys': ['pagedown']}])
    commands = predict(actor, obs)
    assert commands == ['pyautogui.press("pagedown")']
    assert len(transport.requests) == 2 and actor.total_steps == 1
    assert actor.last_trace['step_tokens']['semantic_regenerations'] == 1
    assert actor.contract.tool_repair_retries == 2
    repair = transport.requests[-1]['messages']
    assert any(m.get('tool_call_id') == 'original-1' and 'silently ignored' in m['content'] for m in repair)
    transitions = [json.loads(r[0]) for r in actor.execution_journal.db.execute('SELECT payload FROM events')]
    assert all(e['action'] == commands[0] for e in transitions if e['kind'] == 'transition')
    actor.close()


def test_invalid_member_rejects_whole_batch(monkeypatch, tmp_path):
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    actor.frame = actor.contract.process(obs['screenshot'], 1)
    calls = [{'id': str(i), 'type': 'function', 'function': {'name': 'computer_use',
        'arguments': json.dumps(a)}} for i, a in enumerate([
            {'action': 'left_click', 'coordinate': [10, 10]}, {'action': 'key', 'keys': ['minus']}])]
    response = Completion({'choices': [{'finish_reason': 'tool_calls',
                                       'message': {'role': 'assistant', 'tool_calls': calls}}]})
    with pytest.raises(StreamProtocolError, match='Entire batch'):
        actor.validate_actor_candidate(response)
    assert actor.executions == [] and actor.execution_journal.decision is None
    actor.close()


def test_failed_repairs_are_bounded_and_never_execute(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'key', 'keys': ['Page_Down']}] * 3)
    with pytest.raises(StreamProtocolError):
        predict(actor, obs)
    assert len(transport.requests) == 3 and actor.execution_journal.decision is None
    assert actor.executions == []
    actor.close()


def test_generic_guidance_yields_to_journal_evidence_under_original_view_budget(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    for _ in range(3):
        predict(actor, obs)
    value = packet(transport)
    current = value['views']['current']['records'][0]
    first = json.loads(transport.requests[0]['messages'][-1]['content'][-1]['text'].split('\n', 1)[1])
    guidance = first['views']['current']['records'][0]['interaction_contract']
    assert guidance == interaction_contract()
    assert 'ignores its coordinate' in guidance['scroll']
    assert 'does not confirm a dialog' in guidance['deliverable']
    # Generic advice is optional; later real evidence and the full report
    # protocol take its space rather than being silently displaced by it.
    assert current['interaction_contract_omitted'] is True
    assert 'interaction_contract' not in current
    assert value['views']['attempts']['records']
    assert actor.mini_context.trace['latest_operation_delivered']
    assert actor.mini_context.trace['artifact_protocol_in_packet']
    assert actor.mini_context.trace['packet_bytes'] <= 3000
    assert len(transport.requests) == 3
    assert '243729' not in json.dumps(current) and 'problematic' not in json.dumps(current)
    actor.close()
