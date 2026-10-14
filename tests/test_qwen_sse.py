from copy import deepcopy
import hashlib
import json
import time

import httpx
import pytest

from scripts.taskviews_recovery import configure_qwen_streaming
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import OutputTokenLimitError, ProviderQuotaBlocked, StreamProtocolError
from ui_kobe.api.qwen_native import MODEL, QwenNativeClient, QwenTransportBudget, generation_profile, streaming_migration_matches
from ui_kobe.api.qwen_sse import QwenSSE, response_events
from ui_kobe.osworld.cua_contract import options_contract
from ui_kobe.osworld.qwen_native_base import QwenTransitionNativeAgent
from ui_kobe.osworld.transitions import TransitionJournal
from test_mini_profiles import TASK, make_actor, manager, predict
from test_qwen_reasoning import migration_inputs


def frame(delta=None, finish=None, usage=None, **extra):
    value = {'id': 'original-response', 'model': MODEL, 'created': 123,
             'choices': [] if usage else [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}], **extra}
    if usage:
        value['usage'] = usage
    return ('data: ' + json.dumps(value, ensure_ascii=False) + '\r\n\r\n').encode()


USAGE = {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20,
         'completion_tokens_details': {'reasoning_tokens': 5}, 'prompt_tokens_details': {'cached_tokens': 4}}


def valid_stream(finish='tool_calls', done=True, usage=True):
    return (b': keepalive\r\n\r\n' + frame({'role': 'assistant', 'reasoning_content': '原始推理'})
            + frame({'content': 'public'})
            + frame({'tool_calls': [{'index': 0, 'id': 'original-tool', 'type': 'function',
                'function': {'name': 'computer_use', 'arguments': '{"action":"key",'}}]})
            + frame({'tool_calls': [{'index': 0, 'function': {'arguments': '"keys":["enter"]}'}}]})
            + frame(finish=finish) + (frame(usage=USAGE) if usage else b'')
            + (b'data: [DONE]\r\n\r\n' if done else b''))


