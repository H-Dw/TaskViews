from copy import deepcopy
from io import BytesIO
import argparse
import ast
import json
import os
from pathlib import Path
import time

import httpx
from PIL import Image
import pytest
from kobe_views.task_memory import TaskMemory

from scripts import osworld_native_experiment as experiment
from scripts.run_official_native_tasks import agent_class
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import Completion, OutputTokenLimitError, ProviderQuotaBlocked, StreamBudget, StreamProtocolError
from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, GatewayRequestError, QwenGenerationProfile, QwenNativeClient
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.cua_contract import options_contract
from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
from ui_kobe.osworld.actor_context import repair_messages
from ui_kobe.osworld.kimi_native import official_compile


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


@pytest.mark.parametrize('role,cap', [('executor',16000), ('perception',4000)])
def test_remote_disconnect_retries_same_payload_with_separate_unknown_usage(tmp_path, role, cap):
    waits, payloads = [], []
    def handler(req):
        payloads.append(json.loads(req.content))
        if len(payloads) == 1:
            raise httpx.RemoteProtocolError('Server disconnected without sending a response.', request=req)
        return httpx.Response(200, json=completed())
    client, ledger, events = make_client(tmp_path, handler, sleep=waits.append)
    assert request(client, ledger, role).model_dump() == completed()
    assert payloads[0] == payloads[1] and waits == [3]
    outcomes = [e for e in events if e['event'] == 'request_outcome']
    assert len({e['request_id'] for e in outcomes}) == 2
    assert [e['outcome'] for e in outcomes] == ['error','complete']
    assert outcomes[0]['usage'] is None and outcomes[0]['raw_response_path'] is None
    assert outcomes[0]['observed_response'] is None and outcomes[0]['stream_done'] is False
    assert outcomes[1]['usage'] == completed()['usage']
    assert ledger.snapshot()['unknown_usage_requests'] == 1
    assert ledger.snapshot()['known_usage']['total_tokens'] == 110
    assert ledger.snapshot()['charged_output'] == cap + 10
    assert ledger.repair_counts == {'executor':0, 'advisory':0}
    assert all(e['raw_sse_path'] is None for e in outcomes)
    client.close()


def test_remote_disconnect_attempt_limit_preserves_unknown_usage(tmp_path):
    waits, attempts = [], []
    def handler(req):
        attempts.append(req)
        raise httpx.RemoteProtocolError('Server disconnected without sending a response.', request=req)
    client, ledger, events = make_client(tmp_path, handler, sleep=waits.append)
    with pytest.raises(httpx.RemoteProtocolError):
        request(client, ledger)
    assert len(attempts) == 2 and waits == [3]
    assert not any(e['event'] == 'api_response' for e in events)
    outcomes = [e for e in events if e['event'] == 'request_outcome']
    assert len({e['request_id'] for e in outcomes}) == 2
    assert all(e['usage'] is None and e['outcome'] == 'error' for e in outcomes)
    assert ledger.snapshot()['unknown_usage_requests'] == 2
    assert ledger.snapshot()['charged_output'] == 32000
    assert ledger.snapshot()['known_usage']['total_tokens'] == 0
    client.close()


def test_remote_disconnect_does_not_retry_past_original_deadline(tmp_path):
    waits, attempts = [], []
    def handler(req):
        attempts.append(req)
        raise httpx.RemoteProtocolError('Server disconnected without sending a response.', request=req)
    client, ledger, events = make_client(tmp_path, handler, sleep=waits.append)
    with pytest.raises(httpx.RemoteProtocolError):
        client.create(model=MODEL, messages=[{'role':'user','content':'test'}], max_tokens=16000,
                      budget_role='executor', deadline=time.monotonic()+client.budget.connect_s+1,
                      step_ledger=ledger)
    assert len(attempts) == 1 and waits == []
    assert sum(e['event'] == 'request_outcome' for e in events) == 1
    client.close()


