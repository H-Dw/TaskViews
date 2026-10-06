import json
import time
from io import BytesIO

import httpx
import pytest
from PIL import Image

from ui_kobe.api.kimi import K3Requests, generation_profile
from ui_kobe.api.kimi_budget import StepLedger, StepTokenBudgetError
from ui_kobe.api.kimi_stream import KimiStreamClient, OutputTokenLimitError
from ui_kobe.osworld.kimi_native import KimiNativeAgent


def sse(*, length=False, used=7, content=None, tool=True, usage=True):
    delta = {'reasoning_content': 'original reasoning'}
    if content is not None:
        delta['content'] = content
    if tool:
        delta['tool_calls'] = [{'index': 0, 'id': 'original-id', 'type': 'function', 'function': {
            'name': 'computer_use', 'arguments': '{"action":"mouse_move","coordinate":[100,200]}'}}]
    rows = [{'id': 'completion-id', 'model': 'kimi-k3', 'choices': [{'index': 0, 'delta': delta,
             'finish_reason': 'length' if length else ('tool_calls' if tool else 'stop')}]}]
    if usage:
        rows.append({'id': 'completion-id', 'model': 'kimi-k3', 'choices': [],
                     'usage': {'prompt_tokens': 100, 'completion_tokens': used, 'total_tokens': 100 + used,
                               'completion_tokens_details': {'reasoning_tokens': used if length else 2}}})
    return ''.join('data: ' + json.dumps(row) + '\n\n' for row in rows) + 'data: [DONE]\n\n'


def transport(handler, profile, events, tmp_path):
    return KimiStreamClient(api_key='offline-secret', profile=profile, stream_dir=tmp_path,
        emit=lambda name, **fields: events.append((name, fields)),
        http_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.parametrize('name,effort,cap', [('low-16k', 'low', 16000), ('max-16k', 'max', 16000), ('max-32k', 'max', 32768)])
def test_frozen_profile_reaches_wire_and_rejects_mismatched_effort(name, effort, cap, tmp_path):
    profile = generation_profile(name)
    sent, events = [], []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text=sse())
    client = transport(handler, profile, events, tmp_path)
    client.create(messages=[], max_completion_tokens=cap)
    assert sent[0]['reasoning_effort'] == effort
    assert sent[0]['max_completion_tokens'] == cap
    with pytest.raises(ValueError, match='effort'):
        K3Requests(profile=profile).prepare({'model': 'kimi-k3', 'reasoning_effort': 'high'})


def test_length_keeps_observed_response_usage_and_cannot_be_executed(tmp_path):
    events = []
    profile = generation_profile()
    ledger = StepLedger(profile, time.monotonic() + 50, lambda *a, **k: None)
    client = transport(lambda request: httpx.Response(200, text=sse(length=True, used=16000, tool=False)), profile, events, tmp_path)
    with pytest.raises(OutputTokenLimitError) as caught:
        client.create(messages=[], step_ledger=ledger, max_completion_tokens=16000)
    assert caught.value.code == 'output_token_limit'
    assert caught.value.observed_response['choices'][0]['message']['content'] is None
    assert caught.value.observed_response['usage']['completion_tokens'] == 16000
    assert not any(name == 'api_response' for name, _ in events)
    outcome = next(data for name, data in events if name == 'request_outcome')
    assert outcome['stream_done'] and outcome['finish_reason'] == 'length'
    assert outcome['usage']['total_tokens'] == 16100
    assert outcome['observed_response']['choices'][0]['message']['reasoning_content'] == 'original reasoning'
    assert ledger.snapshot()['known_usage']['total_tokens'] == 16100
    assert len(list(tmp_path.glob('*.jsonl'))) == 1


def test_advisers_cannot_spend_executor_reserve_and_unknown_usage_is_charged():
    ledger = StepLedger(generation_profile(), time.monotonic() + 50, lambda *a, **k: None)
    for i in range(4):
        ledger.reserve(str(i), 'adviser', 4000)
        ledger.settle(str(i), None)
    with pytest.raises(StepTokenBudgetError):
        ledger.allowance('adviser')
    assert ledger.allowance('executor') == 16000
    assert ledger.snapshot()['known_usage']['total_tokens'] == 0
    assert ledger.snapshot()['unknown_usage_requests'] == 4
    ledger.reserve('actor', 'executor', 16000)
    ledger.settle('actor', {'prompt_tokens': 100, 'completion_tokens': 16000, 'total_tokens': 16100})
    assert not ledger.regenerate('executor', 15)


