"""Offline recovery, not an episode: real failure lengths, synthetic facts/I/O."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from kobe_views.artifact_view import CHECKS, ReviewError, tagged_review, validate_review
from ui_kobe.api.kimi_stream import Completion, StreamProtocolError
from ui_kobe.osworld.actor_context import repair_messages
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.mini_recovery import TASK_PREFIX, admit_request, check_tool_pairs, report_feedback
from ui_kobe.osworld.native_history import context_size
from test_mini_taskviews import make_actor, original_event, predict
from test_mini_artifact_protocol import request_packet

FIXTURES = json.loads((Path(__file__).parent/'fixtures/mini_recovery_failures.json').read_text())


def flat_report(ref=1):
    return {'candidate': '/work/synthetic.ext', **{key: [ref, 'Synthetic fact'] for key in CHECKS}}


def request_with_history(chars):
    call = {'id': 'old-call', 'type': 'function', 'function': {
        'name': 'computer_use', 'arguments': '{"action":"screenshot"}'}}
    messages = [{'role': 'system', 'content': 'Original system'},
        {'role': 'user', 'content': [{'type': 'text', 'text': TASK_PREFIX+'Original task\nPrior actions'}]},
        {'role': 'assistant', 'content': 'Original', 'reasoning_content': '', 'tool_calls': [call]},
        {'role': 'tool', 'tool_call_id': 'old-call', 'content': '{"status":"returned"}'},
        {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}},
                                   {'type': 'text', 'text': 'Current frame geometry'}]}]
    messages[2]['reasoning_content'] = 'H' * (chars-context_size(messages)[1])
    assert context_size(messages)[1] == chars
    return {'messages': messages, 'tools': ['unchanged native schema']}


def failed_response(item):
    content = ('No report' if item['failure']=='missing_tag' else
               tagged_review(flat_report()).replace(']}</artifact_review>', ']</artifact_review>'))
    content = content.ljust(item['content_chars'])
    call = {'id': 'x', 'type': 'function', 'function': {
        'name': 'computer_use', 'arguments': '{"action": "terminate", "status": "success"}'}}
    call['id'] += 'x'*(item['tool_calls_chars']-len(json.dumps([call])))
    assert len(json.dumps([call])) == item['tool_calls_chars']
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'content': content, 'reasoning_content': 'R'*item['reasoning_chars'], 'tool_calls': [call]}}]}


@pytest.mark.parametrize('version', ['v4','v6'])
def test_real_failure_lengths_use_report_feedback_without_full_response_replay(monkeypatch, tmp_path, version):
    case = FIXTURES[version]
    count = len(case['responses'])+1
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}]*count)
    original = transport.create
    rejected = []
    def create(**request):
        body = original(**request).model_dump()
        attempt = len(transport.requests)-1
        tokens = 100
        if attempt < count-1:
            item = case['responses'][attempt]
            rejected.append(failed_response(item)['choices'][0]['message'])
            body['choices'][0]['message'].update({key: rejected[-1][key] for key in ('content','reasoning_content')})
            tokens = item['completion_tokens']
        else:
            ref = request_packet(request)['views']['current']['records'][0]['ref']
            body['choices'][0]['message']['content'] = tagged_review(flat_report(ref))
        # Exercise the real shared output pool, not just a request counter.
        ledger = request['step_ledger']
        rid = f'synthetic-{attempt}'
        ledger.reserve(rid, request['budget_role'], request['max_tokens'])
        ledger.settle(rid, {'prompt_tokens': 1, 'completion_tokens': tokens, 'total_tokens': tokens+1})
        transport.last_request_id = rid
        return Completion(body)
    transport.create = create
    assert predict(actor, obs) == ['DONE']
    assert actor.total_steps == 1 and len(transport.requests) == count
    assert actor.pending == f'original-{count}' and actor.execution_journal.position == 1
    for request in transport.requests[1:]:
        assert not any(m.get('role') in ('assistant','tool') for m in request['messages'])
        assert context_size(request['messages'])[1] < 32000
        assert request_packet(request)['views']['current']['records'][0]['artifact']['verification'] == dict.fromkeys(CHECKS,'unknown')
    trace = actor.last_trace['mini_recovery']
    assert trace['report_rejections'] == count-1 and trace['native_rejections'] == 0
    ledger = actor.step_ledger.snapshot()
    assert ledger['requests'] == count and ledger['repair_counts']['executor'] == count-1
    assert ledger['charged_output'] == sum(i['completion_tokens'] for i in case['responses'])+100
    assert ledger['output_limit'] == 32000 and actor.contract.tool_repair_retries == 2
    actor.close()


@pytest.mark.parametrize('version', ['v4','v6'])
def test_real_failure_sizes_native_pairs_can_be_readmitted_by_dropping_whole_old_turns(version):
    case = FIXTURES[version]
    request = request_with_history(case['base_native_text_chars'])
    context = '界'*1000  # 3000 UTF8 bytes; logical chars differ from bytes.
    for item in case['responses']:
        observed = failed_response(item)
        request = repair_messages(request, observed, StreamProtocolError('Synthetic native error'), role='executor')
    original = deepcopy(request)
    assert context_size(request['messages'])[1] > 32000
    value, lengths, trace = admit_request(request, [3],
        contract=CUAContract(context_max_text_chars=32000, context_rough_text_token_budget=12000,
                             taskviews_context_bytes=8000), context=context, label='TaskViews:')
    assert request == original and lengths == [] and trace['old_turns_removed'] == 1
    assert value['tools'] == original['tools']
    check_tool_pairs(value['messages'])
    suffix = value['messages'][1:]
    assert suffix[0]['content'][:2] == original['messages'][4]['content']
    assert suffix[1:] == original['messages'][5:]  # Original reasoning and IDs intact.
    assert sum(p.get('text','').startswith(TASK_PREFIX) for m in value['messages']
        if isinstance(m.get('content'),list) for p in m['content']) == 1
    actual = deepcopy(value['messages'])
    actual[-1]['content'].append({'type':'text','text':'TaskViews:\n'+context})
    assert context_size(actual) == (trace['actual_payload_chars'],trace['actual_text_chars'])
    assert trace['actual_text_chars'] <= 32000


def test_native_error_long_reasoning_readmits_in_the_actual_mini_loop(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action':'left_click'}]*2+[{'action':'made_up'},{'action':'key','keys':['Escape']}])
    original = transport.create
    def create(**request):
        body = original(**request).model_dump()
        n = len(transport.requests)
        body['choices'][0]['message']['reasoning_content'] = ('N'*22307 if n==3 else 'H'*6000 if n<3 else '')
        return Completion(body)
    transport.create = create
    predict(actor, obs)
    predict(actor, obs)
    assert predict(actor, obs) == ['pyautogui.press("escape")']
    trace = actor.last_trace['mini_recovery']
    assert trace['native_rejections'] == 1 and trace['report_rejections'] == 0
    assert trace['admissions'][1]['old_turns_removed'] > 0
    repaired = transport.requests[-1]['messages']
    candidate = next(m for m in repaired if m.get('tool_calls',[{}])[0].get('id')=='original-3')
    assert candidate['reasoning_content'] == 'N'*22307
    assert any(m.get('tool_call_id')=='original-3' for m in repaired)
    check_tool_pairs(repaired)
    assert context_size(repaired)[1] <= 32000
    value = request_packet(transport.requests[-1])
    assert value['views']['current']['records'][0]['artifact']['verification'] == dict.fromkeys(CHECKS,'unknown')
    latest = value['views']['attempts']['records'][-1]
    assert latest['tool']['arguments'] == {'action':'left_click'}
    assert original_event(actor,value,latest)['tool'] == latest['tool']
    for ref in (latest['before'],latest['after']):
        assert original_event(actor,value,{'ref':ref})['kind'] == 'observation'
    assert actor.total_steps == 3 and actor.step_ledger.repair_counts['executor'] == 1
    actor.close()


def test_report_and_native_errors_share_one_original_pool_and_never_dispatch_rejected_calls(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action':'made_up'}]+[{'action':'terminate','status':'success'}]*3)
    original = transport.create
    def create(**request):
        body = original(**request).model_dump()
        body['choices'][0]['message']['content'] = 'No tagged report'
        return Completion(body)
    transport.create = create
    with pytest.raises(ReviewError, match='missing_tag'):
        predict(actor, obs)
    assert len(transport.requests) == 3 and actor.total_steps == 1
    assert actor.step_ledger.repair_counts == {'executor':2,'advisory':0}
    assert actor.mini_recovery_trace['native_rejections'] == 1 and actor.mini_recovery_trace['report_rejections'] == 2
    assert actor.executions == [] and actor.execution_journal.decision is None
    actor.close()


def test_required_native_reply_alone_too_large_stops_before_an_extra_request(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[{'action':'made_up'}])
    original = transport.create
    def create(**request):
        body = original(**request).model_dump()
        body['choices'][0]['message']['reasoning_content'] = 'N'*33000
        return Completion(body)
    transport.create = create
    with pytest.raises(ReadAnomaly, match='required current input and native pairs'):
        predict(actor, obs)
    assert len(transport.requests) == 1 and actor.execution_journal.decision is None
    actor.close()


@pytest.mark.parametrize('stop', ['unknown_output_usage', 'deadline', 'zero_repairs'])
def test_report_recovery_cannot_bypass_original_output_time_or_repair_limits(monkeypatch, tmp_path, stop):
    contract = CUAContract(history_n=20, image_max=1, fold_size=1, context_max_text_chars=32000,
        context_max_payload_chars=2000000, context_reserve_chars=10000,
        context_rough_text_token_budget=12000, taskviews_context_bytes=8000,
        tool_repair_retries=0 if stop=='zero_repairs' else 2)
    actor, obs, transport = make_actor(monkeypatch, tmp_path, contract=contract,
        actions=[{'action':'terminate','status':'success'}]*3)
    original = transport.create
    def create(**request):
        body = original(**request).model_dump()
        body['choices'][0]['message']['content']='No report'
        ledger=request['step_ledger']
        if stop=='unknown_output_usage':
            rid=str(len(transport.requests))
            ledger.reserve(rid,'executor',request['max_tokens'])
            ledger.settle(rid,None)  # Unknown usage retains the full original reservation.
        elif stop=='deadline':
            ledger.deadline=0
        return Completion(body)
    transport.create=create
    with pytest.raises(ReviewError):
        predict(actor,obs)
    assert len(transport.requests)==(2 if stop=='unknown_output_usage' else 1)
    if stop=='unknown_output_usage':
        assert actor.step_ledger.charged_output==32000
    assert not actor.executions
    actor.close()


def test_disabled_context_rescue_does_not_silently_remove_history():
    request=request_with_history(2000)
    with pytest.raises(ReadAnomaly):
        admit_request(request,[3],contract=CUAContract(context_max_text_chars=1000,enable_context_rescue=False))


@pytest.mark.parametrize('broken', ['orphan','missing','duplicate','boundary','task','image'])
def test_readmission_rejects_lost_task_image_or_tool_pair(broken):
    request = request_with_history(1000)
    if broken=='orphan':
        request['messages'][3]['tool_call_id']='other'
    elif broken=='missing':
        request['messages'][3]={'role':'user','content':'unresolved'}
    elif broken=='duplicate':
        request['messages'].insert(4,deepcopy(request['messages'][3]))
    elif broken=='task':
        request['messages'][1]['content']=[]
    elif broken=='image':
        request['messages'][4]['content']=[]
    with pytest.raises(ReadAnomaly):
        admit_request(request,[2 if broken=='boundary' else 3],contract=CUAContract())


@pytest.mark.parametrize('kind', ['context_max_text_chars','context_max_payload_chars','context_rough_text_token_budget'])
def test_all_actual_input_limits_include_optional_view_and_label(kind):
    request = request_with_history(1000)
    contract = CUAContract(**{kind: 900 if kind!='context_rough_text_token_budget' else 225})
    value,lengths,trace=admit_request(request,[3],contract=contract,context='V'*300,label='TaskViews:')
    assert lengths == [] and trace['old_turns_removed'] == 1
    assert context_size(value['messages'])[1] < 900


def test_flat_report_has_one_object_and_preserves_explicit_observation_facts():
    value=flat_report(9)
    encoded=tagged_review(value)
    assert encoded.count('{') == encoded.count('}') == 1
    note=validate_review(encoded,final=True)
    assert all(note['checks'][key]=={'ref':9,'observed':'Synthetic fact'} for key in CHECKS)
    assert validate_review(tagged_review({'no_artifact':'Only changes a setting'}),final=True)['applicable'] is False
    assert 'reasoning_content' not in str(report_feedback(request_with_history(1000),ReviewError('missing_tag','Use report'))['messages'][-1])


@pytest.mark.parametrize('change', [lambda r:r.update(extra=True), lambda r:r.update(source_confirmed=[True,'fact']),
    lambda r:r.update(source_confirmed=[1]),lambda r:r.update(content_previewed=[1,'']),
    lambda r:r.pop('destination_confirmed')])
def test_flat_report_never_fills_missing_or_bad_evidence(change):
    value=flat_report()
    change(value)
    with pytest.raises(ReviewError):
        validate_review(tagged_review(value),final=True)


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
@pytest.mark.parametrize('last', ['valid_review', 'missing_tag', 'inspect'])
def test_source_bound_feedback_recovers_or_stops_within_the_same_two_retries(monkeypatch, tmp_path, mode, last):
    """Reproduce the incident's failure sequence with synthetic facts and GUI."""
    from kobe_views import mini_graph
    from ui_kobe.osworld import telemetry

    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    actions = [{'action': 'terminate', 'status': 'success'}] * 3
    if last == 'inspect':
        actions[-1] = {'action': 'key', 'keys': ['Escape']}
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=actions)
    emitted = []
    monkeypatch.setattr(telemetry, 'emit', lambda name, **data: emitted.append({'event': name, **deepcopy(data)}))
    original = transport.create
    packet_texts = []
    current_refs = []

    def create(**request):
        body = original(**request).model_dump()
        attempt = len(transport.requests)
        text = next(p['text'] for p in request['messages'][-1]['content']
                    if p.get('text', '').startswith(('TaskViews:', 'TaskViews graph:')))
        encoded = text.split('\n', 1)[1]
        packet_texts.append(encoded)
        value = json.loads(encoded)
        view = mini_graph.expand(value) if mode != 'legacy' else value
        current = view['views']['current']['records'][0]
        current_refs.append(current['ref'])
        assert len(encoded.encode('utf-8')) <= 3000
        assert current['artifact']['verification'] == dict.fromkeys(CHECKS, 'unknown')
        message = body['choices'][0]['message']
        message['reasoning_content'] = 'Private rejected reasoning must not be replayed'
        if attempt == 2:
            bad = actor.execution_journal.db.execute(
                "SELECT seq FROM events WHERE json_extract(payload,'$.kind')!='observation' LIMIT 1").fetchone()[0]
            message['content'] = tagged_review(flat_report(bad))
        elif attempt == 3 and last == 'valid_review':
            message['content'] = tagged_review(flat_report(current['ref']))
        else:
            message['content'] = 'No tagged report'
        return Completion(body)

    transport.create = create
    try:
        if last == 'missing_tag':
            with pytest.raises(ReviewError, match='missing_tag'):
                predict(actor, obs)
            assert not actor.executions and actor.execution_journal.decision is None
            exhausted = [e for e in emitted if e['event'] == 'mini_report_recovery_exhausted']
            assert len(exhausted) == 1
            assert exhausted[0]['failures'] == ['missing_tag', 'invalid_reference', 'missing_tag']
            assert exhausted[0]['reason'] == 'regeneration_limit' and not exhausted[0]['action_executed']
        else:
            assert predict(actor, obs) == (['DONE'] if last == 'valid_review' else ['pyautogui.press("escape")'])
            assert actor.pending == 'original-3' and actor.execution_journal.position == 1
        assert actor.total_steps == 1 and len(transport.requests) == 3
        assert actor.step_ledger.repair_counts['executor'] == 2
        assert actor.step_ledger.snapshot()['output_limit'] == 32000
        assert len(set(packet_texts)) == 1  # Recovery does not repack facts or change the view budget.
        feedback = [p['text'] for m in transport.requests[-1]['messages'] if m['role'] == 'user'
                    for p in m.get('content', []) if p.get('text', '').startswith('Mini auxiliary report rejected')]
        assert len(feedback) == 2
        for key in CHECKS:
            assert key + '.ref=' in feedback[-1]
        assert f'Current observation seq={current_refs[-1]}' in feedback[-1]
        assert 'valid number alone is not content proof' in feedback[-1]
        assert 'SAME response' in feedback[-1] and 'OBS_SEQ' in feedback[-1]
        assert 'Synthetic fact' not in feedback[-1] and 'Private rejected reasoning' not in str(transport.requests[-1])
        assert not any(m['role'] in ('assistant', 'tool') for m in transport.requests[-1]['messages'])
    finally:
        actor.close()