def test_local_protocol_error_still_fails_without_transport_retry(tmp_path):
    waits = []
    def handler(req):
        raise httpx.LocalProtocolError('Invalid local request', request=req)
    client, ledger, events = make_client(tmp_path, handler, sleep=waits.append)
    with pytest.raises(httpx.LocalProtocolError):
        request(client, ledger)
    assert waits == [] and sum(e['event'] == 'api_request' for e in events) == 1
    assert ledger.snapshot()['unknown_usage_requests'] == 1
    client.close()


def test_partial_remote_disconnect_keeps_redacted_evidence_before_retry(tmp_path):
    class DisconnectBody(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"message":"offline-key"'
            raise httpx.RemoteProtocolError('Incomplete response body')
    attempts = []
    def handler(req):
        attempts.append(req)
        return (httpx.Response(200, stream=DisconnectBody()) if len(attempts)==1
                else httpx.Response(200, json=completed()))
    client, ledger, events = make_client(tmp_path, handler)
    request(client, ledger, 'perception')
    outcomes = [e for e in events if e['event']=='request_outcome']
    assert len(outcomes)==2 and outcomes[0]['usage'] is None
    assert outcomes[0]['raw_response_sha256'] is not None
    saved = Path(outcomes[0]['raw_response_path'])
    assert saved.name.endswith('.partial-redacted.txt')
    assert 'offline-key' not in saved.read_text() and '[REDACTED]' in saved.read_text()
    assert ledger.snapshot()['unknown_usage_requests']==1
    assert ledger.snapshot()['known_usage']['total_tokens']==110
    client.close()


def test_qwen_options_and_frozen_arguments():
    options_contract({'stream':False, 'enable_thinking':False, 'top_p':0.9}, provider='qwen')
    with pytest.raises(ValueError, match='stream'):
        options_contract({'stream':True}, provider='qwen')
    args = experiment.official_arguments('059', experiment.ROOT/'results/test', provider='qwen')
    for name, value in {'--model':MODEL, '--base_url':BASE_URL, '--temperature':'0', '--top_p':'0.9',
                        '--max_steps':'500', '--max_tokens':'16000', '--coord':'absolute'}.items():
        assert args[args.index(name)+1] == value
    assert '--stream' not in args and '--enable_thinking' not in args
    assert '--no-stream' in args and '--no-enable_thinking' in args
    assert '--batch_actions' in args and agent_class('qwen-native', 'taskviews') is QwenTaskViewsNativeAgent
    with pytest.raises(KeyError):
        agent_class('qwen-native', 'baseline')


def test_actual_official_parser_turns_off_its_enabled_defaults(tmp_path):
    repo = Path(os.environ.get('UI_KOBE_OFFICIAL_REPO', str(Path.home()/'osworld2/OSWorld-V2')))
    source = ast.parse((repo/'scripts/python/run_multienv_qwen.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in ('config','_volume_size')]
    namespace = {'argparse':argparse}
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'pinned-official-argument-parser', 'exec'), namespace)
    args = namespace['config'](experiment.official_arguments('059', tmp_path, provider='qwen'))
    assert args.stream is False and args.enable_thinking is False
    assert args.model == MODEL and args.max_steps == 500 and args.max_tokens == 16000


def test_identity_preflight_does_not_publish_or_rename_task(tmp_path):
    memory = TaskMemory('identity-repair', tmp_path)
    try:
        memory.initialize('Original exact user instruction')
        entity = dict(memory.read().entities['task'])
        before = memory.read().revision
        original_journal = memory.journal.read_bytes()
        with pytest.raises(ValueError, match='immutable'):
            memory.validate_proposal_identity({'entities':[{**entity,'label':'Model rewritten task label'}], 'claims':[]})
        memory.validate_proposal_identity({'entities':[entity], 'claims':[]})
        assert memory.read().revision == before and memory.journal.read_bytes() == original_journal
        claim = next(c for c in memory.read().claims.values() if c['subject'] == 'task')
        changed = {k:claim[k] for k in ('id','subject','predicate','value')}
        changed.update(locator='visible frame', value='changed evidence')
        with pytest.raises(ValueError, match='new claim id'):
            memory.validate_proposal_identity({'entities':[], 'claims':[changed]})
        assert dict(memory.read().entities['task']) == entity
    finally:
        memory.close()


def test_claim_identity_feedback_lists_all_original_conflicts_without_mutation(tmp_path):
    from kobe_views.model import dumps, plain
    memory = TaskMemory('claim-conflicts', tmp_path)
    try:
        memory.initialize('Import input.csv and save output.csv')
        claims = [plain(c) for c in list(memory.read().claims.values())[:2]]
        assert len(claims) == 2
        before = memory.read().revision
        original_db = (memory.directory/'task.sqlite').read_bytes()
        proposals = [{k: c[k] for k in ('id', 'subject', 'predicate', 'value', 'objects', 'basis')}
                     for c in claims]
        for c in proposals:
            c.update(locator='Current frame', value='New visible observation')
        with pytest.raises(ValueError, match='new claim id') as error:
            memory.validate_proposal_identity({'entities': [], 'claims': proposals})
        packet = json.loads(str(error.value).split('Conflicting original claims: ', 1)[1].split('. Omit unchanged', 1)[0])
        assert {r['id'] for r in packet['conflicting_claim_records']} == {c['id'] for c in claims}
        assert len(dumps(packet).encode()) <= 6000
        for record, original in zip(packet['conflicting_claim_records'], claims):
            assert record['changed_identity_fields'] == ['value']
            assert record['original_identity'] == {k: original[k] for k in ('id', 'subject', 'predicate', 'value', 'objects', 'basis')}
        assert memory.read().revision == before and (memory.directory/'task.sqlite').read_bytes() == original_db
        same = [{**{k: c[k] for k in ('id', 'subject', 'predicate', 'value', 'objects', 'basis')},
                 'locator': 'Current frame'} for c in claims]
        memory.validate_proposal_identity({'entities': [], 'claims': same})
    finally:
        memory.close()


def test_claim_identity_feedback_whole_omission_exact_digest_and_no_candidate_echo(tmp_path):
    from types import SimpleNamespace
    import hashlib
    from kobe_views.model import dumps
    original = {'id': 'claim', 'subject': 'task', 'predicate': 'report', 'value': '原'*7000,
                'objects': [], 'basis': []}
    memory = TaskMemory.__new__(TaskMemory)
    memory.graph = SimpleNamespace(read=lambda: SimpleNamespace(claims={'claim': original},
                                                               entities={}, statuses={'claim': 'active'}))
    proposed = {**original, 'value': 'password=sk-unsafe-candidate-value', 'locator': 'visible'}
    with pytest.raises(ValueError) as error:
        memory.validate_proposal_identity({'entities': [], 'claims': [proposed]})
    packet = json.loads(str(error.value).split('Conflicting original claims: ', 1)[1].split('. Omit unchanged', 1)[0])
    record = packet['conflicting_claim_records'][0]
    assert len(dumps(packet).encode()) <= 6000 and record['original_identity_omitted']
    assert 'original_identity' not in record and proposed['value'] not in str(error.value)
    assert record['original_identity_sha256'] == hashlib.sha256(dumps(original).encode()).hexdigest()


def test_identity_feedback_reports_entity_and_claim_conflicts_in_same_repair(tmp_path):
    from kobe_views.model import dumps
    memory = TaskMemory('combined-conflicts', tmp_path)
    try:
        memory.initialize('Import input.csv and save output.csv')
        entity = dict(memory.read().entities['task'])
        claim = next(iter(memory.read().claims.values()))
        proposed = {k: claim[k] for k in ('id', 'subject', 'predicate', 'value')}
        proposed.update(locator='Current frame', value='Changed observation')
        before = memory.read().revision
        with pytest.raises(ValueError) as error:
            memory.validate_proposal_identity({'entities': [{**entity, 'label': 'Wrong label'}],
                                               'claims': [proposed]})
        packet = json.loads(str(error.value).split('Conflicting original identities: ', 1)[1].split('. Omit unchanged', 1)[0])
        assert packet['conflicting_entity_records'] == [entity]
        assert packet['conflicting_claim_records'][0]['id'] == claim['id']
        assert len(dumps(packet).encode()) <= 6000 and memory.read().revision == before
    finally:
        memory.close()


@pytest.mark.parametrize('status,supersedes', [('active', ['prior']), ('superseded', [])])
def test_claim_identity_feedback_distinguishes_status_and_supersedes(status, supersedes):
    from types import SimpleNamespace
    original = {'id': 'claim', 'subject': 'task', 'predicate': 'visible', 'value': 'literal',
                'objects': [], 'basis': []}
    memory = TaskMemory.__new__(TaskMemory)
    memory.graph = SimpleNamespace(read=lambda: SimpleNamespace(claims={'claim': original},
                                                               entities={}, statuses={'claim': status}))
    with pytest.raises(ValueError) as error:
        memory.validate_proposal_identity({'entities': [], 'claims': [{**original, 'locator': 'frame',
                                                                     'supersedes': supersedes}]})
    packet = json.loads(str(error.value).split('Conflicting original claims: ', 1)[1].split('. Omit unchanged', 1)[0])
    record = packet['conflicting_claim_records'][0]
    assert record['changed_identity_fields'] == [] and record['original_status'] == status
    assert record['supersedes_on_existing_id'] is bool(supersedes)


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


@pytest.mark.parametrize('predicate,value,reason', [
    ('coordinates', [3.87, -6.96], 'current_frame_geometry_only'),
    ('visible.position', {'nested': {'x': 20, 'y': 30}}, 'current_frame_geometry_only'),
    ('ui.bbox', [1, 2, 3, 4], 'current_frame_geometry_only'),
    ('observed.value', {'password': 'do-not-publish'}, 'credential_field_or_value'),
    ('observed.value', 'a' * 8193, 'semantic_value_budget_exceeded'),
])
def test_content_preflight_is_pure_and_uses_durable_admission_rules(tmp_path, predicate, value, reason):
    memory = TaskMemory('content-preflight', tmp_path)
    try:
        memory.initialize('Original instruction')
        proposal = {'entities': [], 'claims': [
            {'id': 'candidate', 'subject': 'task', 'predicate': predicate, 'value': value, 'locator': 'visible text'},
            {'id': 'dependent', 'subject': 'task', 'predicate': 'derived.fact', 'value': 'Untrusted derivation',
             'locator': 'model', 'basis': ['candidate']},
            {'id': 'indirect', 'subject': 'task', 'predicate': 'derived.fact', 'value': 'Another derivation',
             'locator': 'model', 'basis': ['dependent']}]}
        original = deepcopy(proposal)
        before = memory.snapshot.revision
        original_db = (memory.directory / 'task.sqlite').read_bytes()
        with pytest.raises(ValueError, match=reason) as error:
            memory.validate_proposal_content(proposal)
        assert 'rejected_evidence_dependency' in str(error.value)
        assert proposal == original and memory.snapshot.revision == before
        assert (memory.directory / 'task.sqlite').read_bytes() == original_db
        assert memory.current_observation is None
        assert memory._claim_content_rejection(proposal['claims'][0]) == reason
        memory.validate_proposal_content({'entities': [], 'claims': []})
    finally:
        memory.close()


@pytest.mark.parametrize('never_correct', [False, True])
def test_frame_content_repair_precedes_observation_and_actor_dispatch(tmp_path, monkeypatch, never_correct):
    monkeypatch.setenv('QWEN_API_KEY', 'offline-key')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '059')
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS', '1')
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)

    class GeometryRead(NativeTransport):
        reads = 0
        previous = None
        first_revision = None
        def create(self, **kwargs):
            if kwargs['budget_role'] != 'perception':
                return super().create(**kwargs)
            self.requests.append(deepcopy(kwargs))
            self.reads += 1
            memory = actor.control.memory
            self.first_revision = self.first_revision or memory.snapshot.revision
            assert memory.snapshot.revision == self.first_revision
            assert memory.current_observation is None
            if self.reads > 1:
                assert kwargs['messages'][-2] == self.previous
                hint = kwargs['messages'][-1]['content'][0]['text']
                assert 'current_frame_geometry_only' in hint and 'rejected_evidence_dependency' in hint
            claims = []
            if self.reads == 1 or never_correct:
                claims = [{'id': 'frame:coords', 'subject': 'task', 'predicate': 'coordinates',
                           'value': [3.87, -6.96], 'locator': 'original visible text'},
                          {'id': 'frame:dependent', 'subject': 'task', 'predicate': 'derived.fact',
                           'value': 'proposal', 'locator': 'model', 'basis': ['frame:coords']}]
            body = completed(json.dumps({'summary': 'Original visible text',
                'elements': [{'text': 'A = (3.87, -6.96)', 'role': 'text', 'bbox': [1, 2, 40, 30]}],
                'semantics': {'entities': [], 'claims': claims}}))
            self.previous = deepcopy(body['choices'][0]['message'])
            return Completion(body)

    transport = GeometryRead()
    actor.transport = actor.client.transport = transport
    image = BytesIO()
    Image.new('RGB', (1920, 1080), 'white').save(image, 'PNG')
    try:
        if never_correct:
            with pytest.raises(ReadAnomaly, match='current_frame_geometry_only'):
                actor.predict('Original instruction', {'screenshot': image.getvalue()})
            assert transport.reads == 3 and transport.actor == 0 and actor.pending is None
            assert actor.control.memory.current_observation is None
        else:
            _, commands = actor.predict('Original instruction', {'screenshot': image.getvalue()})
            assert len(commands) == 1 and transport.reads == 2 and transport.actor == 1
            assert actor.control.memory.current_observation['evidence']['elements'][0]['text'] == 'A = (3.87, -6.96)'
            assert 'frame:coords' not in actor.control.memory.snapshot.claims
        assert actor.advisory_ledger.repair_counts['advisory'] == (2 if never_correct else 1)
        assert actor.advisory_ledger.snapshot()['output_limit'] == 32000
        if never_correct:
            # The independent actor ledger is created only after a valid read.
            assert not hasattr(actor, 'step_ledger')
        else:
            assert actor.step_ledger.repair_counts['executor'] == 0
            assert actor.step_ledger.snapshot()['output_limit'] == 32000
    finally:
        actor.close()


