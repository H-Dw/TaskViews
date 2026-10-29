"""Generic reading, navigation and request delivery; no benchmark answers."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance, mini_graph
from kobe_views.guidance_semantics import analyze
from kobe_views.keyboard_selection import task_keyboard_policy
from kobe_views.operation_support import adjustment_chain, build, intent_excerpt, navigation_recall, reading_notes
from test_keyboard_guidance import names, route
from test_operation_support import action, decision, obs


def chain_rows():
    rows = [obs(1), decision(2, 'Open the view menu to zoom in.', 1, id='a', step=1),
            action(3, {'action': 'left_click', 'coordinate': [1, 2]}, decision_id='a', step=1),
            obs(4), decision(5, 'Set zoom to 100%.', 4, id='b', step=2),
            action(6, {'action': 'left_click', 'coordinate': [8, 9]}, decision_id='b', step=2),
            obs(7), decision(8, 'Maximize the window.', 7, id='c', step=3),
            action(9, {'action': 'key', 'keys': ['alt', 'f10']}, decision_id='c', step=3)]
    for _, e, _ in rows:
        if 'instruction' in e:
            e['instruction'] = 'Read the documents'
    return rows


def test_distinct_commands_share_reading_goal_but_do_not_prove_failure():
    rows = chain_rows()
    chain = adjustment_chain(rows, 'Read the documents', 4)
    assert len(chain['adjustments']) == 3 and chain['effect'] == 'unknown'
    assert {1, 2, 3, 4, 5, 6, 7, 8, 9} == {e['ref'] for e in chain['evidence']}
    support = build(rows=rows, instruction='Read the documents', proposals=[], step=4, observation_ref=10)
    assert support['feedback'][0]['kind'] == 'view_adjustment_chain'
    assert names(route(instruction='Read the documents', adjustment_chain=chain,
                       proposals=[(8, 'Maximize the window.', 3)], step=4))[0] == 'view.readability'
    rows[4][1]['response'] = json.dumps({'content': 'A zoom dropdown appeared. Let me select 100% to read clearly.'})
    assert len(adjustment_chain(rows, 'Read the documents', 4)['adjustments']) == 3
    # Numeric selection alone has no preceding zoom provenance.
    assert adjustment_chain(rows[3:6], 'Read the documents', 3) is None


@pytest.mark.parametrize('case', ['failed', 'no_decision', 'no_observation', 'navigation', 'edit', 'expiry', 'task', 'reported'])
def test_adjustment_chain_has_source_scope_and_lifetime(case):
    rows = chain_rows()
    if case == 'failed':
        rows[-1][1]['controller_receipts'][0]['result']['success'] = False
    elif case == 'no_decision':
        rows[-1][1].pop('decision_id')
    elif case == 'no_observation':
        rows[-2][1]['source'] = 'absent'
    elif case in ('navigation', 'edit', 'reported'):
        text = {'navigation': 'Open another document.', 'edit': 'Type the new text.',
                'reported': 'The table shows 12.75.'}[case]
        rows += [obs(10), decision(11, text, 10, step=4, instruction='Read the documents')]
    elif case == 'task':
        assert adjustment_chain(rows, 'Set zoom to 125%', 4) is None
        return
    assert adjustment_chain(rows, 'Read the documents', 10 if case == 'expiry' else 4) is None


def test_ratio_proposal_is_not_a_precise_task_requirement_and_pending_stage_wins():
    args = dict(instruction='Read the document', proposals=[(2, 'Set zoom to 100%.', 1)])
    selection = route(**args)
    assert names(selection)[0] == 'view.readability'
    assert selection['excluded'][0]['reason'] == 'proposed_ratio_not_task_requirement'
    assert names(route(**{**args, 'instruction': 'Set zoom to 125%'}))[0] == 'view.zoom_value'
    assert names(route(**args, pending_effect={'phase': 'confirm_once', 'refs': [2, 3]}))[0] == 'view.zoom_confirm'
    assert names(route(**args, pending_effect={'phase': 'inspect_effect', 'refs': [2, 3]}))[0] == 'view.zoom_check'


@pytest.mark.parametrize('text,expected', [
    ('I can read the text clearly.', True), ('I can now clearly read the values.', True),
    ('我现在能清楚读出文字。', True), ('Check whether I can read the text clearly.', False),
    ('If I can read the text clearly, continue.', False), ('I cannot read the text clearly.', False),
])
def test_readability_public_report_not_hypothesis(text, expected):
    assert any(s['kind'] == 'readable' for s in analyze(text)['states']) == expected


def test_reading_reports_preserve_different_observations_and_do_not_repeat_latest_only():
    rows = [obs(1), decision(2, 'Section Alpha shows 12.75.', 1), obs(3),
            decision(4, 'Section Beta shows 8.50. The total is 21.25. The difference is 4.25.', 3)]
    notes, _ = reading_notes(rows, 'Copy files', 5)
    assert [n['before'] for n in notes[:2]] == [3, 1]
    assert len(notes) == 2 and all(n['verification'] == 'unknown' for n in notes)
    assert all(line in rows[1][1]['response'] or line in rows[3][1]['response']
               for n in notes for line in n['text'].splitlines())
    assert reading_notes(rows + [action(6, {'action': 'type', 'text': 'edit'})], 'Copy files', 7)[0] == []
    assert reading_notes(rows, 'Copy files', 18)[0] == []
    assert reading_notes([obs(1), decision(2, 'Does the table show a difference? Maybe the amount is 8.', 1)], 'Copy files', 3)[0] == []


def test_public_numeric_list_keeps_its_heading_and_whole_rows_not_anonymous_numbers():
    text = 'I now have the meter readings. Let me record them:\n- Channel Alpha: 7.25\n- Channel Beta: 9.50\n\nOpen the next document.'
    notes, _ = reading_notes([obs(1), decision(2, text, 1)], 'Copy files', 3)
    assert notes[0]['text'] == 'I now have the meter readings.\n- Channel Alpha: 7.25\n- Channel Beta: 9.50'
    assert notes[0]['before'] == 1 and notes[0]['verification'] == 'unknown'
    for invalid in ('Let me get the meter readings:\n- Channel Alpha: 7.25',
                    'If the table shows these:\n- Channel Alpha: 7.25',
                    'Next actions:\n- Set zoom to 100%'):
        assert not reading_notes([obs(1), decision(2, invalid, 1)], 'Copy files', 3)[0]


def test_recall_is_bounded_public_text_not_success_or_coordinate_plan():
    rows = [obs(1), decision(2, 'The value is 3. Open the Archive window.', 1, id='nav', step=1),
            action(3, {'action': 'left_click', 'coordinate': [40, 50]}, decision_id='nav', step=1),
            obs(4), decision(5, 'Open the Archive window again.', 4, id='query', step=3)]
    proposals = [(5, 'Open the Archive window again.', 3)]
    recall = navigation_recall(rows, 'Copy files', proposals, 4)
    assert recall['ref'] == 3 and recall['intent_ref'] == 2 and recall['matched_terms'] == ['archive']
    assert recall['text'] == 'Open the Archive window.'
    assert navigation_recall(rows, 'Copy files', [(5, 'Open the Archive window.', 3)], 4) is None
    assert navigation_recall(rows, 'Copy files', [(5, 'Open the Settings window.', 3)], 4) is None
    assert navigation_recall(rows, 'Different task', proposals, 4) is None
    assert navigation_recall(rows, 'Copy files', proposals, 20) is None
    rows[2][1]['controller_receipts'][0]['result']['success'] = False
    assert navigation_recall(rows, 'Copy files', proposals, 4) is None
    assert intent_excerpt('Long report ' * 60 + '. Open the Archive window.') == 'Open the Archive window.'


@pytest.mark.parametrize('mode', ['legacy', 'flat'])
def test_actual_wire_views_carry_two_source_reports_and_related_attempt(monkeypatch, tmp_path, mode):
    from test_mini_taskviews import TASK, make_actor, packet, predict
    from test_mini_artifact_protocol import annotate
    from kobe_views.model import dumps
    policy = task_keyboard_policy({'instruction': TASK}, mode='task_capabilities')['mini_guidance']
    monkeypatch.setenv(guidance.ENV, json.dumps(policy))
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_PACKING', mini_graph.policy(mode,
        mini_graph.DELIVERY_PACKING if mode != 'legacy' else None)['packing'])
    actor, observation, transport = make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'left_click', 'coordinate': [40, 50]}, {'action': 'screenshot'},
        {'action': 'screenshot'}, {'action': 'screenshot'}])
    texts = ['Open the Archive window.', 'Section Alpha shows 12.75. The total is 12.75.',
             'Section Beta shows 8.50. Open the Archive window again.', '']
    annotate(transport, lambda request, attempt: texts[attempt-1])
    try:
        for _ in texts:
            predict(actor, observation)
        wire = packet(transport)
        display = wire if mode == 'legacy' else mini_graph.expand(wire)
        assert len(dumps(wire).encode()) <= 3000
        views = display['views']
        reports = [r for r in views['lessons']['records'] if r['grade'] == 'model_reading_proposal']
        assert {r['text'] for r in reports} == {'Section Alpha shows 12.75.\nThe total is 12.75.', 'Section Beta shows 8.50.'}
        assert {r['ref'] for r in reports} == {r['ref'] for r in views['current']['records'][0]['reading_progress']['reports']}
        assert all(r['verification'] == 'unknown' and str(r['before']) in display['sources'] for r in reports)
        attempt = views['attempts']['records'][0]
        assert attempt['recall']['coordinates'] == 're_ground_current_image'
        assert attempt['intent']['text'] == texts[0] and attempt['effect_status'] == 'unknown'
        assert len(transport.requests) == actor.total_steps == 4
        metrics = actor.mini_context.trace['operation_support']
        assert metrics['delivered'] and metrics['reading_reports_in_packet'] == 2
        assert metrics['navigation_recall_in_packet'] and metrics['model_adoption'] == 'unknown'
        assert all(metrics['view_records_in_packet'][v] for v in ('current', 'attempts', 'lessons'))
        from kobe_views.guidance_delivery import materialize
        from mini_graph_support import projection_snapshot
        index, args = projection_snapshot(actor)
        for limit in (0, 64, 1200, 1800, 2400, 3000, 5000):
            results = []
            for graph_mode in ('flat', 'linked'):
                value = materialize(episode_id=index.episode_id, index=index, instruction=TASK,
                    graph_mode=graph_mode, packing=mini_graph.DELIVERY_PACKING,
                    selection=actor.mini_context.guidance_selection, review_policy=policy,
                    **{**deepcopy(args), 'max_bytes': limit})
                assert value is None or len(dumps(value).encode()) <= min(limit, 3000)
                results.append(value)
            assert (results[0] is None) == (results[1] is None)
            if results[0]:
                assert {k: v for k, v in results[0].items() if k not in ('links', 'mode')} == {
                    k: v for k, v in results[1].items() if k not in ('links', 'mode')}
        incompatible = deepcopy(actor.checkpoint_state())
        incompatible['mini_guidance']['version'] = 'capability_guidance_v5'
        with pytest.raises(Exception, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(incompatible)
    finally:
        actor.close()
