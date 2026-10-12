from copy import deepcopy
import json

import pytest

from kobe_views.controls_view import VERSION, policy
from ui_kobe.api.kimi_stream import StreamProtocolError
from ui_kobe.osworld.actor_context import _declared_parameter_requirement, repair_messages
from ui_kobe.osworld.kimi_native import native_schema, validate_native
from test_mini_taskviews import make_actor, predict
from test_native_official_policy import candidate
from test_cua_contract import png
from ui_kobe.osworld.cua_contract import CUAContract


def example(arguments=None):
    frame = CUAContract().process(png(), 1)
    observed = candidate([arguments or {'action': 'key', 'text': 'Escape'}]).model_dump()
    request = {'tools': [native_schema(frame)], 'messages': [{'role': 'user', 'content': 'original goal'}]}
    try:
        validate_native(candidate([arguments or {'action': 'key', 'text': 'Escape'}]), frame)
    except StreamProtocolError as error:
        return request, observed, error, frame
    raise AssertionError('Expected an unchanged official rejection')


def test_original_key_candidates_stay_rejected_but_feedback_identifies_exact_schema_field():
    request, observed, error, frame = example()
    original = deepcopy([request, observed])
    repaired = repair_messages(request, observed, error, role='executor', declared_parameter_feedback=True)
    card = json.loads(_declared_parameter_requirement(request, observed, error))
    assert card['required_parameter'] == {'name': 'keys', 'schema': request['tools'][0]['function']['parameters']['properties']['keys']}
    assert card['matching_original_calls'][0]['provided_parameter_names'] == ['action', 'text']
    assert repaired['messages'][1] == observed['choices'][0]['message']
    assert repaired['messages'][2]['tool_call_id'] == observed['choices'][0]['message']['tool_calls'][0]['id']
    assert json.loads(repaired['messages'][2]['content']) == {'error': str(error)}
    assert [request, observed] == original
    for spelling in ('esc', 'Escape'):
        with pytest.raises(StreamProtocolError, match='key requires keys'):
            validate_native(candidate([{'action': 'key', 'text': spelling}]), frame)


def test_controls_actor_repairs_through_original_pool_with_full_bad_response_and_no_rewrite(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', VERSION)
    catalog = policy()
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'key', 'text': 'Escape'}, {'action': 'key', 'keys': ['esc']}])
    assert predict(actor, obs) == ['pyautogui.press("esc")']
    assert len(transport.requests) == 2 and actor.contract.tool_repair_retries == 2
    messages = transport.requests[1]['messages']
    bad = next(m for m in messages if m.get('role') == 'assistant')
    assert json.loads(bad['tool_calls'][0]['function']['arguments']) == {'action': 'key', 'text': 'Escape'}
    assert 'Exact parameter requirement:' in messages[-1]['content'][0]['text']
    assert actor.pending == 'original-2' and policy() == catalog
    actor.close()


def test_disabled_mini_and_legacy_feedback_remain_unchanged(monkeypatch, tmp_path):
    request, observed, error, _ = example()
    assert repair_messages(request, observed, error, role='executor') == repair_messages(
        request, observed, error, role='executor', declared_parameter_feedback=False)
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'key', 'text': 'Escape'}, {'action': 'key', 'keys': ['esc']}])
    predict(actor, obs)
    assert 'Exact parameter requirement:' not in transport.requests[-1]['messages'][-1]['content'][0]['text']
    actor.close()


@pytest.mark.parametrize('mutation', ['foreign_error', 'missing_field', 'foreign_action', 'huge_definition', 'huge_arguments'])
def test_feedback_requires_bounded_exact_declared_contract(mutation):
    request, observed, error, _ = example()
    if mutation == 'foreign_error':
        error.code = 'coordinate'
    elif mutation == 'missing_field':
        del request['tools'][0]['function']['parameters']['properties']['keys']
    elif mutation == 'foreign_action':
        error = StreamProtocolError('made_up requires keys', code='malformed_tool_call')
    elif mutation == 'huge_definition':
        request['tools'][0]['function']['parameters']['properties']['keys']['description'] = 'x' * 2000
    else:
        observed['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps({'action': 'key', 'text': 'x' * 6001})
    assert _declared_parameter_requirement(request, observed, error) is None


def test_other_required_fields_and_types_come_from_original_schema_without_action_examples():
    request, observed, error, _ = example({'action': 'type'})
    card = json.loads(_declared_parameter_requirement(request, observed, error))
    assert card['action'] == 'type' and card['required_parameter']['name'] == 'text'
    assert card['required_parameter']['schema']['type'] == 'string'
    assert 'example' not in card and card['matching_original_calls'][0]['provided_parameter_names'] == ['action']