def test_conflicting_task_label_gets_bounded_model_repair_before_graph_publish(tmp_path, monkeypatch):
    monkeypatch.setenv('QWEN_API_KEY', 'offline-key')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '059')
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS', '1')
    class ConflictingIdentity(NativeTransport):
        failed = False
        def create(self, **kwargs):
            if kwargs['budget_role']=='perception' and not self.failed:
                self.failed=True
                self.requests.append(deepcopy(kwargs))
                return Completion(completed(json.dumps({'summary':'Visible application','elements':[],
                    'semantics':{'entities':[{'id':'task','type':'task','label':'Model rewritten task label'}], 'claims':[]}})))
            return super().create(**kwargs)
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
    transport = ConflictingIdentity()
    actor.transport = actor.client.transport = transport
    image = BytesIO()
    Image.new('RGB',(1920,1080),'white').save(image,'PNG')
    try:
        _, commands = actor.predict('Original exact user instruction', {'screenshot':image.getvalue()})
        assert len(commands)==1 and transport.actor==1
        assert actor.advisory_ledger.repair_counts['advisory']==1
        assert actor.step_ledger.repair_counts['executor']==0
        context = json.loads(transport.requests[0]['messages'][1]['content'][0]['text'])
        bindings = context['role_evidence']['entity_records']
        assert next(e for e in bindings if e['id']=='task') == dict(actor.control.memory.read().entities['task'])
        assert actor.control.memory.read().entities['task']['label'] != 'Model rewritten task label'
        assert 'advisory_failure' not in actor.view_trace
    finally:
        actor.close()


