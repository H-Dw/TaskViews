from copy import deepcopy
import hashlib
import json
import threading
import time

import httpx
import pytest

from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.qwen_connection import ConnectionTrace, QwenConnectionUnavailable, exception_chain
from ui_kobe.api.qwen_native import MODEL, QwenNativeClient, QwenTransportBudget, generation_profile, transport_policy
from test_qwen_native_checkpoints import completed
from test_qwen_sse import valid_stream


def fail_connect(request, *, after_upload=False):
    callback = request.extensions['trace']
    callback('connection.connect_tcp.started', {'request': request, 'headers': {'Authorization': 'offline-secret'}})
    callback('connection.connect_tcp.complete', {})
    callback('connection.start_tls.started', {})
    if after_upload:
        callback('connection.start_tls.complete', {})
        callback('http11.send_request_headers.started', {})
        callback('http11.send_request_body.started', {})
    cause = ConnectionResetError(104, 'Connection reset by peer; offline-secret')
    callback('http11.send_request_body.failed' if after_upload else 'connection.start_tls.failed', {'exception': cause})
    try:
        raise cause
    except OSError as exc:
        raise httpx.ConnectError('Connection reset by peer; offline-secret', request=request) from exc


def make_client(tmp_path, handler, *, limit=3, streaming=False):
    profile = generation_profile('qwen-sse-low-total16k' if streaming else 'qwen-native-low-16k')
    ledger = StepLedger(profile, time.monotonic() + 930, lambda *a, **k: None)
    events, waits = [], []
    client = QwenNativeClient(api_key='offline-secret', budget=QwenTransportBudget(connect_reset_limit=limit),
        profile=profile, response_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append, emit=lambda name, **v: events.append((name, deepcopy(v), threading.current_thread().name)))
    def invoke():
        return client.create(model=MODEL, messages=[{'role': 'user', 'content': 'unchanged input'}],
            **{client.request_policy['output_field']: 16000}, step_ledger=ledger, budget_role='executor', deadline=ledger.deadline)
    return client, ledger, events, waits, invoke


@pytest.mark.parametrize('limit,attempts,waits', [(3, 3, [3, 6]), (0, 6, [3, 6, 12, 24, 48])])
def test_confirmed_tls_resets_stop_at_the_declared_circuit_and_preserve_unknown_usage(tmp_path, limit, attempts, waits):
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        fail_connect(request)
    client, ledger, events, slept, invoke = make_client(tmp_path, handler, limit=limit)
    try:
        with pytest.raises(QwenConnectionUnavailable if limit else httpx.ConnectError):
            invoke()
        assert len(sent) == attempts and slept == waits
        assert [r['max_tokens'] for r in sent] == [16000] + [3200] * (attempts - 1)
        assert ledger.charged_output == 16000 + 3200 * (attempts - 1)
        assert ledger.snapshot()['unknown_usage_requests'] == attempts
        outcomes = [v for name, v, _ in events if name == 'request_outcome']
        assert len(outcomes) == attempts and all(r['usage'] is None for r in outcomes)
        for outcome in outcomes:
            path = tmp_path / (outcome['request_id'] + '.transport.json')
            assert hashlib.sha256(path.read_bytes()).hexdigest() == outcome['transport_trace_sha256']
            trace = json.loads(path.read_text())
            assert trace['delivery'] == 'confirmed_no_origin_http_dispatch'
            assert trace['failure_phase'] == 'connection.start_tls.failed'
            assert trace['exception_chain'][-1]['errno'] == 104
            assert 'offline-secret' not in path.read_text() and 'Authorization' not in path.read_text()
        assert not any(name == 'api_response' for name, _, _ in events)
        assert sum(name == 'connection_circuit_open' for name, _, _ in events) == bool(limit)
    finally:
        client.close()


def test_two_transient_resets_can_recover_with_original_content_and_budgets(tmp_path):
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) < 3:
            fail_connect(request)
        return httpx.Response(200, json=completed())
    client, ledger, events, waits, invoke = make_client(tmp_path, handler)
    try:
        assert invoke().model_dump() == completed()
        assert waits == [3, 6] and len(sent) == 3
        assert all(r['messages'] == sent[0]['messages'] for r in sent)
        assert all(r['reasoning_effort'] == 'low' for r in sent)
        assert ledger.charged_output == 19210 and ledger.snapshot()['output_limit'] == 32000
        assert not any(name == 'connection_circuit_open' for name, _, _ in events)
    finally:
        client.close()


def test_upload_failure_or_missing_phase_evidence_never_claims_no_dispatch(tmp_path):
    for index, after_upload in enumerate((False, True)):
        calls = []
        def handler(request):
            calls.append(request)
            if after_upload:
                fail_connect(request, after_upload=True)
            raise httpx.ConnectError('Connection reset by peer', request=request)
        client, ledger, events, waits, invoke = make_client(tmp_path / str(index), handler)
        try:
            with pytest.raises(httpx.ConnectError):
                invoke()
            assert len(calls) == 6 and waits == [3, 6, 12, 24, 48]
            assert ledger.charged_output == 32000
            assert not any(name == 'connection_circuit_open' for name, _, _ in events)
        finally:
            client.close()


