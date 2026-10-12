from copy import deepcopy
import json
import time

import httpx
import pytest

from scripts.taskviews_recovery import configure_qwen_transport_retry
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import ProviderQuotaBlocked, StreamBudget
from ui_kobe.api.qwen_native import MODEL, QwenGenerationProfile, QwenNativeClient, QwenTransportBudget, transport_policy
from ui_kobe.osworld.cua_contract import options_contract
from test_qwen_native_checkpoints import completed


def client_for(tmp_path, handler, role='executor', sleep=None):
    events, waits = [], []
    ledger = StepLedger(QwenGenerationProfile(), time.monotonic() + 930, lambda *a, **k: None)
    client = QwenNativeClient(api_key='offline-key', budget=QwenTransportBudget(), profile=ledger.profile,
        emit=lambda event, **data: events.append({'event': event, **deepcopy(data)}), response_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleep or waits.append)
    def request():
        return client.create(model=MODEL, messages=[{'role': 'user', 'content': 'original'}],
            max_tokens=ledger.allowance(role), budget_role=role, deadline=ledger.deadline, step_ledger=ledger)
    return client, ledger, events, waits, request


@pytest.mark.parametrize('role,caps,charged', [('executor', [16000] + [3200]*5, 28810),
                                            ('perception', [4000] + [2400]*5, 13610)])
def test_five_unknown_disconnects_can_recover_without_larger_output_pool(tmp_path, role, caps, charged):
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) <= 5:
            raise httpx.RemoteProtocolError('remote disconnect', request=request)
        return httpx.Response(200, json=completed())
    client, ledger, events, waits, request = client_for(tmp_path, handler, role)
    try:
        assert request().model_dump() == completed()
        assert [p['max_tokens'] for p in payloads] == caps
        assert all({k: v for k, v in p.items() if k != 'max_tokens'} ==
                   {k: v for k, v in payloads[0].items() if k != 'max_tokens'} for p in payloads)
        assert waits == [3, 6, 12, 24, 48]
        outcomes = [e for e in events if e['event'] == 'request_outcome']
        assert len({e['request_id'] for e in outcomes}) == 6
        assert [e['usage'] for e in outcomes[:-1]] == [None]*5
        assert outcomes[-1]['usage'] == completed()['usage']
        assert ledger.charged_output == charged and ledger.snapshot()['output_limit'] == 32000
        assert ledger.snapshot()['unknown_usage_requests'] == 5
        assert ledger.repair_counts == {'executor': 0, 'advisory': 0}
    finally:
        client.close()


def test_six_attempt_exhaustion_settles_all_unknown_reservations_and_stops(tmp_path):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ConnectError('connection reset', request=request)
    client, ledger, events, waits, request = client_for(tmp_path, handler)
    try:
        with pytest.raises(httpx.ConnectError):
            request()
        assert count == 6 and waits == [3, 6, 12, 24, 48]
        assert ledger.charged_output == 32000 and ledger.snapshot()['unknown_usage_requests'] == 6
        assert not any(e['event'] == 'api_response' for e in events)
        assert all(e['usage'] is None for e in events if e['event'] == 'request_outcome')
        assert sum(e['event'] == 'request_outcome' for e in events) == 6
    finally:
        client.close()


@pytest.mark.parametrize('failure', [httpx.ConnectTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError])
def test_transient_network_failures_retry_but_do_not_modify_native_history(tmp_path, failure):
    count = 0
    def handler(req):
        nonlocal count
        count += 1
        if count == 1:
            raise failure('transient network error', request=req)
        return httpx.Response(200, json=completed())
    client, ledger, events, waits, request = client_for(tmp_path, handler)
    try:
        assert request().model_dump() == completed()
        assert count == 2 and waits == [3] and ledger.snapshot()['unknown_usage_requests'] == 1
        assert events[0]['payload']['messages'] == [{'role': 'user', 'content': 'original'}]
    finally:
        client.close()