def test_omitted_old_identity_is_repaired_from_original_record_without_renaming(tmp_path, monkeypatch):
    monkeypatch.setenv('QWEN_API_KEY', 'offline-key')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '059')
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS', '1')
    goal = 'Original exact user instruction'
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
    actor.control.initialize(goal)
    memory = actor.control.memory
    entities = [{'id':f'old-window-{i}', 'type':'ui_window', 'label':f'Original window {i}'}
                for i in range(80)]
    memory.graph.ingest({'id':'offline-old-identity-fixture', 'task_id':memory.task_id,
        'source':'fixture', 'ref':'original-inventory.json', 'observed_at':'2030-01-01T00:00:00Z',
        'occurred_at':'2030-01-01T00:00:00Z', 'text':'Original identity fixture',
        'extraction':{'entities':entities, 'claims':[]}})
    original = entities[20]
    assert original['id'] not in {e['id'] for e in actor.control.inventory()['entities']}
    rejected = {**original, 'type':'window', 'label':'Model reinterpreted title'}

    class OmittedIdentity(NativeTransport):
        reads = 0
        rejected_message = None
        def create(self, **kwargs):
            if kwargs['budget_role'] != 'perception':
                return super().create(**kwargs)
            self.requests.append(deepcopy(kwargs))
            self.reads += 1
            if self.reads == 1:
                context = json.loads(kwargs['messages'][1]['content'][0]['text'])
                assert original['id'] not in context['role_evidence']['entity_ids']
                candidate = rejected
            else:
                assert self.reads == 2
                assert kwargs['messages'][-2] == self.rejected_message
                feedback = kwargs['messages'][-1]['content'][0]['text']
                assert 'conflicting_entity_records' in feedback
                assert json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')) in feedback
                candidate = original
            body = completed(json.dumps({'summary':'Visible application', 'elements':[],
                'semantics':{'entities':[candidate], 'claims':[]}}))
            if self.reads == 1:
                self.rejected_message = deepcopy(body['choices'][0]['message'])
            return Completion(body)

    transport = OmittedIdentity()
    actor.transport = actor.client.transport = transport
    image = BytesIO()
    Image.new('RGB', (1920,1080), 'white').save(image,'PNG')
    try:
        _, commands = actor.predict(goal, {'screenshot':image.getvalue()})
        assert len(commands) == 1 and transport.actor == 1 and transport.reads == 2
        assert dict(actor.control.memory.read().entities[original['id']]) == original
        assert actor.advisory_ledger.repair_counts['advisory'] == 1
        assert actor.step_ledger.repair_counts['executor'] == 0
        assert all(r['max_tokens'] <= (16000 if r.get('tools') else 4000) for r in transport.requests)
    finally:
        actor.close()


