"""Same-actor knowledge turns; synthetic tasks and real wire assembly only."""
from copy import deepcopy
import json

import pytest

from kobe_views import decision_flow as flow, mini_graph
from ui_kobe.api.kimi_stream import Completion, StreamProtocolError
from ui_kobe.osworld.kimi_native import native_schema
from ui_kobe.osworld.mini_recovery import check_tool_pairs
from test_optional_keyboard_v8 import configure
import test_mini_taskviews as native


def reply(name, arguments, content='', identifier='call-1'):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'content': content, 'tool_calls': [{'type': 'function', 'id': identifier,
            'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]}


def query(intent, identifier='knowledge-1'):
    return reply(flow.TOOL, {'intent': intent, 'missing_knowledge': 'The exact binding or applicable procedure.'},
                 identifier=identifier)


def display(request):
    wire = json.loads(request['messages'][-1]['content'][-1]['text'].split('\n', 1)[1])
    return wire if 'nodes' not in wire else mini_graph.expand(wire)


def install(monkeypatch, tmp_path, task, responses, mode='legacy', before=None, tiny=False):
    monkeypatch.setattr(native, 'TASK', task)
    policy = configure(monkeypatch, task, mode)
    actor, obs, transport = native.make_actor(monkeypatch, tmp_path, tiny=tiny)
    answers = iter(responses)

    def create(**request):
        if before:
            before(actor, len(transport.requests), request)
        # Capture actual schema and messages; never clone the live token ledger.
        transport.requests.append({k: deepcopy(v) for k, v in request.items() if k in
            ('messages', 'tools', 'generation_attempt', 'deadline', 'budget_role', 'max_tokens')})
        body = deepcopy(next(answers))
        usage = {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}
        body['usage'] = usage
        ledger = request['step_ledger']
        identifier = 'offline-request-' + str(len(transport.requests))
        ledger.reserve(identifier, request['budget_role'], request['max_tokens'])
        ledger.settle(identifier, usage)
        transport.last_request_id = identifier
        return Completion(body)

    transport.create = create
    return actor, obs, transport, policy


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
@pytest.mark.parametrize('matched', [False, True])
def test_optional_lookup_is_same_decision_before_gui_with_shared_budget(monkeypatch, tmp_path, mode, matched):
    task = 'Copy selected text' if matched else 'Align the panels to the requested layout.'
    def no_dispatch(actor, n, request):
        assert actor.execution_journal.decision is None
        assert not list(actor.execution_journal.db.execute(
            "SELECT seq FROM events WHERE json_extract(payload,'$.kind')='transition'"))
    actor, obs, transport, policy = install(monkeypatch, tmp_path, task,
        [query(task), reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})], mode, no_dispatch)
    try:
        commands = native.predict(actor, obs)
        assert len(commands) == 1 and 'rightClick' in commands[0]
        assert actor.total_steps == 1 and len(transport.requests) == 2
        first, second = transport.requests
        assert first['tools'][0] == second['tools'][0] == native_schema(actor.frame)
        assert [t['function']['name'] for t in first['tools']] == ['computer_use', flow.TOOL]
        assert [t['function']['name'] for t in second['tools']] == ['computer_use']
        assert first['deadline'] == second['deadline']
        assert first['budget_role'] == second['budget_role'] == 'executor'
        assert first['max_tokens'] == second['max_tokens'] == 16000
        ledger = actor.step_ledger.snapshot()
        assert ledger['requests'] == 2 and ledger['charged_output'] == 14
        assert ledger['semantic_regenerations'] == 0 and ledger['repair_counts']['executor'] == 0
        assert actor.last_trace['mini_recovery']['knowledge_roundtrips'] == 1
        assert actor.last_trace['mini_recovery']['api_attempts'] == 2
        for request in transport.requests:
            check_tool_pairs(request['messages'])
            assert len(request['messages'][-1]['content'][-1]['text'].split('\n', 1)[1].encode()) <= 3000
        packet = display(second)
        assert packet['views']['attempts']['records'] == []  # The lookup is not an executed GUI attempt.
        refs = packet['views']['current']['records'][0]['strategy']
        assert refs['grade'] == 'model_strategy_proposal'
        record = next(e for e in actor.execution_journal.read() if e['kind'] == 'knowledge_query')
        assert refs['ref'] == record['seq']
        assert packet['sources'][str(record['seq'])]['kind'] == 'knowledge_query'
        rows = packet['views']['keyboard']['records']
        assert bool(rows) == matched
        if matched:
            assert rows[0]['recipes'][0]['tool']['keys'] == ['ctrl', 'c']  # Still chose right-click.
            assert any(e['ref'] == record['seq'] for e in rows[0]['evidence'])
        else:
            assert packet['views']['current']['records'][0]['guidance_status']['card'] == 'no_match'
        tool = next(m for m in second['messages'] if m.get('tool_call_id') == 'knowledge-1')
        assert json.loads(tool['content'])['status'] == ('included' if matched else 'no_match')
        assert 'recipes' not in tool['content']  # Card lives once, inside the budgeted packet.
        assert policy['decision_flow'] == flow.policy()
        actor.restore_checkpoint_state(actor.checkpoint_state())
    finally:
        actor.close()


