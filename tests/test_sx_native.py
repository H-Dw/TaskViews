import json
import time

import httpx
import pytest

from scripts.verified_invoice import specification
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import StreamProtocolError
from ui_kobe.api.qwen_native import QwenTransportBudget
from ui_kobe.api.sx_native import MODEL, SXSSE, SXNativeClient, generation_profile, resolve_base_url


def frame(created, delta=None, finish=None, **extra):
    return ('data: ' + json.dumps({'id': 'sx-original-id', 'model': MODEL, 'created': created,
        'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}], **extra}) + '\n\n').encode()


def stream():
    return (frame(100, {'role': 'assistant', 'reasoning_content': 'fixture'})
            + frame(101, {'content': 'OK'}) + frame(102, finish='stop')
            + b'data: [DONE]\n\n')


def test_per_chunk_created_is_audited_without_relaxing_response_identity():
    parser = SXSSE(MODEL)
    parser.feed(stream(), final=True)
    body = parser.complete()
    assert body['created'] == 100 and body['choices'][0]['message']['content'] == 'OK'
    assert body['sx_stream_metadata'] == {'created_semantics': 'per_chunk_timestamp',
        'first_created': 100, 'last_created': 102, 'timestamp_changes': 2}


@pytest.mark.parametrize('bad', [frame(101, id='other-response'), frame(101, model='qwen3.8-max'),
                                frame(99), frame('101')])
def test_bad_identity_or_timestamps_fail_closed(bad):
    parser = SXSSE(MODEL)
    parser.feed(frame(100, {'role': 'assistant'}) + bad + b'data: [DONE]\n\n', final=True)
    with pytest.raises(StreamProtocolError):
        parser.complete()


@pytest.mark.parametrize('value,expected', [('https://sx.example', 'https://sx.example/v1'),
    ('https://sx.example/v1/', 'https://sx.example/v1'), ('https://sx.example/api/v1', 'https://sx.example/api/v1')])
def test_url_comes_from_selected_environment_without_duplicate_v1(monkeypatch, value, expected):
    monkeypatch.setenv('SX_URL_SB', value)
    monkeypatch.setenv('SX_URL', 'https://wrong.example')
    assert resolve_base_url('SX_URL_SB') == expected


@pytest.mark.parametrize('value', ['', 'http://sx.example', 'https://key@sx.example',
                                  'https://sx.example?key=secret', 'https://sx.example/v1/chat/completions'])
def test_invalid_url_rejected_before_credentials_can_be_sent(monkeypatch, value):
    monkeypatch.setenv('SX_URL_SB', value)
    with pytest.raises(ValueError):
        resolve_base_url('SX_URL_SB')


def test_request_and_raw_archive_use_only_sx_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('SX_URL_SB', 'https://sx.example')
    monkeypatch.setenv('SX_QWEN_API_KEY', 'fixture-secret')
    profile = generation_profile()
    ledger = StepLedger(profile, time.monotonic()+930, lambda *a, **k: None)
    payloads = []
    def handler(request):
        assert str(request.url) == 'https://sx.example/v1/chat/completions'
        body = json.loads(request.content)
        payloads.append(body)
        assert body['model'] == MODEL and body['max_tokens'] == 16000
        assert body['reasoning_effort'] == 'low' and body['stream']
        assert all(k not in body for k in ('preserve_thinking', 'enable_thinking', 'separate_reasoning', 'reasoning'))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=stream())
    client = SXNativeClient(url_env='SX_URL_SB', profile=profile, budget=QwenTransportBudget(attempts=1),
        emit=lambda *a, **k: None, response_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        result = client.create(model=MODEL, messages=[], max_tokens=16000,
            step_ledger=ledger, budget_role='executor', deadline=ledger.deadline)
        assert result.model_dump()['created'] == 100 and len(payloads) == 1
        assert next(tmp_path.glob('*.sse')).read_bytes() == stream()
    finally:
        client.close()


def test_sx_freezes_model_url_env_and_shared_comparison_contract(monkeypatch):
    monkeypatch.setenv('SX_URL_SB', 'https://sx.example')
    plan = specification('sx', 'SX_URL_SB')
    assert plan['model'] == MODEL and plan['base_url'] == 'https://sx.example/v1'
    assert plan['base_url_env'] == 'SX_URL_SB' and plan['api_key_env'] == 'SX_QWEN_API_KEY'
    assert plan['max_steps'] == 35 and plan['arms'] == ['ui_kobe_like', 'taskviews']
    assert plan['live_provider_check_required']
    from ui_kobe.osworld.taskviews_profiles import mini_cua_contract
    previous = mini_cua_contract()
    assert plan['cua_contract']['context_max_payload_chars'] == 12_000_000
    assert {k: v for k, v in plan['cua_contract'].items() if k != 'context_max_payload_chars'} == {
        k: v for k, v in previous.items() if k != 'context_max_payload_chars'}


def test_sx_envelope_fits_existing_maximum_png_without_more_text_or_images(monkeypatch):
    from ui_kobe.api.qwen_png_transport import MAX_PNG_BYTES, PREFIX
    from ui_kobe.osworld.native_history import context_size
    monkeypatch.setenv('SX_URL', 'https://sx.example')
    contract = specification('sx')['cua_contract']
    url = PREFIX + 'A' * (4 * ((MAX_PNG_BYTES + 2) // 3))
    payload, text = context_size([{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': url}},
        {'type': 'text', 'text': 'fixture'}]}])
    assert payload > 2_000_000
    assert payload + contract['context_max_text_chars'] + contract['context_reserve_chars'] < contract['context_max_payload_chars']
    assert text == 7 and contract['image_max'] == 1


def test_sx_does_not_fall_back_to_other_credentials_and_redacts_its_key(tmp_path, monkeypatch):
    from ui_kobe.osworld.telemetry import safe
    monkeypatch.setenv('SX_URL', 'https://sx.example')
    monkeypatch.delenv('SX_QWEN_API_KEY', raising=False)
    monkeypatch.setenv('QWEN_API_KEY', 'wrong-provider')
    with pytest.raises(ValueError, match='SX_QWEN_API_KEY'):
        SXNativeClient(profile=generation_profile(), budget=QwenTransportBudget(),
                       emit=lambda *a, **k: None, response_dir=tmp_path)
    monkeypatch.setenv('SX_QWEN_API_KEY', 'fixture-secret')
    assert safe('echo fixture-secret') == 'echo [REDACTED]'
