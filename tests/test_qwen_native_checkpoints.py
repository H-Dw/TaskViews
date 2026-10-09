from copy import deepcopy
from io import BytesIO
import json
import time

import httpx
from PIL import Image
import pytest

from scripts import osworld_native_experiment as experiment
from scripts.run_official_native_tasks import agent_class
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import Completion, OutputTokenLimitError, ProviderQuotaBlocked, StreamBudget
from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, GatewayRequestError, QwenGenerationProfile, QwenNativeClient
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.cua_contract import options_contract
from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent


def make_client(tmp_path, handler, *, role='executor', sleep=lambda _: None):
    events, profile = [], QwenGenerationProfile()
    ledger = StepLedger(profile, time.monotonic()+930, lambda *a, **k: None)
    client = QwenNativeClient(api_key='offline-key', budget=StreamBudget(), profile=profile,
        emit=lambda event, **data: events.append({'event': event, **data}), response_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleep)
    return client, ledger, events


def request(client, ledger, role='executor'):
    return client.create(model=MODEL, messages=[{'role':'user', 'content':'test'}],
                         max_tokens=ledger.allowance(role), budget_role=role,
                         deadline=ledger.deadline, step_ledger=ledger)


def completed(content='ok', finish='stop'):
    return {'id':'original-response', 'model':MODEL,
            'choices':[{'finish_reason':finish, 'message':{'role':'assistant', 'content':content}}],
            'usage':{'prompt_tokens':100, 'completion_tokens':10, 'total_tokens':110,
                     'prompt_tokens_details':{'cached_tokens':50}}}


def test_qwen_wire_has_no_kimi_fields_and_preserves_real_usage(tmp_path):
    requests = []
    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, json=completed())
    client, ledger, events = make_client(tmp_path, handler)
    assert request(client, ledger).model_dump() == completed()
    assert requests[0]['enable_thinking'] is False and requests[0]['stream'] is False
    assert requests[0]['max_tokens'] == 16000 and requests[0]['temperature'] == 0
    assert not {'max_completion_tokens','reasoning_effort'} & requests[0].keys()
    outcome = next(e for e in events if e['event'] == 'request_outcome')
    assert outcome['usage'] == completed()['usage']
    assert outcome['raw_sse_path'] is None and outcome['stream_done'] is False
    assert json.loads((tmp_path / (outcome['request_id']+'.json')).read_text()) == completed()
    assert ledger.snapshot()['known_usage']['total_tokens'] == 110
    client.close()


def test_http_200_nested_model_error_is_not_a_completion(tmp_path):
    body = {'success':False, 'code':500,
            'message':json.dumps({'error':{'code':'model_not_found', 'message':'secret offline-key'}})}
    client, ledger, events = make_client(tmp_path, lambda _: httpx.Response(200, json=body))
    with pytest.raises(GatewayRequestError, match='model_not_found'):
        request(client, ledger)
    assert not any(e['event'] == 'api_response' for e in events)
    outcome = next(e for e in events if e['event'] == 'request_outcome')
    assert outcome['outcome'] == 'error' and outcome['usage'] is None
    assert ledger.snapshot()['unknown_usage_requests'] == 1
    assert 'offline-key' not in json.dumps(events)
    assert 'offline-key' not in next(tmp_path.glob('*.json')).read_text()
    client.close()


def test_non_stream_length_keeps_full_usage_and_never_executes(tmp_path):
    body = completed('incomplete', 'length')
    body['usage'].update(completion_tokens=4000, total_tokens=4100)
    client, ledger, events = make_client(tmp_path, lambda _: httpx.Response(200, json=body), role='perception')
    with pytest.raises(OutputTokenLimitError):
        request(client, ledger, 'perception')
    outcome = next(e for e in events if e['event'] == 'request_outcome')
    assert outcome['usage'] == body['usage'] and outcome['executable'] is False
    assert ledger.snapshot()['unknown_usage_requests'] == 0
    assert ledger.allowance('perception') == 4000
    client.close()


def test_billing_quota_never_retries(tmp_path):
    waits, requests = [], []
    def handler(req):
        requests.append(req)
        return httpx.Response(429, json={'error':{'type':'exceeded_current_quota_error', 'message':'sk-account-id'}},
                              headers={'retry-after':'1'})
    client, ledger, events = make_client(tmp_path, handler, sleep=waits.append)
    with pytest.raises(ProviderQuotaBlocked):
        request(client, ledger)
    assert len(requests) == 1 and waits == []
    assert sum(e['event'] == 'request_outcome' for e in events) == 1
    assert ledger.snapshot()['unknown_usage_requests'] == 1
    assert 'sk-account-id' not in json.dumps(events)
    client.close()