def test_recovery_template_contains_current_limits_but_no_invented_observations(monkeypatch):
    from kobe_views import artifact_view
    monkeypatch.setattr(artifact_view, 'MAX_OBSERVED_CHARS', 17)
    request = request_with_history(1000)
    before = deepcopy(request)
    result = report_feedback(request, ReviewError('invalid_reference', '字段' * 2000), current_ref=63)
    text = result['messages'][-1]['content'][0]['text']
    assert request == before
    assert 'Current observation seq=63' in text and 'each fact 1..17 chars' in text
    assert len(text.encode('utf-8')) < 3000 and '字段' not in text
    assert '[OBS_SEQ,' in text and '"OBS_SEQ"' not in text and '"VISIBLE_FACT"' in text
    assert 'unquoted positive JSON integer observation seq' in text
    import re
    template = re.search(r'<artifact_review>.*?</artifact_review>', text).group(0)
    filled = template.replace('OBS_SEQ', '63').replace('PATH', 'file.png').replace('VISIBLE_FACT', 'Visible fact')
    note = validate_review(filled, final=True)
    assert all(check['ref'] == 63 for check in note['checks'].values())
    for bad in (0, -1, True, '63'):
        with pytest.raises(ReadAnomaly):
            report_feedback(request, ReviewError('missing_tag', 'Missing report'), current_ref=bad)


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
@pytest.mark.parametrize('quoted', [False, True])
def test_transmitted_recovery_shape_accepts_integer_refs_without_coercing_strings(monkeypatch, tmp_path, mode, quoted):
    """The incident's third response must satisfy the real schema and journal gate."""
    import re
    from kobe_views import mini_graph

    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}] * 3)
    original = transport.create

    def create(**request):
        body = original(**request).model_dump()
        content = 'No tagged report'
        if len(transport.requests) == 3:
            packet_text = next(p['text'] for p in request['messages'][-1]['content']
                               if p.get('text', '').startswith(('TaskViews:', 'TaskViews graph:')))
            value = json.loads(packet_text.split('\n', 1)[1])
            view = mini_graph.expand(value) if mode != 'legacy' else value
            ref = view['views']['current']['records'][0]['ref']
            feedback = [p['text'] for m in request['messages'] if m['role'] == 'user'
                        for p in m.get('content', []) if p.get('text', '').startswith('Mini auxiliary report rejected')][-1]
            template_section = feedback.split('Replace every placeholder in this shape using your actual evidence: ', 1)[1]
            shape = re.search(r'<artifact_review>.*?</artifact_review>', template_section).group(0)
            number = json.dumps(str(ref)) if quoted else str(ref)
            content = shape.replace('OBS_SEQ', number).replace('PATH', 'file.png').replace('VISIBLE_FACT', 'Synthetic fact')
        body['choices'][0]['message']['content'] = content
        return Completion(body)

    transport.create = create
    try:
        if quoted:
            with pytest.raises(ReviewError, match='expected positive integer observation seq'):
                predict(actor, obs)
            assert not actor.executions and actor.execution_journal.decision is None
        else:
            assert predict(actor, obs) == ['DONE']
            assert actor.pending == 'original-3'
        assert len(transport.requests) == 3 and actor.total_steps == 1
        assert actor.step_ledger.repair_counts['executor'] == 2
    finally:
        actor.close()
