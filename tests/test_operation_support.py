"""Generic journal scenarios, with no benchmark objects, files or solutions."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance, mini_graph
from kobe_views.artifact_view import COMPACT_REVIEW_SCHEMA, REVIEW_SCHEMA, prompt_schema, validate_review, ReviewError
from kobe_views.guidance_semantics import capabilities
from kobe_views.keyboard_selection import task_keyboard_policy, validate_task_keyboard
from kobe_views.operation_support import build, reading_notes, short_cycle
from test_keyboard_guidance import event, route


def action(seq, args, **changes):
    changes.setdefault('step', seq)
    return event([], seq=seq, tool={'arguments': args}, **changes)


def obs(seq):
    return seq, {'kind': 'observation', 'id': str(seq)}, '1' * 64


def decision(seq, text, source, **changes):
    return seq, {'kind': 'decision', 'instruction': 'Copy files', 'step': seq, 'source': str(source),
                 'response': json.dumps({'content': text, 'reasoning_content': 'NEVER READ THIS'}), **changes}, '1' * 64


def support(rows, step=12, **changes):
    return build(rows=rows, instruction='Copy files', proposals=[], step=step, observation_ref=100,
                 decision_limit=40, **changes)


def test_task_freezes_reading_and_image_operations_without_objects_or_answers():
    assert {'reading', 'zoom_in', 'maximize'} <= set(capabilities('Cross-check the figures in these documents.'))
    assert {'image_edit', 'undo', 'export'} <= set(capabilities('Remove the background of a photo.'))
    assert 'image_edit' in capabilities('Make the picture transparent.')
    assert 'image_edit' not in capabilities('Do not remove the background.')
    value = route(instruction='Remove the background of a photo', proposals=[], enabled=['general', 'app.gimp'])
    assert value['groups'] == []  # Image-edit verification does not produce Keyboard knowledge.


def test_zoom_lookup_narrows_alternatives_to_explicit_direction_and_order_is_stable(monkeypatch):
    from kobe_views import keyboard_view
    value = route(instruction='Read a document', enabled=['general', 'app.evince'],
        proposals=[(3, 'Zoom in Evince <key_lookup>app.evince.zoom</key_lookup>', 1)])
    card = value['groups'][0]['record']
    assert [r['intent'] for r in card['recipes']] == ['zoom in']
    original = keyboard_view.active_catalog
    def reordered(*a, **kw):
        result = deepcopy(original(*a, **kw))
        for row in result.values():
            row['recipes'].reverse()
        return dict(reversed(list(result.items())))
    monkeypatch.setattr(keyboard_view, 'active_catalog', reordered)
    assert value == route(instruction='Read a document', enabled=['general', 'app.evince'],
        proposals=[(3, 'Zoom in Evince <key_lookup>app.evince.zoom</key_lookup>', 1)])
    absent = route(instruction='Read a document', enabled=['general', 'app.gimp'],
        proposals=[(3, 'Zoom in <key_lookup>app.gimp.zoom</key_lookup>', 1)])
    assert absent['groups'][0]['record']['guide_id'].startswith('view.zoom_in:')
    assert any(g['reason'] == 'lookup_binding_unavailable' for g in absent['coverage_gaps'])
    move = route(instruction='Move files')['groups'][0]['record']
    assert move['dependencies'] == [['cut', 'paste']]
    assert move['group_kind'] == 'workflow'


def test_drag_duration_change_is_not_a_source_correction_and_receipts_do_not_prove_target():
    rows = [action(1, {'action': 'left_click', 'coordinate': [10, 20]}),
            action(2, {'action': 'left_click_drag', 'coordinate': [90, 80], 'duration': 1}),
            action(3, {'action': 'left_click_drag', 'coordinate': [90, 80], 'duration': 3})]
    value = support(rows, step=4)
    assert value['feedback'][0]['kind'] == 'drag_start'
    assert 'destination' in value['feedback'][0]['constraint'] and 'duration' in value['feedback'][0]['constraint']
    assert value['audit']['cycle']['period'] == 1
    assert not value['audit']['drag']['semantic_source_confirmed']
    assert all(r['effect'] == 'unknown' for r in value['feedback'])
    rows[-1][1]['controller_receipts'] = [{'result': {'success': False}}]
    assert not support(rows, step=4)['feedback']


def test_click_delete_cycle_does_not_depend_on_pixel_equality_or_invent_failure():
    rows = [action(i, {'action': 'left_click', 'coordinate': [20, 30]} if i % 2 else
                   {'action': 'key', 'keys': ['delete']}) for i in range(1, 7)]
    cycle = short_cycle(list(reversed(rows)))
    assert cycle['period'] == 2 and cycle['progress'] == 'unknown'
    assert support(rows, step=7)['feedback'][0]['kind'] == 'command_cycle'
    for row in rows:
        row[1]['tool']['arguments'] = {'action': 'scroll', 'direction': 'down', 'pixels': 200}
    assert short_cycle(list(reversed(rows))) is None
    for row in rows:
        row[1]['tool']['arguments'] = {'action': 'key', 'keys': ['ctrl', 'c']}
    assert short_cycle(list(reversed(rows))) is None


def test_held_key_pairs_and_task_boundaries_do_not_carry_false_state():
    rows = [action(1, {'action': 'key_down', 'keys': ['shift']}),
            action(2, {'action': 'left_click', 'coordinate': [2, 3]})]
    assert support(rows)['feedback'][0]['keys'] == ['shift']
    rows += [action(3, {'action': 'key_up', 'keys': ['shift']})]
    assert not support(rows)['feedback']
    rows = rows[:2] + [(3, {'kind': 'task_input', 'instruction': 'Different'}, '1' * 64)]
    assert not support(rows)['feedback']


def test_reading_claims_are_whole_source_bound_unknown_and_expire_or_invalidate():
    rows = [obs(1), decision(2, 'The table shows 12.50.\nLet me compare another page.', 1)]
    notes, _ = reading_notes(rows, 'Copy files', 3)
    assert notes == [{'grade': 'model_reading_proposal', 'ref': 2, 'before': 1,
                      'text': 'The table shows 12.50.', 'expires_step': 14, 'verification': 'unknown'}]
    assert reading_notes(rows, 'Copy files', 15)[0] == []
    assert reading_notes(rows + [action(4, {'action': 'type', 'text': 'new content'})], 'Copy files', 5)[0] == []
    assert reading_notes(rows + [decision(4, 'Correction: I misread the value.', 1)], 'Copy files', 5)[0] == []
    assert reading_notes([obs(1), decision(2, 'The value is ' + 'long ' * 80, 1)], 'Copy files', 3)[0] == []
    assert reading_notes([obs(1), decision(2, '', 1)], 'Copy files', 3)[0] == []
    assert 'NEVER' not in json.dumps(support(rows))


def test_completion_is_budget_bound_advice_not_automatic_success_or_export():
    value = support([], step=37)
    assert value['completion']['remaining_decisions'] == 4
    assert value['completion']['status'] == 'unverified'
    assert 'only if required' in value['completion']['check']
    assert 'Budget expiry is not success' in value['completion']['check']
    assert 'check' not in support([], step=2)['completion']


@pytest.mark.parametrize('mode', ['legacy', 'flat'])
@pytest.mark.parametrize('review', ['full', 'compact'])
def test_real_request_support_terminal_gate_and_checkpoint(monkeypatch, tmp_path, mode, review):
    from test_mini_taskviews import TASK, make_actor, packet, predict
    from test_mini_artifact_protocol import annotate, report
    from kobe_views.artifact_view import tagged_review

    plan = task_keyboard_policy({'instruction': TASK}, mode='task_capabilities',
                                review_prompt=review, decision_limit=40)
    monkeypatch.setenv(guidance.ENV, json.dumps(plan['mini_guidance']))
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_PACKING', mini_graph.policy(mode,
        mini_graph.DELIVERY_PACKING if mode != 'legacy' else None)['packing'])
    actor, observation, transport = make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'left_click_drag', 'coordinate': [80, 90]},
        {'action': 'terminate', 'status': 'success'}, {'action': 'terminate', 'status': 'success'}])
    def content(request, attempt):
        wire = packet(transport)
        display = wire if mode == 'legacy' else mini_graph.expand(wire)
        current = display['views']['current']['records'][0]
        from kobe_views.review_presentation import schema
        assert current['artifact']['review_schema'] == schema(plan['mini_guidance'])
        assert 'completion' not in current
        if attempt == 1:
            return 'The table shows 12.50.'
        assert any(x['kind'] == 'drag_start' for x in current['action_conditions'])
        return 'Task complete' if attempt == 2 else tagged_review(report(current['ref']))
    annotate(transport, content)
    try:
        predict(actor, observation)
        state = actor.checkpoint_state()
        actor.restore_checkpoint_state(state)
        incompatible = deepcopy(state)
        incompatible['mini_guidance']['review_prompt'] = 'compact' if review == 'full' else 'full'
        with pytest.raises(Exception, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(incompatible)
        assert predict(actor, observation) == ['DONE']
        assert len(transport.requests) == 3 and actor.total_steps == 2
        assert actor.last_trace['mini_recovery']['report_rejections'] == 1
        assert actor.mini_context.trace['delivered']
        assert len(actor.mini_context.cached.encode()) <= 3000
    finally:
        actor.close()


def test_review_mode_and_limit_are_frozen_and_strict_validator_is_identical():
    plans = [task_keyboard_policy({'instruction': 'Copy files'}, mode='task_capabilities',
                                 review_prompt=mode, decision_limit=40) for mode in ('full', 'compact')]
    a, b = [p['mini_guidance'] for p in plans]
    assert {k: v for k, v in a.items() if k != 'review_prompt'} == {k: v for k, v in b.items() if k != 'review_prompt'}
    assert len(COMPACT_REVIEW_SCHEMA) < len(REVIEW_SCHEMA)
    for mode, plan in zip(('full', 'compact'), plans):
        assert prompt_schema(mode)
        validate_task_keyboard({**plan, 'max_steps': 40}, {'instruction': 'Copy files'})
        with pytest.raises(ValueError, match='decision limit'):
            validate_task_keyboard({**plan, 'max_steps': 39}, {'instruction': 'Copy files'})
        with pytest.raises(ReviewError):
            validate_review('<artifact_review>{"candidate":"x"}</artifact_review>', final=True)


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
def test_current_conditions_whole_group_and_review_ablation_share_facts(monkeypatch, tmp_path, mode):
    from kobe_views.guidance_delivery import materialize
    from mini_graph_support import actor_fixture, projection_snapshot
    from test_mini_taskviews import TASK
    from kobe_views.model import dumps
    with actor_fixture(monkeypatch, tmp_path) as (actor, obs_value, transport, predict_once):
        predict_once(actor, obs_value)
        index, args = projection_snapshot(actor)
        current_ref = args['current']['ref']
        args['current']['action_conditions'] = [{'ref': current_ref, 'kind': 'drag_start',
            'constraint': 'Ground source, then drag to destination; duration cannot fix a wrong start.', 'effect': 'unknown'}]
        selection = route(instruction='Move files', observation_ref=current_ref)
        results = []
        for review in ('full', 'compact'):
            args['current']['artifact']['review_schema'] = prompt_schema(review)
            wire = materialize(episode_id=index.episode_id, index=index, instruction=TASK,
                graph_mode=mode, packing=mini_graph.DELIVERY_PACKING, selection=selection, **args)
            assert wire and len(dumps(wire).encode()) <= 3000
            value = wire if mode == 'legacy' else mini_graph.expand(wire)
            current = value['views']['current']['records'][0]
            assert current['action_conditions'][0]['kind'] == 'drag_start'
            records = value['views']['keyboard']['records']
            assert records and [r['tool']['keys'] for r in records[0]['recipes']] == [['ctrl', 'x'], ['ctrl', 'v']]
            current['artifact']['review_schema'] = 'review variant removed for comparison'
            results.append(value)
        assert results[0] == results[1]