def test_sse_reader_trace_is_emitted_only_on_the_foreground_with_done_and_original_usage(tmp_path):
    callbacks = []
    def handler(request):
        callback = request.extensions['trace']
        callbacks.append(threading.current_thread().name)
        callback('connection.connect_tcp.complete', {})
        callback('connection.start_tls.complete', {})
        callback('http11.send_request_headers.started', {'request': request})
        callback('http11.send_request_body.complete', {})
        callback('http11.receive_response_headers.complete', {'return_value': {'secret': 'offline-secret'}})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=valid_stream())
    client, ledger, events, _, invoke = make_client(tmp_path, handler, streaming=True)
    try:
        body = invoke().model_dump()
        assert body['choices'][0]['message']['tool_calls'][0]['id'] == 'original-tool'
        assert callbacks == ['qwen-sse-reader']
        assert all(thread == threading.current_thread().name for _, _, thread in events)
        outcome = next(v for name, v, _ in events if name == 'request_outcome')
        assert outcome['stream_done'] and outcome['usage'] == body['usage']
        assert outcome['transport']['delivery'] == 'response_headers_received'
        assert ledger.snapshot()['known_usage']['total_tokens'] == 20
    finally:
        client.close()


def test_reset_streak_is_broken_by_a_different_failure(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) in (1, 2, 4, 5):
            fail_connect(request)
        if len(calls) == 3:
            raise httpx.ReadError('unknown upload outcome', request=request)
        return httpx.Response(200, json=completed())
    client, ledger, events, _, invoke = make_client(tmp_path, handler)
    try:
        assert invoke().model_dump() == completed()
        assert len(calls) == 6 and ledger.charged_output == 28810
        assert not any(name == 'connection_circuit_open' for name, _, _ in events)
    finally:
        client.close()


def test_trace_archive_failure_still_settles_usage_and_does_not_return_a_candidate(tmp_path, monkeypatch):
    from pathlib import Path
    original = Path.open
    def open_file(self, *args, **kwargs):
        if self.name.endswith('.transport.json'):
            raise OSError('trace archive unavailable')
        return original(self, *args, **kwargs)
    client, ledger, events, _, invoke = make_client(tmp_path, lambda _: httpx.Response(200, json=completed()))
    monkeypatch.setattr(Path, 'open', open_file)
    try:
        with pytest.raises(OSError, match='trace archive unavailable'):
            invoke()
        outcomes = [v for name, v, _ in events if name == 'request_outcome']
        assert len(outcomes) == 1 and outcomes[0]['usage'] == completed()['usage']
        assert outcomes[0]['transport_trace_path'] is None
        assert ledger.snapshot()['known_usage']['total_tokens'] == 110
        assert any(name == 'transport_trace_archive_error' for name, _, _ in events)
    finally:
        client.close()


def test_trace_keeps_first_failure_and_never_serializes_request_info():
    trace = ConnectionTrace('offline-secret')
    trace('http11.send_request_body.started', {'headers': {'Authorization': 'offline-secret'}})
    trace('http11.send_request_body.failed', {'exception': httpx.WriteError('SSL EOF offline-secret')})
    trace('http11.receive_response_headers.failed', {'exception': httpx.RemoteProtocolError('no response')})
    assert trace.snapshot()['failure_phase'] == 'http11.send_request_body.failed'
    assert not trace.confirmed_pre_http_reset(httpx.ConnectError('connection reset'))
    for _ in range(70):
        trace('http11.receive_response_body.complete', {'body': 'private'})
    saved = trace.snapshot()
    assert saved['events_truncated'] and len(saved['events']) == 64
    assert 'offline-secret' not in json.dumps(saved) and 'private' not in json.dumps(saved)


def test_exception_chain_is_redacted_and_cycle_bounded():
    error = httpx.ConnectError('offline-secret')
    error.__cause__ = error
    assert exception_chain(error, 'offline-secret') == [{'type': 'ConnectError', 'error': '[REDACTED]', 'errno': None}]


@pytest.mark.parametrize('limit', [-1, 7, True, 2.5])
def test_invalid_reset_limits_rejected(limit):
    with pytest.raises(ValueError):
        QwenTransportBudget(connect_reset_limit=limit)


def test_phase_policy_does_not_change_output_or_deadline_admission():
    policy = transport_policy()
    assert policy['version'] == 'qwen-phase-aware-retry-v2'
    assert policy['connection_reset_circuit']['consecutive_limit'] == 3
    assert policy['budget']['attempts'] == 6 and policy['budget']['total_s'] == 900
    assert policy['budget']['generation_s'] == 600 and policy['budget']['step_s'] == 930