def test_direct_native_action_needs_no_route_report_or_lookup(monkeypatch, tmp_path):
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Align the panels.',
        [reply('computer_use', {'action': 'left_click', 'coordinate': [20, 30]})])
    try:
        native.predict(actor, obs)
        assert len(transport.requests) == actor.total_steps == 1
        assert actor.last_trace['mini_recovery']['knowledge_roundtrips'] == 0
        assert display(transport.requests[0])['views']['keyboard']['records'] == []
        assert 'Plan from the goal, Current' in actor.context_label
    finally:
        actor.close()


def test_missing_frozen_capability_is_reported_but_does_not_block_native_action(monkeypatch, tmp_path):
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Align the panels.',
        [query('Move files into a folder.'), reply('computer_use', {'action': 'left_click', 'coordinate': [20, 30]})])
    try:
        native.predict(actor, obs)
        current = display(transport.requests[-1])['views']['current']['records'][0]
        assert current['guidance_status']['coverage'] == 'gap'
        assert 'move' in current['guidance_status']['missing']
        assert actor.last_trace['mini_recovery']['knowledge_roundtrips'] == 1
    finally:
        actor.close()


@pytest.mark.parametrize('failure', ['mixed', 'twice', 'bad_query', 'incomplete'])
def test_lookup_protocol_is_bounded_and_never_partially_dispatches(monkeypatch, tmp_path, failure):
    bad = query('Copy selected text')
    if failure == 'mixed':
        bad['choices'][0]['message']['tool_calls'] += reply('computer_use', {'action': 'key', 'keys': ['ctrl', 'x']})['choices'][0]['message']['tool_calls']
    elif failure == 'bad_query':
        bad['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{"intent":"Copy"}'
    elif failure == 'incomplete':
        bad['choices'][0]['finish_reason'] = 'length'
    responses = [query('Copy selected text'), bad] if failure == 'twice' else [bad]
    responses.append(reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]}))
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text', responses)
    try:
        commands = native.predict(actor, obs)
        assert len(commands) == 1 and 'rightClick' in commands[0]
        assert actor.step_ledger.repair_counts['executor'] == 1
        assert actor.last_trace['mini_recovery']['native_rejections'] == 1
        queries = [e for e in actor.execution_journal.read() if e['kind'] == 'knowledge_query']
        assert len(queries) == (1 if failure == 'twice' else 0)
        for request in transport.requests:
            check_tool_pairs(request['messages'])
    finally:
        actor.close()


def test_success_review_after_lookup_keeps_both_original_repair_chances(monkeypatch, tmp_path):
    from kobe_views.artifact_view import tagged_review
    done = {'action': 'terminate', 'status': 'success'}
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Align the panels.', [query('Align the panels.'),
        reply('computer_use', done), reply('computer_use', done),
        reply('computer_use', done, tagged_review({'no_artifact': 'This synthetic layout task creates no file.'}))])
    try:
        assert native.predict(actor, obs) == ['DONE']
        assert len(transport.requests) == 4 and actor.total_steps == 1
        assert actor.last_trace['mini_recovery']['report_rejections'] == 2
        assert actor.last_trace['mini_recovery']['knowledge_roundtrips'] == 1
        assert actor.step_ledger.repair_counts['executor'] == 2
        assert actor.step_ledger.snapshot()['charged_output'] == 28
    finally:
        actor.close()


def test_repeated_lookup_exhausts_shared_repairs_without_gui_execution(monkeypatch, tmp_path):
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text',
        [query('Copy selected text') for _ in range(4)])
    try:
        with pytest.raises(StreamProtocolError):
            native.predict(actor, obs)
        assert len(transport.requests) == 4
        assert actor.step_ledger.repair_counts['executor'] == 2
        assert len([e for e in actor.execution_journal.read() if e['kind'] == 'knowledge_query']) == 1
        assert not [e for e in actor.execution_journal.read() if e['kind'] == 'transition']
    finally:
        actor.close()