def test_identity_conflict_feedback_omits_whole_records_within_bound(tmp_path):
    memory = TaskMemory('bounded-conflicts', tmp_path)
    try:
        memory.initialize('Original instruction')
        entities = [{'id':f'window-{i}', 'type':'ui_window', 'label':'原' * 1000} for i in range(32)]
        memory.graph.ingest({'id':'identity-fixture', 'task_id':memory.task_id, 'source':'fixture',
            'ref':'inventory.json', 'observed_at':'2030-01-01T00:00:00Z',
            'occurred_at':'2030-01-01T00:00:00Z', 'text':'Original identities',
            'extraction':{'entities':entities, 'claims':[]}})
        before = memory.snapshot.revision
        original_db = (memory.directory/'task.sqlite').read_bytes()
        with pytest.raises(ValueError, match='immutable') as error:
            memory.validate_proposal_identity({'entities':[{**e,'label':'Rewritten'} for e in entities], 'claims':[]})
        packet = json.loads(str(error.value).split('Conflicting original identities: ', 1)[1])
        records = packet['conflicting_entity_records']
        from kobe_views.model import dumps
        assert len(dumps(records).encode()) <= 6000
        assert records and all(e in entities for e in records)
        assert packet['omitted_conflicting_entity_records'] == len(entities) - len(records) > 0
        assert memory.snapshot.revision == before
        assert (memory.directory/'task.sqlite').read_bytes() == original_db
    finally:
        memory.close()


