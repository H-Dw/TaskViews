from copy import deepcopy
import json
import time

import httpx
import pytest

from scripts.verified_invoice import specification
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import StreamProtocolError
from ui_kobe.api.openrouter_native import BASE_URL, MODEL, OpenRouterNativeClient, OpenRouterSSE, generation_profile
from ui_kobe.api.qwen_native import QwenTransportBudget
from ui_kobe.osworld.native_history import context_size

DETAILS = [
    {'type': 'reasoning.text', 'text': 'first ', 'signature': None, 'id': 'r', 'index': 0, 'format': 'unknown'},
    {'type': 'reasoning.text', 'text': 'part', 'signature': 'opaque-signature', 'id': 'r', 'index': 0},
    {'type': 'reasoning.encrypted', 'data': 'opaque-data', 'id': 'e', 'index': 1},
]


def frame(delta=None, finish=None, usage=None, **fields):
    body = {'id': 'or-response', 'model': MODEL, 'provider': 'fixture-provider', 'created': 1,
            'choices': [] if usage else [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}], **fields}
    if usage:
        body['usage'] = usage
    return ('data: ' + json.dumps(body) + '\n\n').encode()


def stream():
    raw = b': OPENROUTER PROCESSING\n\n'
    for detail in DETAILS:
        raw += frame({'reasoning_details': [detail]})
    raw += frame({'role': 'assistant', 'reasoning': 'flat trace', 'content': 'OK', 'tool_calls': [{
        'index': 0, 'id': 'tool-original', 'type': 'function', 'function': {
            'name': 'computer_use', 'arguments': '{"action":"mouse_move","coordinate":[1,2]}'}}]})
    raw += frame(finish='tool_calls')
    raw += frame(usage={'prompt_tokens': 50, 'completion_tokens': 20, 'total_tokens': 70,
                        'completion_tokens_details': {'reasoning_tokens': 15}, 'cost': 0.0001})
    return raw + b'data: [DONE]\n\n'


def test_reasoning_objects_preserved_exactly_across_fragmented_sse_and_replay(tmp_path):
    raw = stream()
    accumulator = OpenRouterSSE(MODEL)
    for byte in raw:
        accumulator.feed(bytes([byte]))
    accumulator.feed(b'', final=True)
    complete = accumulator.complete()
    assistant = complete['choices'][0]['message']
    assert assistant['reasoning_details'] == DETAILS
    assert assistant['reasoning'] == 'flat trace' and 'reasoning_content' not in assistant
    assert complete['provider'] == 'fixture-provider' and complete['usage']['cost'] == 0.0001
    assistant['reasoning_details'][0]['text'] = 'mutated copy'
    assert accumulator.observed()['choices'][0]['message']['reasoning_details'] == DETAILS
    original = accumulator.observed()['choices'][0]['message']
    messages = [{'role': 'user', 'content': 'diagnostic'}, original,
                {'role': 'tool', 'tool_call_id': 'tool-original', 'content': 'OK'}]
    snapshot = deepcopy(messages)
    captured = []
    def handler(request):
        assert str(request.url) == BASE_URL + '/chat/completions'
        body = json.loads(request.content)
        captured.append(body)
        assert body['messages'] == snapshot
        assert body['reasoning'] == {'enabled': True, 'effort': 'low'}
        assert body['provider'] == {'require_parameters': True}
        assert all(k not in body for k in ('reasoning_effort', 'enable_thinking', 'preserve_thinking', 'separate_reasoning'))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=raw)
    profile = generation_profile()
    ledger = StepLedger(profile, time.monotonic()+930, lambda *a, **k: None)
    client = OpenRouterNativeClient(api_key='or-test-key', profile=profile, budget=QwenTransportBudget(attempts=1),
        emit=lambda *a, **k: None, response_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        response = client.create(model=MODEL, messages=messages, max_tokens=16000,
                    step_ledger=ledger, budget_role='executor', deadline=ledger.deadline).model_dump()
        assert response['choices'][0]['message']['reasoning_details'] == DETAILS
        assert messages == snapshot and len(captured) == 1
    finally:
        client.close()


@pytest.mark.parametrize('tail', [frame({'reasoning_details': 'not-an-array'}),
                                frame({'reasoning_details': [123]}),
                                frame(provider='changed-provider'),
                                b'data: {"error":{"message":"upstream failed","code":502}}\n\n'])
def test_invalid_details_provider_or_midstream_error_prevent_completion(tail):
    accumulator = OpenRouterSSE(MODEL)
    accumulator.feed(frame({'role': 'assistant'}) + tail + b'data: [DONE]\n\n', final=True)
    with pytest.raises(StreamProtocolError):
        accumulator.complete()


def test_reasoning_details_count_against_history_text_budget_without_rewriting():
    messages = [{'role': 'assistant', 'content': 'OK', 'reasoning_details': deepcopy(DETAILS)}]
    before = deepcopy(messages)
    _, text = context_size(messages)
    assert text == 2 + len(json.dumps(DETAILS, ensure_ascii=False))
    assert messages == before


def test_openrouter_plan_isolated_from_tinker_and_pinggy():
    plan = specification('openrouter')
    assert plan['model'] == MODEL and plan['base_url'] == BASE_URL
    assert plan['api_key_env'] == 'OPENROUTER_LTY_API_KEY'
    assert plan['generation_fields']['reasoning'] == {'enabled': True, 'effort': 'low'}
    assert plan['live_provider_check_required'] and plan['max_steps'] == 35


def test_openrouter_credential_does_not_fall_back_and_is_redacted(tmp_path, monkeypatch):
    from ui_kobe.osworld.telemetry import safe
    monkeypatch.delenv('OPENROUTER_LTY_API_KEY', raising=False)
    monkeypatch.setenv('TINKER_API_KEY', 'not-allowed')
    args = dict(profile=generation_profile(), budget=QwenTransportBudget(),
                emit=lambda *a, **k: None, response_dir=tmp_path)
    with pytest.raises(ValueError, match='OPENROUTER_LTY_API_KEY'):
        OpenRouterNativeClient(**args)
    monkeypatch.setenv('OPENROUTER_LTY_API_KEY', 'private-or-key')
    assert safe('echo private-or-key') == 'echo [REDACTED]'