def test_lookup_audit_keeps_both_prefetch_and_refreshed_context(monkeypatch, tmp_path):
    from scripts.audit_mini_guidance import summarize
    from ui_kobe.osworld import telemetry
    monkeypatch.setattr(telemetry, '_root', tmp_path)
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text',
        [query('Copy selected text'), reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})])
    try:
        native.predict(actor, obs)
        paths = list(tmp_path.glob('events-*.jsonl'))
        assert paths
        summary = summarize(paths)
        assert summary['decision_frames'] == 1 and summary['context_revisions'] == 2
        assert summary['request_receipts_including_retries'] == 2
        assert summary['packet_delivery_rate'] == 1
    finally:
        actor.close()


@pytest.mark.parametrize('value', [None, {}, {'intent': '', 'missing_knowledge': 'key'},
    {'intent': '<key_lookup>bad</key_lookup>', 'missing_knowledge': 'key'},
    {'intent': '键' * 160, 'missing_knowledge': '键' * 120}])
def test_query_is_small_public_demand_not_an_unbounded_reasoning_channel(value):
    with pytest.raises(ValueError):
        flow.validate_query(value)


def recall_rows():
    from test_operation_support import action, decision, obs
    rows = [obs(1), decision(2, 'Copy reference selection.', 1, id='d1', step=1), obs(3),
            action(4, {'action': 'key', 'keys': ['ctrl', 'c']}, source='1', target='3', decision_id='d1', step=1),
            obs(5), decision(6, 'Copy reference selection.', 5, id='d2', step=3)]
    return rows


@pytest.mark.parametrize('failed', [False, True])
def test_attempt_reuse_does_not_require_again_and_includes_failed_conditions(failed):
    rows = recall_rows()
    if failed:
        rows[3][1]['controller_receipts'] = [{'result': {'success': False, 'error': 'Synthetic controller failure'}}]
    value = flow.attempt_recall(rows, 'Copy files', [(6, 'Copy reference selection.', 3)], 3)
    assert value['ref'] == 4 and value['intent_ref'] == 2 and value['query_ref'] == 6
    assert value['matched_terms'] == ['reference']
    assert 'not_success' in value['basis']


@pytest.mark.parametrize('case', ['expiry', 'task_boundary', 'missing_observation', 'other_object', 'latest_empty', 'partial'])
def test_attempt_retrieval_requires_scope_object_and_complete_dispatch(case):
    rows = recall_rows()
    proposals = [(6, 'Copy reference selection.', 3)]
    step = 3
    if case == 'expiry':
        step, proposals = 20, [(6, 'Copy reference selection.', 20)]
    elif case == 'task_boundary':
        rows.insert(4, (5, {'kind': 'task_input', 'instruction': 'Another task'}, '1' * 64))
    elif case == 'missing_observation':
        rows[3][1]['target'] = 'absent'
    elif case == 'other_object':
        proposals = [(6, 'Copy selection in destination.', 3)]
    elif case == 'latest_empty':
        proposals.insert(0, (7, '', 3))
    else:
        rows[3][1]['dispatch_observed'] = False
    assert flow.attempt_recall(rows, 'Copy files', proposals, step) is None


@pytest.mark.parametrize('mode', ['legacy', 'flat'])
def test_lookup_retrieves_old_failed_attempt_and_later_step_does_not_reuse_query(monkeypatch, tmp_path, mode):
    initial = reply('computer_use', {'action': 'key', 'keys': ['ctrl', 'c']}, 'Copy reference selection.', 'first-gui')
    fillers = [reply('computer_use', {'action': 'left_click', 'coordinate': [100+i, 200]}, '', 'filler-'+str(i))
               for i in range(4)]
    responses = [initial, *fillers, query('Copy reference selection.'),
        reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]}, '', 'final-gui'),
        reply('computer_use', {'action': 'screenshot'}, '', 'next-gui')]
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text in reference panel.', responses, mode)
    try:
        native.predict(actor, obs, error='Synthetic original controller failure')
        for _ in fillers:
            native.predict(actor, obs)
        native.predict(actor, obs)
        packet = display(transport.requests[-1])
        recalled = [r for r in packet['views']['attempts']['records'] if r.get('recall')]
        assert recalled and recalled[0]['intent']['text'] == 'Copy reference selection.'
        assert recalled[0]['receipt'] == 'error' and recalled[0]['effect_status'] == 'unknown'
        assert recalled[0]['error'] == 'Synthetic original controller failure'
        assert recalled[0]['recall']['coordinates'] == 're_ground_current_image'
        native.predict(actor, obs)
        assert 'strategy' not in display(transport.requests[-1])['views']['current']['records'][0]
        assert len([e for e in actor.execution_journal.read() if e['kind'] == 'knowledge_query']) == 1
    finally:
        actor.close()