@pytest.mark.parametrize('finish, executable', [('stop', False), ('length', False), ('stop', True)])
def test_adviser_repair_preserves_only_complete_nonexecutable_original_response(finish, executable):
    body = completed('{"rejected":"original"}', finish)
    message = body['choices'][0]['message']
    if executable:
        message['tool_calls'] = [{'id':'never-execute', 'type':'function',
            'function':{'name':'computer_use', 'arguments':'{}'}}]
    original = {'messages':[{'role':'user', 'content':[{'type':'text','text':'Original context'}]}]}
    snapshot = deepcopy(original)
    corrected = repair_messages(original, body, ValueError('Original identity conflict'), role='perception')
    assert original == snapshot
    admitted = [m for m in corrected['messages'] if m['role'] == 'assistant']
    assert admitted == ([message] if finish == 'stop' and not executable else [])
    assert not any(m['role'] == 'tool' for m in corrected['messages'])
    assert 'perception JSON was rejected' in corrected['messages'][-1]['content'][0]['text']


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


def native_response(arguments, identifier):
    body = completed(None, 'tool_calls')
    body['choices'][0]['message']['tool_calls'] = [{'id':identifier, 'type':'function',
        'function':{'name':'computer_use', 'arguments':json.dumps(arguments)}}]
    return body