def test_transient_429_honors_wait_and_settles_two_actual_attempts(tmp_path):
    waits, count = [], 0
    def handler(req):
        nonlocal count
        count += 1
        return (httpx.Response(429, json={'error':{'code':'rate_limit_exceeded'}}, headers={'retry-after':'1'})
                if count == 1 else httpx.Response(200, json=completed()))
    client, ledger, events = make_client(tmp_path, handler, sleep=waits.append)
    request(client, ledger)
    assert count == 2 and waits == [60]
    outcomes = [e for e in events if e['event'] == 'request_outcome']
    assert len({e['request_id'] for e in outcomes}) == 2
    assert [e['usage'] is None for e in outcomes] == [True, False]
    assert ledger.snapshot()['unknown_usage_requests'] == 1
    client.close()


def test_actor_and_analysis_admission_remain_independent():
    profile = QwenGenerationProfile()
    actor = StepLedger(profile, time.monotonic()+930, lambda *a, **k: None)
    analysis = StepLedger(profile, time.monotonic()+315, lambda *a, **k: None)
    assert actor.allowance('executor') == 16000 and analysis.allowance('perception') == 4000
    analysis.reserve('unknown-read', 'perception', 4000)
    analysis.settle('unknown-read', None)
    assert actor.snapshot()['charged_output'] == 0
    assert analysis.snapshot()['charged_output'] == 4000
    assert analysis.snapshot()['output_limit'] == actor.snapshot()['output_limit'] == 32000


def test_qwen_options_and_frozen_arguments():
    options_contract({'stream':False, 'enable_thinking':False, 'top_p':0.9}, provider='qwen')
    with pytest.raises(ValueError, match='stream'):
        options_contract({'stream':True}, provider='qwen')
    args = experiment.official_arguments('059', experiment.ROOT/'results/test', provider='qwen')
    for name, value in {'--model':MODEL, '--base_url':BASE_URL, '--temperature':'0', '--top_p':'0.9',
                        '--max_steps':'500', '--max_tokens':'16000', '--coord':'absolute'}.items():
        assert args[args.index(name)+1] == value
    assert '--stream' not in args and '--enable_thinking' not in args
    assert '--batch_actions' in args and agent_class('qwen-native', 'taskviews') is QwenTaskViewsNativeAgent
    with pytest.raises(KeyError):
        agent_class('qwen-native', 'baseline')


class NativeTransport:
    last_timing = {}
    def __init__(self, invalid_read=False):
        self.requests, self.invalid_read, self.actor = [], invalid_read, 0
    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        if kwargs.get('tools'):
            self.actor += 1
            body = completed(None, 'tool_calls')
            body['choices'][0]['message']['tool_calls'] = [{'id':f'actual-{self.actor}', 'type':'function',
                'function':{'name':'computer_use', 'arguments':'{"action":"mouse_move","coordinate":[100,100]}'}}]
        elif self.invalid_read:
            body = completed('malformed')
        elif 'Extract visible evidence' in kwargs['messages'][0]['content']:
            body = completed(json.dumps({'summary':'Visible application', 'elements':[],
                                         'semantics':{'entities':[], 'claims':[]}}))
        else:
            body = completed(json.dumps({'stage':'observe', 'needs':[{'id':'gui', 'consumer':'executor',
                'purpose':'next action', 'anchors':['task'], 'focus_predicates':['*'], 'max_hops':1}]}))
        return Completion(body)
    def close(self):
        pass


@pytest.mark.parametrize('invalid_read', [False, True])
def test_qwen_taskviews_keeps_original_tool_identity_or_pauses_before_actor(tmp_path, monkeypatch, invalid_read):
    monkeypatch.setenv('QWEN_API_KEY', 'offline-key')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '059')
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS', '1')
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
    transport = NativeTransport(invalid_read)
    actor.transport = actor.client.transport = transport
    image = BytesIO()
    Image.new('RGB', (1920,1080), 'white').save(image, 'PNG')
    try:
        if invalid_read:
            with pytest.raises(ReadAnomaly):
                actor.predict('Original user goal', {'screenshot':image.getvalue()})
            assert transport.actor == 0 and actor.pending is None
        else:
            for _ in range(2):
                _, commands = actor.predict('Original user goal', {'screenshot':image.getvalue()})
                assert len(commands) == 1 and 'moveTo' in commands[0]
            payload = transport.requests[-1]
            assistant = next(m for m in payload['messages'] if m['role'] == 'assistant')
            reply = next(m for m in payload['messages'] if m['role'] == 'tool')
            assert assistant['tool_calls'][0]['id'] == reply['tool_call_id'] == 'actual-1'
            assert actor.last_trace['protocol'] == PROTOCOL
        for req in transport.requests:
            assert req['model'] == MODEL and 'reasoning_effort' not in req and 'max_completion_tokens' not in req
            assert req['max_tokens'] <= (16000 if req.get('tools') else 4000)
    finally:
        actor.close()