def client_for(tmp_path, handler, attempts=6, effort='xhigh'):
    profile = generation_profile(f'qwen-sse-{effort}-total16k')
    events, waits = [], []
    ledger = StepLedger(profile, time.monotonic()+930, lambda *a, **k: None)
    client = QwenNativeClient(api_key='offline-key', profile=profile, budget=QwenTransportBudget(attempts=attempts),
        emit=lambda event, **data: events.append({'event': event, **deepcopy(data)}), response_dir=tmp_path,
        sleep=waits.append, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, ledger, events, waits


def invoke(client, ledger, messages=None):
    return client.create(model=MODEL, messages=messages or [], max_completion_tokens=16000,
                         step_ledger=ledger, budget_role='executor', deadline=ledger.deadline)


@pytest.mark.parametrize('effort', ['low', 'high', 'xhigh'])
def test_fragmented_utf8_tools_reasoning_usage_and_exact_raw_archive(tmp_path, effort):
    raw = valid_stream()
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            yield from (raw[i:i+1] for i in range(len(raw)))
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream;charset=UTF-8'}, stream=Bytes())
    client, ledger, events, waits = client_for(tmp_path, handler, effort=effort)
    history = [{'role': 'assistant', 'content': 'original', 'reasoning_content': 'separate private',
                'tool_calls': [{'id': 'old-id', 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{}'}}]},
               {'role': 'tool', 'tool_call_id': 'old-id', 'content': 'original error'}]
    try:
        body = invoke(client, ledger, history).model_dump()
        assert body['choices'][0]['message']['reasoning_content'] == '原始推理'
        assert body['choices'][0]['message']['content'] == 'public'
        assert body['choices'][0]['message']['tool_calls'][0]['id'] == 'original-tool'
        assert body['usage'] == USAGE and ledger.snapshot()['known_usage']['completion_tokens'] == 8
        assert requests[0]['messages'] == history and 'max_tokens' not in requests[0]
        assert requests[0]['max_completion_tokens'] == 16000 and requests[0]['stream'] is True
        assert requests[0]['reasoning_effort'] == effort and requests[0]['preserve_thinking'] is True
        assert requests[0]['stream_options'] == {'include_usage': True} and not waits
        assert next(tmp_path.glob('*.sse')).read_bytes() == raw
        outcome = next(e for e in events if e['event'] == 'request_outcome')
        assert outcome['stream_done'] and outcome['stream'] and outcome['usage'] == USAGE
        assert outcome['raw_response_sha256'] == hashlib.sha256(raw).hexdigest()
    finally:
        client.close()


@pytest.mark.parametrize('mutation', ['missing_done', 'after_done', 'conflicting_id', 'bad_arguments', 'invalid_utf8', 'wrong_model'])
def test_incomplete_or_corrupted_stream_never_completes(mutation):
    raw = valid_stream()
    if mutation == 'missing_done':
        raw = valid_stream(done=False)
    elif mutation == 'after_done':
        raw += frame({'content': 'late'})
    elif mutation == 'conflicting_id':
        raw = frame(id='other-response') + raw
    elif mutation == 'bad_arguments':
        raw = raw.replace(b'enter', b'enter\\"')
    elif mutation == 'invalid_utf8':
        raw = b'\xff' + raw
    else:
        raw = raw.replace(MODEL.encode(), b'wrong-model')
    acc = QwenSSE(MODEL)
    with pytest.raises((StreamProtocolError, UnicodeError)):
        acc.feed(raw, final=True)
        acc.complete()


def test_length_still_settles_reasoning_usage_without_returning_candidate(tmp_path):
    client, ledger, events, waits = client_for(tmp_path, lambda _: httpx.Response(
        200, headers={'content-type': 'text/event-stream'}, content=valid_stream(finish='length')))
    try:
        with pytest.raises(OutputTokenLimitError):
            invoke(client, ledger)
        assert not waits and ledger.snapshot()['known_usage']['completion_tokens'] == 8
        assert not any(e['event'] == 'api_response' for e in events)
    finally:
        client.close()


def test_missing_done_retries_with_original_output_pool_and_unknown_usage(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        raw = valid_stream(done=False, usage=False) if len(requests) == 1 else valid_stream()
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=raw)
    client, ledger, events, waits = client_for(tmp_path, handler)
    try:
        invoke(client, ledger)
        assert [p['max_completion_tokens'] for p in requests] == [16000, 3200]
        outcomes = [e for e in events if e['event'] == 'request_outcome']
        assert outcomes[0]['usage'] is None and not outcomes[0]['stream_done']
        assert outcomes[1]['usage'] == USAGE and waits == [3]
        assert ledger.charged_output == 16008
    finally:
        client.close()


@pytest.mark.parametrize('sse', [False, True])
def test_quota_error_json_and_stream_stop_without_retry(tmp_path, sse):
    body = {'success': False, 'error': {'code': 'insufficient_quota'}, 'choices': [{'index': 0}]}
    def handler(_):
        return httpx.Response(200, headers={'content-type': 'text/event-stream' if sse else 'application/json'},
                              content=('data: '+json.dumps(body)+'\n\n').encode() if sse else json.dumps(body).encode())
    client, ledger, events, waits = client_for(tmp_path, handler)
    try:
        with pytest.raises(ProviderQuotaBlocked):
            invoke(client, ledger)
        assert not waits and sum(e['event'] == 'api_request' for e in events) == 1
    finally:
        client.close()


def test_wall_deadline_stops_silent_reader_without_second_request():
    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.3)
            yield b'data: [DONE]\n\n'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Slow()))) as client:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            list(response_events(client, 'https://offline.invalid', {}, httpx.Timeout(1), start+0.04))
        assert time.monotonic()-start < 0.25
        time.sleep(0.3)  # Allow the offline reader to exit before fixture teardown.


def test_stream_profile_uses_total_field_from_shared_actor():
    from types import SimpleNamespace
    from ui_kobe.osworld.qwen_native_base import QwenNativeProvider
    actor = QwenNativeProvider()
    actor.profile = generation_profile('qwen-sse-xhigh-total16k')
    ledger = SimpleNamespace(allowance=lambda role: 16000)
    assert actor.generation_fields(ledger, 'executor') == {'max_completion_tokens': 16000}