def alias_agent(tmp_path, monkeypatch, candidates):
    monkeypatch.setenv('QWEN_API_KEY', 'offline-key')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '059')
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS', '1')
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
    actor.transport.close()
    sent, original = [], []
    def handler(req):
        payload = json.loads(req.content)
        sent.append(payload)
        if payload.get('tools'):
            arguments = candidates[len(original)]
            body = native_response(arguments, f'original-candidate-{len(original)+1}')
            original.append(body)
        elif 'Extract visible evidence' in payload['messages'][0]['content']:
            body = completed(json.dumps({'summary':'Visible application', 'elements':[],
                'semantics':{'entities':[], 'claims':[]}}))
        else:
            body = completed(json.dumps({'stage':'observe', 'needs':[{'id':'gui', 'consumer':'executor',
                'purpose':'next action', 'anchors':['task'], 'focus_predicates':['*'], 'max_hops':1}]}))
        return httpx.Response(200, json=body)
    client, _, events = make_client(tmp_path/'responses', handler)
    actor.transport = actor.client.transport = client
    image = BytesIO()
    Image.new('RGB', (1920,1080), 'white').save(image,'PNG')
    return actor, {'screenshot':image.getvalue()}, sent, original, events


@pytest.mark.parametrize('bad,good', [
    ({'action':'doubleClick','coordinate':[100,100]}, {'action':'double_click','coordinate':[100,100]}),
    ({'action':'hotkey','keys':['CTRL','A']}, {'action':'key','keys':['CTRL','A']}),
    ({'action':'rightClick','coordinate':[100,100]}, {'action':'right_click','coordinate':[100,100]}),
])
def test_qwen_actor_repair_uses_exact_schema_and_preserves_rejected_calls(tmp_path, monkeypatch, bad, good):
    actor, obs, sent, original, events = alias_agent(tmp_path, monkeypatch, [bad,good])
    try:
        _, commands = actor.predict('Original exact instruction',obs)
        assert commands == official_compile([good],actor.frame).commands
        executor = [p for p in sent if p.get('tools')]
        assert len(executor)==2
        assert 'including underscores' in executor[0]['messages'][0]['content']
        schema = executor[0]['tools'][0]['function']['parameters']['properties']['action']['enum']
        repair = executor[1]['messages'][-1]['content'][0]['text']
        assert json.dumps(schema,ensure_ascii=False) in repair
        assert 'Python/PyAutoGUI method names and other aliases are invalid' in repair
        assert executor[0]['tools']==executor[1]['tools']
        rejected = next(m for m in executor[1]['messages'] if m['role']=='assistant')
        assert rejected == original[0]['choices'][0]['message']
        assert json.loads(rejected['tool_calls'][0]['function']['arguments'])==bad
        reply = next(m for m in executor[1]['messages'] if m['role']=='tool')
        assert reply['tool_call_id']=='original-candidate-1' and set(json.loads(reply['content']))=={'error'}
        assert actor.turns[-1][-1]==original[1]['choices'][0]['message']
        assert actor.pending=='original-candidate-2'
        assert actor.step_ledger.repair_counts=={'executor':1,'advisory':0}
        assert actor.step_ledger.snapshot()['known_usage']['total_tokens']==220
        assert actor.step_ledger.charged_output==20 and actor.advisory_ledger.charged_output==20
        actor_ids={e['request_id'] for e in events if e['event']=='api_request' and e['budget_role']=='executor'}
        outcomes=[e for e in events if e['event']=='request_outcome' and e['request_id'] in actor_ids]
        assert len(outcomes)==2 and all(e['outcome']=='complete' for e in outcomes)
        assert all(e['usage'] is not None for e in outcomes)
    finally:
        actor.close()