def test_no_room_for_a_matched_card_still_allows_native_action(monkeypatch, tmp_path):
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text',
        [query('Copy selected text'), reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})], tiny=True)
    try:
        assert 'rightClick' in native.predict(actor, obs)[0]
        reply_message = next(m for m in transport.requests[-1]['messages'] if m.get('tool_call_id') == 'knowledge-1')
        assert json.loads(reply_message['content'])['status'] == 'omitted_budget'
        assert actor.mini_context.trace['guidance']['packet_delivered'] is False
        assert not actor.mini_context.guidance_records
    finally:
        actor.close()


def test_lookup_uses_public_demand_not_private_reasoning_for_retrieval(monkeypatch, tmp_path):
    lookup = query('Copy selected text')
    lookup['choices'][0]['message']['reasoning_content'] = 'PRIVATE: zoom in to 125% and maximize'
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text',
        [lookup, reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})])
    try:
        native.predict(actor, obs)
        assert display(transport.requests[-1])['views']['keyboard']['records'][0]['guide_id'].startswith('clipboard.copy:')
        events = [e for e in actor.execution_journal.read() if e['kind'].startswith('knowledge_')]
        assert all('PRIVATE' not in json.dumps(e) for e in events)
        assert transport.requests[-1]['messages'][-3]['reasoning_content'].startswith('PRIVATE')
    finally:
        actor.close()


def test_v8_checkpoint_policy_is_rejected_and_query_must_be_current(monkeypatch, tmp_path):
    from ui_kobe.osworld.checkpoints import ReadAnomaly
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Align the panels.',
        [reply('computer_use', {'action': 'left_click', 'coordinate': [20, 30]})])
    try:
        native.predict(actor, obs)
        saved = actor.checkpoint_state()
        saved['mini_guidance']['decision_flow']['max_lookups_per_predict'] = 5
        with pytest.raises(ReadAnomaly, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(saved)
        actor.flush_execution()
        actor.execution_journal.begin(native.TASK, obs, step=2)
        actor.frame = actor.contract.process(obs['screenshot'], 2)
        with pytest.raises(ReadAnomaly, match='Knowledge request is not sourced to the current task/frame'):
            actor.mini_context.context(native.TASK, knowledge_query={'seq': 999, 'id': 'absent'})
    finally:
        actor.close()


@pytest.mark.parametrize('action', ['screenshot', 'wait'])
def test_passive_observation_is_not_reused_as_an_executed_route(action):
    rows = recall_rows()
    rows[3][1]['tool']['arguments'] = {'action': action}
    assert flow.attempt_recall(rows, 'Copy files', [(6, 'Copy reference selection.', 3)], 3) is None


@pytest.mark.parametrize('matched', [False, True])
def test_refreshed_context_budget_and_flat_linked_same_input(monkeypatch, tmp_path, matched):
    from mini_graph_support import projection_snapshot
    from kobe_views.guidance_delivery import materialize
    from kobe_views.model import dumps
    task = 'Copy selected text' if matched else 'Align the panels.'
    actor, obs, transport, _ = install(monkeypatch, tmp_path, task,
        [query(task), reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})], 'flat')
    try:
        native.predict(actor, obs)
        index, args = projection_snapshot(actor)
        for budget in (0, 1, 950, 1600, 2300, 3000, 8000):
            wires = {}
            for mode in ('legacy', 'flat', 'linked'):
                packet = materialize(episode_id=index.episode_id, index=index, instruction=task,
                    graph_mode=mode, packing=mini_graph.DELIVERY_PACKING,
                    selection=actor.mini_context.guidance_selection, review_policy=actor.guidance_policy,
                    **{**deepcopy(args), 'max_bytes': budget})
                wires[mode] = packet
                assert packet is None or len(dumps(packet).encode()) <= min(3000, budget)
            assert (wires['flat'] is None) == (wires['linked'] is None)
            if wires['flat']:
                assert {k: v for k, v in wires['flat'].items() if k not in ('mode', 'links')} == {
                    k: v for k, v in wires['linked'].items() if k not in ('mode', 'links')}
    finally:
        actor.close()