def test_over_cap_usage_is_recorded_but_candidate_is_not_returned(tmp_path):
    raw = valid_stream().replace(json.dumps(USAGE).encode(), json.dumps({**USAGE, 'completion_tokens':16001, 'total_tokens':16013}).encode())
    client, ledger, events, waits = client_for(tmp_path, lambda _: httpx.Response(200,
        headers={'content-type':'text/event-stream'}, content=raw))
    try:
        with pytest.raises(OutputTokenLimitError):
            invoke(client, ledger)
        assert ledger.charged_output == 16001 and not waits
        assert not any(e['event'] == 'api_response' for e in events)
    finally:
        client.close()


def test_nested_error_is_not_hidden_by_choices():
    from ui_kobe.api.qwen_native import provider_error
    body = {'choices':[{'index':0}], 'message':json.dumps({'error':{'code':'insufficient_quota'}})}
    assert provider_error(body) == 'insufficient_quota'
    acc = QwenSSE(MODEL)
    acc.add(json.dumps(body))
    assert acc.provider_failure == body


def test_streaming_migration_preserves_budgets_and_rejects_wrong_checkpoint():
    plan, manifest, saved = migration_inputs()
    before = generation_profile('qwen-native-xhigh-16k').__dict__
    for obj in (plan, manifest, saved):
        obj['generation_profile'] = deepcopy(before)
    manifest['official_arguments'] = ['--enable_thinking', '--no-stream']
    original = deepcopy(saved)
    configure_qwen_streaming(plan, manifest, saved)
    assert saved == original and manifest['official_arguments'] == ['--enable_thinking', '--stream']
    after = manifest['generation_profile']
    assert {k:v for k,v in before.items() if k != 'name'} == {k:v for k,v in after.items() if k != 'name'}
    migration = manifest['qwen_streaming_migration']
    assert streaming_migration_matches(migration, tag=saved['tag'], before=before, after=after)
    assert not streaming_migration_matches(migration, tag='wrong-tag', before=before, after=after)
    assert not streaming_migration_matches(migration, tag=saved['tag'], before=before, after={**after, 'step_output_tokens':64000})
    options_contract({'stream': True, 'enable_thinking': True}, provider='qwen', generation_profile=generation_profile(after['name']))
    with pytest.raises(ValueError, match='stream'):
        options_contract({'stream': False}, provider='qwen', generation_profile=generation_profile(after['name']))


def test_checkpoint_streaming_restore_is_exact_and_does_not_rewrite_history(tmp_path, monkeypatch):
    actor, obs, _ = make_actor(monkeypatch, tmp_path/'first', cls=QwenTransitionNativeAgent)
    actor.profile = generation_profile('qwen-native-xhigh-16k')
    actor.execution_journal = TransitionJournal(tmp_path/'journal', task_id='059', run_id='offline-stream', contract=actor.contract)
    predict(actor, obs)
    cp = manager(tmp_path, 'ui_kobe_like')
    tag = cp.save(actor, TASK, obs)
    _, saved = cp.read(tag, metadata_only=True)
    restored, _, _ = make_actor(monkeypatch, tmp_path/'second', cls=QwenTransitionNativeAgent)
    restored.profile = generation_profile('qwen-sse-xhigh-total16k')
    with pytest.raises(ValueError, match='contract changed'):
        cp.restore_agent(restored)
    cp.manifest.update(agent_interface='qwen-native', qwen_streaming_migration={
        'version':'qwen-streaming-migration-v1', 'checkpoint':tag,
        'before':saved['generation_profile'], 'after':restored.profile.__dict__})
    cp.restore_agent(restored)
    assert restored.turns == actor.turns and restored.pending == actor.pending and restored.total_steps == 1
    assert cp.read(tag, metadata_only=True)[1]['generation_profile'] == saved['generation_profile']
    actor.close()
    restored.close()
