"""Generic source-bound phase scenarios, not benchmark answers or objects."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance, mini_graph
from kobe_views.guidance_semantics import analyze, operations
from kobe_views.operation_support import build, mixed_view_cycle, pending_effect, readability_report, reading_notes
from kobe_views.keyboard_selection import task_keyboard_policy
from kobe_views.review_presentation import schema
from test_keyboard_guidance import names, route
from test_operation_support import action, decision, obs


@pytest.mark.parametrize('text,need,absent', [
    ('Zoom in', {'zoom_in'}, {'zoom_value', 'edit'}),
    ('Adjust the zoom', {'readability'}, {'zoom_value'}),
    ('Type a larger zoom value', {'readability'}, {'zoom_value'}),
    ('Set the zoom to 125%', {'zoom_value'}, {'zoom_in', 'readability'}),
    ('Zoom in to 125%', {'zoom_value'}, {'zoom_in'}),
    ('Enter the exact zoom value', {'zoom_value'}, {'edit'}),
    ('Do not zoom in', set(), {'zoom_in', 'zoom_value'}),
    ('The zoom field is visible', set(), {'zoom_value'}),
    ('Type 125 in the total field', {'edit'}, {'zoom_value'}),
    ('Type a label. The zoom is 125%', {'edit'}, {'zoom_value'}),
    ('The text is cut off; open menu', {'menu_open'}, {'cut', 'open'}),
    ('Read the content', {'reading'}, {'zoom_value'}),
])
def test_action_state_and_precise_ratio_are_distinct(text, need, absent):
    assert need <= operations(text)
    assert not absent & operations(text)


@pytest.mark.parametrize('text,state', [
    ('The text is now readable.', 'readable'), ('The content is not readable.', 'unreadable'),
    ('The page is too small.', 'unreadable'), ('内容现在清晰可读。', 'readable'),
    ('Check whether the text is readable.', None), ('If the content is readable, read it.', None),
    ('The text is not too small.', None),
])
def test_readability_is_a_report_not_an_action(text, state):
    states = [s['kind'] for s in analyze(text)['states'] if s['kind'] in ('readable', 'unreadable')]
    assert states == ([state] if state else [])


def test_report_requires_source_and_fresh_view_and_overrides_arbitrary_zoom_only():
    rows = [obs(1), decision(2, 'The text is readable.', 1)]
    report = readability_report(rows, 'Copy files', 3)
    assert report['verification'] == 'unknown'
    assert readability_report(rows, 'Copy files', 5) is None
    assert readability_report(rows[1:], 'Copy files', 3) is None
    assert readability_report(rows + [action(3, {'action': 'scroll', 'direction': 'down', 'pixels': 40})], 'Copy files', 4) is None
    assert names(route(instruction='Read content', proposals=[(2, 'Zoom in', 2)], step=3, readability=report))[0] == 'document.read'
    precise = route(instruction='Set zoom to 125%', readability=report)
    assert names(precise)[0] == 'view.zoom_value'
    card = precise['groups'][0]['record']
    assert [r['tool']['keys'] for r in card['recipes']] == [['ctrl', 'a'], ['return']]
    assert card['dependencies'] == [['select_text', 'confirm']]


def silent_entry():
    return [obs(1), decision(2, 'Focus the zoom field.', 1, id='focus', step=1),
            action(3, {'action': 'triple_click', 'coordinate': [20, 30]}, decision_id='focus', step=1),
            obs(4), decision(5, '', 4, id='silent', step=2),
            action(6, {'action': 'type', 'text': '125%'}, decision_id='silent', step=2)]


def test_silent_input_uses_bounded_context_and_never_certifies_focus():
    rows = silent_entry()
    state, _ = pending_effect(rows, 'Copy files', 3)
    assert state['phase'] == 'confirm_once' and state['effect'] == 'unknown'
    assert state['basis'] == 'prior_public_zoom_context_focus_unconfirmed'
    assert {1, 2, 3, 5, 6} <= set(state['refs'])
    selection = route(instruction='Read content', proposals=[(2, 'Set zoom to 125%', 2)], step=3,
                      pending_effect=state)
    assert names(selection)[0] == 'view.zoom_confirm'
    assert 'view.zoom_value' not in names(selection)
    rows += [action(7, {'action': 'key', 'keys': ['return']}, step=3), obs(8)]
    state, _ = pending_effect(rows, 'Copy files', 4)
    assert state['phase'] == 'inspect_effect' and state['effect'] == 'unknown'
    assert names(route(instruction='Read content', pending_effect=state))[0] == 'view.zoom_check'
    assert not route(instruction='Read content', pending_effect=state)['groups'][0]['record']['recipes']


@pytest.mark.parametrize('case', ['no_source', 'other_intent', 'scope_changed', 'wrong_task', 'failed_input', 'expired'])
def test_silent_numeric_input_cannot_borrow_unrelated_or_stale_intent(case):
    rows = silent_entry()
    if case == 'no_source':
        rows = rows[1:]
    elif case == 'other_intent':
        rows[4][1]['response'] = json.dumps({'content': 'Type the new data.'})
    elif case == 'scope_changed':
        rows[2][1]['tool']['arguments'] = {'action': 'key', 'keys': ['alt', 'tab']}
    elif case == 'wrong_task':
        rows[1][1]['instruction'] = 'Another task'
    elif case == 'failed_input':
        rows[-1][1]['controller_receipts'][0]['result']['success'] = False
    else:
        rows[-1][1]['step'] = 7
    assert pending_effect(rows, 'Copy files', 8 if case == 'expired' else 3)[0] is None


def test_silent_zoom_entry_retains_a_reading_claim_without_promoting_it():
    rows = silent_entry()
    rows[1][1]['response'] = json.dumps({'content': 'The table shows 12.75. Focus the zoom field.'})
    notes, _ = reading_notes(rows, 'Copy files', 3)
    assert notes[0]['text'] == 'The table shows 12.75.'
    assert notes[0]['verification'] == 'unknown'


def test_mixed_focus_numeric_scroll_loop_keeps_literal_sources_not_success():
    rows = [obs(1)]
    for n, value in [(2, '125%'), (7, '150%')]:
        rows += [decision(n, 'Set zoom to ' + value, 1, id=str(n), step=n),
                 action(n+1, {'action': 'triple_click', 'coordinate': [20, 30]}, step=n),
                 action(n+2, {'action': 'type', 'text': value}, decision_id=str(n), step=n),
                 action(n+3, {'action': 'scroll', 'direction': 'down', 'pixels': 80}, step=n)]
    actions = [r for r in reversed(rows) if r[1]['kind'] == 'transition']
    cycle = mixed_view_cycle(actions, rows)
    assert cycle['progress'] == 'unknown' and cycle['entered_values'] == ['125%', '150%']
    value = build(rows=rows, instruction='Copy files', proposals=[], step=8, observation_ref=1)
    assert value['audit']['mixed_view_cycle'] == cycle
    assert any(c['kind'] == 'mixed_view_cycle' for c in value['feedback'])
    # Repeated ordinary form input/paging is not a zoom cycle.
    changed = deepcopy(rows)
    for _, e, _ in changed:
        if e['kind'] == 'decision':
            e['response'] = json.dumps({'content': 'Type the value in the form.'})
    assert mixed_view_cycle([r for r in reversed(changed) if r[1]['kind'] == 'transition'], changed) is None


def test_executed_save_without_public_intent_triggers_terminal_format_but_not_success():
    rows = [action(1, {'action': 'key', 'keys': ['ctrl', 's']})]
    value = build(rows=rows, instruction='Copy files', proposals=[], step=2, observation_ref=100)
    assert value['finishing'] and value['completion']['status'] == 'unverified'
    assert value['audit']['finishing_action_refs'] == [1]
    rows[0][1]['controller_receipts'][0]['result']['success'] = False
    assert not build(rows=rows, instruction='Copy files', proposals=[], step=2, observation_ref=100)['finishing']


def test_stage_only_new_defaults_and_old_full_round_policy_rejected():
    policy = task_keyboard_policy({'instruction': 'Read content'}, mode='task_capabilities')['mini_guidance']
    assert (policy['review_timing'], policy['review_budget']) == ('stage', 'refill')
    assert len(schema(policy)) < 150 and '<artifact_review>' in schema(policy, finishing=True)
    with pytest.raises(ValueError):
        schema({**policy, 'review_timing': 'always'})
    with pytest.raises(ValueError):
        task_keyboard_policy({'instruction': 'Read content'}, review_timing='always')


@pytest.mark.parametrize('mode', ['legacy', 'flat'])
def test_actual_request_keeps_attempts_and_reading_without_a_matching_card(monkeypatch, tmp_path, mode):
    from test_mini_taskviews import TASK, make_actor, packet, predict
    from test_mini_artifact_protocol import annotate
    from kobe_views.model import dumps
    policy = task_keyboard_policy({'instruction': TASK}, mode='task_capabilities')['mini_guidance']
    monkeypatch.setenv(guidance.ENV, json.dumps(policy))
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    actor, observation, transport = make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'left_click', 'coordinate': [20, 30]}, {'action': 'screenshot'}])
    annotate(transport, lambda request, attempt: 'The table shows 12.75.' if attempt == 1 else '')
    try:
        predict(actor, observation)
        predict(actor, observation)
        wire = packet(transport)
        display = wire if mode == 'legacy' else mini_graph.expand(wire)
        assert len(dumps(wire).encode()) <= 3000
        attempt = display['views']['attempts']['records'][-1]
        assert attempt['tool']['arguments']['action'] == 'left_click'
        assert attempt['effect_status'] == 'unknown'
        assert attempt['intent']['text'] == 'The table shows 12.75.'
        assert str(attempt['intent']['ref']) in display['sources']
        assert display['views']['keyboard']['records'] == []
        assert not any(r.get('grade') == 'model_intent_proposal' for r in display['views']['lessons']['records'])
        current = display['views']['current']['records'][0]
        assert 'keyboard_lookup' not in current or actor.mini_context.guidance_selection['coverage_gaps']
        assert len(current['reading_progress']['reports']) == 1
        report = next(r for r in display['views']['lessons']['records'] if r.get('grade') == 'model_reading_proposal')
        assert current['reading_progress']['reports'][0]['ref'] == report['ref']
        assert report['verification'] == 'unknown'
        assert actor.mini_context.trace['delivered']
    finally:
        actor.close()
