from copy import deepcopy
import json
import time

import httpx
import pytest

from scripts import verified_invoice
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import OutputTokenLimitError, ProviderQuotaBlocked, StreamProtocolError
from ui_kobe.api.qwen_native import QwenTransportBudget
from ui_kobe.api.tinker_native import BASE_URL, MODEL, TinkerNativeClient, generation_profile
from ui_kobe.osworld.cua_contract import options_contract


def response_bytes(*, done=True, finish='tool_calls', model=MODEL):
    def frame(delta=None, finish=None, usage=None):
        body = {'id': 'tinker-response', 'created': 1, 'model': model,
                'choices': [] if usage else [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
        if usage:
            body['usage'] = usage
        return ('data: ' + json.dumps(body) + '\n\n').encode()
    return (frame({'role': 'assistant', 'content': 'diagnostic', 'tool_calls': [
        {'index': 0, 'id': 'original-tool-id', 'type': 'function', 'function': {
            'name': 'computer_use', 'arguments': '{"action":"mouse_move","coordinate":[4,3]}'}}]})
        + frame(finish=finish)
        + frame(usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15})
        + (b'data: [DONE]\n\n' if done else b''))


def setup(tmp_path, handler, attempts=1):
    events, waits = [], []
    profile = generation_profile()
    ledger = StepLedger(profile, time.monotonic() + 930, lambda *a, **k: None)
    client = TinkerNativeClient(api_key='offline-tinker-secret', profile=profile,
        budget=QwenTransportBudget(attempts=attempts), response_dir=tmp_path,
        emit=lambda event, **fields: events.append({'event': event, **deepcopy(fields)}),
        sleep=waits.append, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, ledger, events, waits


def invoke(client, ledger, **extra):
    return client.create(model=MODEL, messages=extra.pop('messages', []), max_tokens=16000,
                         step_ledger=ledger, budget_role='executor', deadline=ledger.deadline, **extra)


def test_tinker_wire_endpoint_image_history_and_unmodified_tool_identity(tmp_path):
    requests = []
    def handler(request):
        assert str(request.url) == BASE_URL + '/chat/completions'
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=response_bytes())
    client, ledger, events, waits = setup(tmp_path, handler)
    history = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]},
               {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'old', 'type': 'function',
                 'function': {'name': 'computer_use', 'arguments': '{}'}}]},
               {'role': 'tool', 'tool_call_id': 'old', 'content': 'diagnostic'}]
    try:
        result = invoke(client, ledger, messages=history).model_dump()
        payload = requests[0]
        assert payload['messages'] == history
        assert payload['model'] == MODEL and payload['max_tokens'] == 16000
        assert payload['reasoning_effort'] == 'low' and payload['separate_reasoning'] is True
        assert payload['stream_options'] == {'include_usage': True}
        assert not any(k in payload for k in ('enable_thinking', 'preserve_thinking', 'max_completion_tokens'))
        assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'original-tool-id'
        assert ledger.usage['completion_tokens'] == 5 and not waits
        assert next(tmp_path.glob('*.sse')).read_bytes() == response_bytes()
        assert any(e['event'] == 'api_response' for e in events)
    finally:
        client.close()


@pytest.mark.parametrize('status,error', [(402, ProviderQuotaBlocked), (400, httpx.HTTPStatusError),
                                         (401, httpx.HTTPStatusError), (403, httpx.HTTPStatusError)])
def test_billing_or_unsupported_settings_stop_without_fallback_or_retry(tmp_path, status, error):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(status, json={'detail': 'failure offline-tinker-secret'})
    client, ledger, events, waits = setup(tmp_path, handler, attempts=6)
    try:
        with pytest.raises(error):
            invoke(client, ledger)
        assert len(seen) == 1 and not waits
        assert not any(e['event'] == 'api_response' for e in events)
        assert all('offline-tinker-secret' not in p.read_text() for p in tmp_path.iterdir())
        assert 'offline-tinker-secret' not in json.dumps(events)
        assert ledger.snapshot()['unknown_usage_requests'] == 1
    finally:
        client.close()


@pytest.mark.parametrize('mutation,error', [('missing_done', StreamProtocolError),
                                          ('wrong_model', StreamProtocolError), ('length', OutputTokenLimitError)])
def test_incomplete_or_wrong_model_response_cannot_be_executed(tmp_path, mutation, error):
    raw = response_bytes(done=mutation != 'missing_done', finish='length' if mutation == 'length' else 'tool_calls',
                         model='qwen3.8-max' if mutation == 'wrong_model' else MODEL)
    client, ledger, events, _ = setup(tmp_path, lambda _: httpx.Response(
        200, headers={'content-type': 'text/event-stream'}, content=raw))
    try:
        with pytest.raises(error):
            invoke(client, ledger)
        assert not any(e['event'] == 'api_response' for e in events)
    finally:
        client.close()


def test_no_qwen_credential_fallback_and_no_implicit_proxy(tmp_path, monkeypatch):
    monkeypatch.delenv('TINKER_API_KEY', raising=False)
    monkeypatch.setenv('QWEN_API_KEY', 'must-not-be-used')
    args = dict(profile=generation_profile(), budget=QwenTransportBudget(),
                emit=lambda *a, **k: None, response_dir=tmp_path)
    with pytest.raises(ValueError, match='TINKER_API_KEY'):
        TinkerNativeClient(**args)
    monkeypatch.setenv('TINKER_API_KEY', 'offline-tinker-secret')
    client = TinkerNativeClient(**args)
    try:
        assert client.key == 'offline-tinker-secret' and client.client._trust_env is False
    finally:
        client.close()


def test_tinker_profile_and_live_launch_gate(tmp_path):
    plan = verified_invoice.specification('tinker')
    assert plan['model'] == MODEL and plan['base_url'] == BASE_URL
    assert plan['api_key_env'] == 'TINKER_API_KEY'
    assert plan['max_steps'] == 35 and plan['arms'] == ['ui_kobe_like', 'taskviews']
    assert plan['arm_profiles']['taskviews']['view_ids'] == ['current', 'attempts', 'lessons']
    _, budget, _, _ = options_contract({}, provider='tinker', generation_profile=generation_profile())
    assert budget.attempts == 6
    plan['project_source'] = {'test': 'hash'}
    proof = {k: plan[k] for k in ('project_source', 'model', 'base_url', 'generation_fields', 'cua_contract')}
    proof.update(complete=False, checks=['text'])
    verified_invoice.write(tmp_path / 'live-provider-check.json', proof)
    with pytest.raises(ValueError, match='incomplete'):
        verified_invoice.require_live_provider_check(tmp_path, plan)
    proof.update(complete=True, checks=['text', 'vision_native_tool', 'tool_reply'])
    verified_invoice.write(tmp_path / 'live-provider-check.json', proof)
    verified_invoice.require_live_provider_check(tmp_path, plan)


def test_tinker_secret_redaction(monkeypatch):
    from ui_kobe.osworld.telemetry import safe
    monkeypatch.setenv('TINKER_API_KEY', 'offline-tinker-secret')
    assert safe({'error': 'echo offline-tinker-secret'}) == {'error': 'echo [REDACTED]'}
