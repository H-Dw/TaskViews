"""Generic UI scenarios and independent presentation ablations, no task answers."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance, mini_graph
from kobe_views.artifact_view import REVIEW_SCHEMA, prompt_schema
from kobe_views.guidance_delivery import materialize
from kobe_views.keyboard_selection import task_keyboard_policy, validate_task_keyboard
from kobe_views.model import dumps
from kobe_views.operation_support import build, pending_effect, reading_notes, short_cycle
from kobe_views.review_presentation import schema
from test_operation_support import action, decision, obs
from test_keyboard_guidance import route

CONDITIONS = [('stage', 'full', 'fixed_reference'),
              ('stage', 'compact', 'fixed_reference'), ('stage', 'compact', 'refill')]


def zoom_rows():
    return [obs(1), decision(2, 'The table shows 42.75.', 1, id='read'),
            decision(3, 'I will set the zoom to 150%.', 1, id='zoom'),
            action(4, {'action': 'type', 'text': '150%'}, decision_id='zoom'),
            action(5, {'action': 'triple_click', 'coordinate': [20, 30]})]


def test_zoom_reading_survives_clicks_and_confirm_but_not_content_edits():
    rows = zoom_rows()
    assert reading_notes(rows, 'Copy files', 6)[0][0]['text'] == 'The table shows 42.75.'
    state, _ = pending_effect(rows, 'Copy files', 6)
    assert state['phase'] == 'confirm_once' and state['ref'] == 4 and state['effect'] == 'unknown'
    rows.append(action(6, {'action': 'key', 'keys': ['enter']}))
    value = build(rows=rows, instruction='Copy files', proposals=[], step=7, observation_ref=100)
    assert value['pending_effect']['phase'] == 'inspect_effect'
    assert 'Enter was dispatched' in value['feedback'][0]['constraint']
    assert value['reading_progress']
    rows.append(action(7, {'action': 'type', 'text': 'replace text'}))
    assert not reading_notes(rows, 'Copy files', 8)[0]
    assert pending_effect(rows, 'Copy files', 8)[0] is None


@pytest.mark.parametrize('change', [{'decision_id': 'missing'}, {'dispatch_observed': False},
                                  {'controller_receipts': [{'result': {'success': False}}]}])
def test_zoom_requires_issuing_decision_and_real_dispatch(change):
    rows = zoom_rows()
    rows[3][1].update(change)
    assert pending_effect(rows, 'Copy files', 6)[0] is None
    if 'decision_id' not in change:
        assert reading_notes(rows, 'Copy files', 6)[0]  # Failed input cannot erase a claim.


def test_pending_expiry_scope_change_and_public_report_remain_unverified():
    rows = zoom_rows()
    assert pending_effect(rows, 'Copy files', 11)[0] is None
    assert pending_effect(rows + [action(6, {'action': 'key', 'keys': ['alt', 'tab']})], 'Copy files', 7)[0] is None
    rows += [obs(6), decision(7, 'Zoom now shows 150%.', 6)]
    state, audit = pending_effect(rows, 'Copy files', 8)
    assert state is None and audit[-1]['reason'] == 'public_zoom_report_not_certification'
    negative = zoom_rows() + [obs(6), decision(7, 'Zoom now shows 150%, but it is not applied.', 6)]
    assert pending_effect(negative, 'Copy files', 8)[0] is not None
    boundary = (6, {'kind': 'task_input', 'instruction': 'Another task'}, '1' * 64)
    value = build(rows=zoom_rows() + [boundary], instruction='Copy files', proposals=[], step=7, observation_ref=9)
    assert value['pending_effect'] is None and not value['reading_progress']


def test_triple_click_coverage_and_specific_card_not_generic_focus():
    rows = [action(n, {'action': 'triple_click', 'coordinate': [20, 30]}) for n in (1, 2)]
    assert short_cycle(list(reversed(rows)))['period'] == 1
    pending, _ = pending_effect(zoom_rows(), 'Copy files', 6)
    selection = route(instruction='Read a document', pending_effect=pending)
    card = selection['groups'][0]['record']
    assert card['guide_id'].startswith('view.zoom_confirm:')
    assert [r['tool']['keys'] for r in card['recipes']] == [['return']]
    pending['phase'] = 'inspect_effect'
    card = route(instruction='Read a document', pending_effect=pending)['groups'][0]['record']
    assert card['guide_id'].startswith('view.zoom_check:') and not card['recipes']


@pytest.mark.parametrize('timing,wording,budget', CONDITIONS)
def test_frozen_presentation_and_terminal_format(timing, wording, budget):
    task = {'instruction': 'Read a document'}
    plan = task_keyboard_policy(task, mode='task_capabilities', review_timing=timing,
                                review_prompt=wording, review_budget=budget, decision_limit=40)
    validate_task_keyboard({**plan, 'max_steps': 40}, task)
    policy = plan['mini_guidance']
    assert schema(policy, finishing=True) == prompt_schema(wording)
    if timing == 'stage':
        assert len(schema(policy)) < 150
    if budget == 'fixed_reference':
        assert schema(policy, cost=True) == REVIEW_SCHEMA
    altered = deepcopy(plan)
    altered['mini_guidance']['review_timing'] = 'typo'
    with pytest.raises(ValueError):
        validate_task_keyboard(altered, task)


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
def test_same_input_no_refill_selects_identical_facts_and_refill_is_bounded(monkeypatch, tmp_path, mode):
    from mini_graph_support import actor_fixture, projection_snapshot
    from test_mini_taskviews import TASK
    with actor_fixture(monkeypatch, tmp_path) as (actor, observation, _, predict):
        predict(actor, observation)
        index, args = projection_snapshot(actor)
        selection = route(observation_ref=args['current']['ref'])
        facts, sizes = [], []
        for timing, wording, budget in CONDITIONS:
            policy = guidance.policy({'instruction': TASK}, ['general'], review_timing=timing,
                                     review_prompt=wording, review_budget=budget)
            args['current']['artifact']['review_schema'] = schema(policy)
            packet = materialize(episode_id=index.episode_id, index=index, instruction=TASK,
                graph_mode=mode, packing=mini_graph.DELIVERY_PACKING, selection=selection,
                review_policy=policy, **args)
            assert packet and len(dumps(packet).encode()) <= 3000
            sizes.append(len(dumps(packet).encode()))
            display = packet if mode == 'legacy' else mini_graph.expand(packet)
            assert 'https://' not in dumps(display)
            display['views']['current']['records'][0]['artifact']['review_schema'] = 'EXCLUDED_PRESENTATION'
            facts.append(display)
        assert facts[0] == facts[1]
        assert sizes[1] < sizes[0]
        # Refill may admit more but never less current card / key evidence.
        for view in ('keyboard', 'attempts'):
            assert all(row in facts[2]['views'][view]['records'] for row in facts[1]['views'][view]['records'])


@pytest.mark.parametrize('timing,wording,budget', CONDITIONS)
def test_actual_request_terminal_gate_and_cross_policy_restore(monkeypatch, tmp_path, timing, wording, budget):
    from test_mini_taskviews import TASK, make_actor, packet, predict
    from test_mini_artifact_protocol import annotate, report
    from kobe_views.artifact_view import tagged_review
    policy = task_keyboard_policy({'instruction': TASK}, mode='task_capabilities', review_timing=timing,
                                  review_prompt=wording, review_budget=budget, decision_limit=40)['mini_guidance']
    monkeypatch.setenv(guidance.ENV, json.dumps(policy))
    actor, observation, transport = make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'left_click', 'coordinate': [40, 50]},
        {'action': 'terminate', 'status': 'success'}, {'action': 'terminate', 'status': 'success'}])
    def content(request, attempt):
        current = packet(transport)['views']['current']['records'][0]
        if attempt == 1:
            assert current['artifact']['review_schema'] == schema(policy)
            return 'Ready to finish; final check.'
        assert current['artifact']['review_schema'] == prompt_schema(wording)
        return 'Complete' if attempt == 2 else tagged_review(report(current['ref']))
    annotate(transport, content)
    try:
        predict(actor, observation)
        state = actor.checkpoint_state()
        actor.restore_checkpoint_state(state)
        state['mini_guidance']['review_budget'] = 'refill' if budget == 'fixed_reference' else 'fixed_reference'
        with pytest.raises(Exception, match='cannot be switched'):
            actor.restore_checkpoint_state(state)
        assert predict(actor, observation) == ['DONE']
        assert len(transport.requests) == 3 and actor.total_steps == 2
        assert actor.last_trace['mini_recovery']['report_rejections'] == 1
    finally:
        actor.close()