def test_usage_not_double_counted_and_actor_repairs_reserved_from_advisers():
    ledger = StepLedger(generation_profile(), time.monotonic() + 50, lambda *a, **k: None)
    ledger.reserve('one', 'planner', 4000)
    measured = {'prompt_tokens': 50, 'completion_tokens': 1000, 'total_tokens': 1050}
    ledger.settle('one', measured)
    assert ledger.charged_output == 1000
    with pytest.raises(RuntimeError):
        ledger.settle('one', measured)
    assert ledger.regenerate('planner', 15)
    assert ledger.regenerate('executor', 15)
    assert ledger.regenerate('executor', 15)
    assert not ledger.regenerate('executor', 15)
    assert ledger.regenerate('perception', 15)
    assert not ledger.regenerate('verifier', 15)
    assert ledger.repair_counts == {'executor': 2, 'advisory': 2}
    ledger.deadline = time.monotonic() - 1
    with pytest.raises(StepTokenBudgetError):
        ledger.allowance('executor')


def test_short_remaining_deadline_prevents_regeneration():
    ledger = StepLedger(generation_profile(), time.monotonic() + 5, lambda *a, **k: None)
    assert not ledger.regenerate('executor', 15)
    assert ledger.regenerations == 0


def test_max_profile_is_passed_to_official_runner_arguments(tmp_path):
    from scripts.osworld_native_experiment import official_arguments
    args = official_arguments('059', tmp_path, generation_profile('max-32k').__dict__)
    assert args[args.index('--max_tokens') + 1] == '32768'
    assert args[args.index('--max_steps') + 1] == '500'


def test_max16_retains_16k_reserves_and_changes_effort_only(tmp_path):
    from scripts.osworld_native_experiment import official_arguments
    low, maximum = generation_profile('low-16k'), generation_profile('max-16k')
    assert maximum.reasoning_effort == 'max'
    assert [maximum.max_completion_tokens, maximum.step_output_tokens,
            maximum.executor_reserve_tokens, maximum.adviser_max_tokens] == [16000, 32000, 16000, 4000]
    assert {k: v for k, v in maximum.__dict__.items() if k not in ('name', 'reasoning_effort')} == {
        k: v for k, v in low.__dict__.items() if k not in ('name', 'reasoning_effort')}
    args = official_arguments('059', tmp_path, maximum.__dict__)
    assert args[args.index('--max_tokens') + 1] == '16000'


def make_agent(monkeypatch, tmp_path):
    monkeypatch.setenv('KIMI_API_KEY', 'offline-secret')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_GENERATION_PROFILE', 'low-16k')
    agent = KimiNativeAgent(model='kimi-k3', base_url='https://api.moonshot.ai/v1', temperature=1, max_tokens=16000)
    image = BytesIO()
    Image.new('RGB', (1920, 1080)).save(image, 'PNG')
    return agent, {'screenshot': image.getvalue()}


@pytest.mark.parametrize('second_length', [False, True])
def test_agent_regenerates_once_preserves_history_and_charges_failed_usage(monkeypatch, tmp_path, second_length):
    agent, obs = make_agent(monkeypatch, tmp_path)
    sent, events = [], []
    def handler(request):
        sent.append(json.loads(request.content))
        failed = len(sent) == 1 or second_length
        return httpx.Response(200, text=sse(length=failed, used=16000 if failed else 7, tool=not failed))
    agent.client = transport(handler, agent.profile, events, tmp_path / 'streams')
    try:
        if second_length:
            with pytest.raises(OutputTokenLimitError):
                agent.predict('exact goal', obs)
            assert not agent.turns and agent.pending is None
        else:
            _, commands = agent.predict('exact goal', obs)
            assert len(commands) == 1 and 'moveTo' in commands[0]
            assert len(agent.turns) == 1 and agent.pending == 'original-id'
        assert len(sent) == 2
        assert all(m['role'] != 'assistant' for m in sent[1]['messages'])
        assert sent[1]['messages'][-1]['content'][0]['text'].startswith('Original task: exact goal')
        requests = [value for name, value in events if name == 'api_request']
        assert [v['generation_attempt'] for v in requests] == [1, 2]
        assert [v['attempt'] for v in requests] == [1, 1]
        assert requests[1]['parent_request_id'] == requests[0]['request_id']
        assert agent.step_ledger.snapshot()['known_usage']['total_tokens'] == (32200 if second_length else 16207)
    finally:
        agent.close()