def test_quota_and_local_protocol_errors_still_stop_immediately(tmp_path):
    for index, quota in enumerate((False, True)):
        def handler(req):
            if quota:
                return httpx.Response(429, json={'error': {'code': 'insufficient_quota'}})
            raise httpx.LocalProtocolError('invalid request', request=req)
        client, ledger, events, waits, request = client_for(tmp_path / str(index), handler)
        try:
            with pytest.raises(ProviderQuotaBlocked if quota else httpx.LocalProtocolError):
                request()
            assert waits == [] and sum(e['event'] == 'api_request' for e in events) == 1
        finally:
            client.close()


def test_backoff_cannot_cross_existing_role_deadline(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    def handler(req):
        clock[0] += 2
        raise httpx.ConnectError('transient', request=req)
    client, ledger, events, waits, request = client_for(tmp_path, handler, sleep=lambda delay: clock.__setitem__(0, clock[0]+delay))
    ledger.deadline = 130
    try:
        with pytest.raises(httpx.ConnectError):
            request()
        assert [e['attempt'] for e in events if e['event'] == 'api_request'] == [1, 2, 3]
        assert clock[0] == 115 and sum(e['event'] == 'request_outcome' for e in events) == 3
    finally:
        client.close()


def test_default_qwen_uses_fresh_connections_and_kimi_keeps_two_attempts(tmp_path, monkeypatch):
    original, kwargs = httpx.Client, []
    def factory(**options):
        kwargs.append(options)
        return original(**options, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=completed())))
    monkeypatch.setattr(httpx, 'Client', factory)
    client = QwenNativeClient(api_key='offline-key', budget=QwenTransportBudget(), profile=QwenGenerationProfile(),
        emit=lambda *a, **k: None, response_dir=tmp_path)
    try:
        assert kwargs[0]['limits'].max_keepalive_connections == 0
        assert options_contract({}, provider='qwen')[1].attempts == 6
        assert options_contract({})[1].attempts == 2
        with pytest.raises(ValueError):
            StreamBudget(attempts=6)
    finally:
        client.close()


@pytest.mark.parametrize('value', [0, 7, True, 2.5])
def test_invalid_qwen_retry_limit_is_rejected(value):
    with pytest.raises(ValueError):
        QwenTransportBudget(attempts=value)


def test_transport_migration_changes_only_retry_policy_and_one_original_flag():
    plan = {'agent_interface': 'qwen-native', 'cua_contract': {'history_n': 20}}
    manifest = {'agent_interface': 'qwen-native', 'official_arguments':
        ['--max_steps', '500', '--max_api_retries', '2', '--model', MODEL]}
    before = deepcopy(manifest)
    configure_qwen_transport_retry(plan, manifest, 6)
    assert manifest['official_arguments'] == ['--max_steps', '500', '--max_api_retries', '6', '--model', MODEL,
                                              '--retry_sleep_base', '3', '--retry_sleep_cap', '60']
    assert plan['qwen_transport_policy'] == manifest['qwen_transport_policy'] == transport_policy()
    assert plan['stream_budget']['total_s'] == 900 and plan['stream_budget']['step_s'] == 930
    assert before['official_arguments'][3] == '2' and plan['cua_contract'] == {'history_n': 20}
    for args in ([], ['--max_api_retries', '2', '--max_api_retries', '2']):
        with pytest.raises(RuntimeError):
            configure_qwen_transport_retry(plan, {**manifest, 'official_arguments': args}, 6)
    with pytest.raises(ValueError):
        configure_qwen_transport_retry(plan, {**manifest, 'agent_interface': 'k3-native'}, 6)


def test_qwen_backoff_options_match_explicit_migrated_arguments():
    from scripts.osworld_native_experiment import official_arguments, ROOT
    args = official_arguments('059', ROOT / 'results/offline', provider='qwen')
    assert args[args.index('--max_api_retries') + 1] == '6'
    assert args[args.index('--retry_sleep_cap') + 1] == '60'
    assert options_contract({'max_api_retries': 6, 'retry_sleep_base': 3, 'retry_sleep_cap': 60}, provider='qwen')[1].attempts == 6
    assert options_contract({'max_api_retries': 2, 'retry_sleep_cap': 15}, provider='qwen')[1].attempts == 2
    with pytest.raises(ValueError, match='cap=60'):
        options_contract({'max_api_retries': 6, 'retry_sleep_cap': 15}, provider='qwen')