def test_qwen_never_coerces_aliases_or_exceeds_two_repairs(tmp_path,monkeypatch):
    candidates=[{'action':'doubleClick','coordinate':[100,100]},
                {'action':'hotkey','keys':['CTRL','A']},
                {'action':'rightClick','coordinate':[100,100]}]
    actor,obs,sent,original,events=alias_agent(tmp_path,monkeypatch,candidates)
    try:
        with pytest.raises(StreamProtocolError,match='Unsupported tool action: rightclick'):
            actor.predict('Original exact instruction',obs)
        assert len(original)==3 and actor.turns==[] and actor.pending is None
        assert actor.step_ledger.repair_counts=={'executor':2,'advisory':0}
        assert actor.step_ledger.charged_output==30
        assert actor.step_ledger.snapshot()['unknown_usage_requests']==0
        assert all(json.loads(b['choices'][0]['message']['tool_calls'][0]['function']['arguments'])==c
                   for b,c in zip(original,candidates))
        assert sum(e['event']=='api_response' for e in events)==5
        assert not any(e['event']=='api_error' for e in events)
    finally:
        actor.close()


@pytest.mark.parametrize('role,code', [('perception','unsupported_tool_action:unknown'),('executor','coordinate')])
def test_action_vocabulary_hint_does_not_leak_into_other_repairs(role,code):
    request={'messages':[],'tools':[{'function':{'name':'computer_use','parameters':{
        'properties':{'action':{'enum':['key','right_click']}}}}}]}
    original=deepcopy(request)
    error=StreamProtocolError('original error',code=code,retryable=True)
    repaired=repair_messages(request,None,error,role=role)
    assert request==original and 'exact action identifier' not in repaired['messages'][-1]['content'][0]['text']