def test_missing_usage_does_not_trigger_semantic_regeneration(monkeypatch, tmp_path):
    agent, obs = make_agent(monkeypatch, tmp_path)
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, text=sse(usage=False))
    agent.client = transport(handler, agent.profile, [], tmp_path / 'streams')
    _, commands = agent.predict('exact goal', obs)
    assert len(commands) == 1 and len(sent) == 1 and len(agent.turns) == 1
    assert agent.step_ledger.charged_output == 16000
    assert agent.step_ledger.snapshot()['unknown_usage_requests'] == 1
    agent.close()


def test_transport_retry_is_distinct_and_reserves_unknown_attempt(monkeypatch, tmp_path):
    monkeypatch.setattr('ui_kobe.api.kimi_stream.time.sleep', lambda n: None)
    events, calls = [], []
    ledger = StepLedger(generation_profile(), time.monotonic() + 50, lambda *a, **k: None)
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError('offline transport failure')
        return httpx.Response(200, text=sse())
    client = transport(handler, generation_profile(), events, tmp_path)
    client.create(messages=[], step_ledger=ledger, max_completion_tokens=16000)
    requests = [value for name, value in events if name == 'api_request']
    assert [v['attempt'] for v in requests] == [1, 2]
    assert [v['generation_attempt'] for v in requests] == [1, 1]
    assert ledger.charged_output == 16007
    assert ledger.snapshot()['unknown_usage_requests'] == 1


@pytest.mark.parametrize('failed_role', ['perception', 'executor'])
def test_taskviews_roles_share_budget_and_executor_retry_reuses_views(monkeypatch, tmp_path, failed_role):
    from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
    monkeypatch.setenv('KIMI_API_KEY', 'offline-secret')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '059')
    monkeypatch.setenv('UI_KOBE_GENERATION_PROFILE', 'low-16k')
    agent = KimiTaskViewsNativeAgent(model='kimi-k3', base_url='https://api.moonshot.ai/v1', temperature=1, max_tokens=16000)
    roles, payloads, events = [], [], []
    def handler(request):
        payload = json.loads(request.content)
        prompt = payload['messages'][0]['content']
        if payload.get('tools'):
            role, body = 'executor', None
        elif 'Extract visible evidence' in prompt:
            role, body = 'perception', {'summary': 'Visible screen', 'elements': [], 'semantics': {'entities': [], 'claims': []}}
        elif 'subordinate task planner' in prompt:
            role, body = 'planner', {'advice': 'Inspect visible controls.', 'needed_evidence': []}
        elif 'subordinate visual verifier' in prompt:
            role, body = 'verifier', {'assessment': 'unknown', 'quotes': [], 'gaps': []}
        else:
            role, body = 'view_controller', {'stage': 'observe', 'needs': [
                {'id': consumer, 'consumer': consumer, 'purpose': 'next action', 'anchors': ['task'],
                 'focus_predicates': ['*'], 'max_hops': 1} for consumer in ('planner', 'verifier', 'executor')]}
        fail = role == failed_role and role not in roles
        roles.append(role)
        payloads.append(payload)
        return httpx.Response(200, text=sse(length=fail, used=payload['max_completion_tokens'] if fail else 7,
            content=None if fail or body is None else json.dumps(body), tool=not fail and role == 'executor'))
    actual = transport(handler, agent.profile, events, tmp_path / 'streams')
    agent.transport = agent.client.transport = actual
    png = BytesIO()
    Image.new('RGB', (1920, 1080)).save(png, 'PNG')
    try:
        _, commands = agent.predict('exact goal', {'screenshot': png.getvalue()})
        assert len(commands) == 1 and 'moveTo' in commands[0]
        assert len(roles) == 6 and roles.count(failed_role) == 2
        assert all(roles.count(role) == 1 for role in {'perception', 'view_controller', 'planner', 'verifier', 'executor'} - {failed_role})
        assert all(payload['reasoning_effort'] == 'low' for payload in payloads)
        assert all(payload['max_completion_tokens'] <= (16000 if role == 'executor' else 4000)
                   for role, payload in zip(roles, payloads))
        ledger = agent.step_ledger.snapshot()
        assert ledger['semantic_regenerations'] == 1 and ledger['requests'] == 6
        assert ledger['charged_output'] == (4000 if failed_role == 'perception' else 16000) + 35
        assert ledger['known_usage']['total_tokens'] == ledger['charged_output'] + 600
        assert ledger['charged_output'] <= ledger['output_limit']
        if failed_role == 'executor':
            assert payloads[-1]['messages'][-1]['content'][1] == payloads[-2]['messages'][-1]['content'][1]
            assert payloads[-1]['max_completion_tokens'] == 15972
    finally:
        agent.close()
