"""Optional references under no-match, real wire assembly and phase boundaries.

Only synthetic generic tasks; no benchmark assets, answers, API or GUI calls.
"""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance, mini_graph
from kobe_views.guidance_eligibility import GUIDE_OPS
from kobe_views.guidance_delivery import materialize
from kobe_views.keyboard_selection import task_keyboard_policy
from kobe_views.model import dumps
from test_keyboard_guidance import names, route


@pytest.mark.parametrize('proposals', [[], [(3, '', 1)], [(3, None, 1)],
    [(3, 'Use the visible alignment handles.', 1)], [(3, '<key_lookup>focus.verify</key_lookup>', 1)]])
def test_task_specific_or_missing_intent_has_no_substitute_reference(proposals):
    selection = route(instruction='Align the panels to the requested layout.', proposals=proposals)
    assert selection['groups'] == selection['needed_groups'] == []
    assert selection['selection_status'] == 'empty' and selection['guide_sources'] == {}
    assert 'focus.verify' not in guidance.LIBRARY['guides'] and 'focus.verify' not in GUIDE_OPS
    metrics = guidance.delivery_audit(selection, [], False, delivered=True)
    assert metrics['packet_delivered'] and metrics['selection_status'] == 'empty'
    assert metrics['needed_group_count'] == metrics['needed_groups_delivered'] == metrics['matching_group_count'] == 0
    assert metrics['needed_recipe_delivery_rate'] is metrics['workflow_completeness_rate'] is None
    assert metrics['adoption'] == 'unknown_parameter_match_is_not_use'


def test_empty_prose_does_not_revive_old_intention_or_disable_execution_phase():
    value = route(instruction='Read the content', step=3, proposals=[(6, '', 2), (3, 'Zoom in', 1)])
    assert names(value) == []
    assert any(x['reason'] == 'superseded_public_intention' for x in value['excluded'])
    for phase, card in [('confirm_once', 'view.zoom_confirm'), ('inspect_effect', None)]:
        value = route(instruction='Read the content', proposals=[(3, '', 1)],
                      pending_effect={'phase': phase, 'refs': [2, 3]})
        assert names(value) == ([card] if card else [])


def configure(monkeypatch, task, mode):
    policy = task_keyboard_policy({'instruction': task}, mode='task_capabilities')['mini_guidance']
    monkeypatch.setenv(guidance.ENV, json.dumps(policy))
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_PACKING', mini_graph.policy(mode,
        mini_graph.DELIVERY_PACKING if mode != 'legacy' else None)['packing'])
    return policy


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
@pytest.mark.parametrize('public_text', ['', 'Use the visible alignment handles.'])
def test_native_actions_and_success_do_not_require_a_keyboard_match(monkeypatch, tmp_path, mode, public_text):
    import test_mini_taskviews as native
    from test_mini_artifact_protocol import annotate
    from kobe_views.artifact_view import tagged_review
    monkeypatch.setattr(native, 'TASK', 'Align the panels to the requested layout.')
    policy = configure(monkeypatch, native.TASK, mode)
    actor, obs, transport = native.make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'left_click', 'coordinate': [20, 30]},
        {'action': 'left_click_drag', 'coordinate': [60, 70]},
        {'action': 'terminate', 'status': 'success'}])
    annotate(transport, lambda request, n: public_text if n < 3 else tagged_review(
        {'no_artifact': 'This synthetic layout task creates no file.'}))
    try:
        for n in range(3):
            commands = native.predict(actor, obs)
            wire = native.packet(transport)
            display = wire if mode == 'legacy' else mini_graph.expand(wire)
            assert len(dumps(wire).encode()) <= 3000
            assert display['views']['keyboard'] == {'records': [], 'omitted_records': 0}
            current = display['views']['current']['records'][0]
            assert 'guidance_status' not in current
            assert 'keyboard_lookup' not in current
            assert 'focus.verify' not in dumps(transport.requests[-1])
            assert actor.mini_context.trace['delivered']
            assert actor.mini_context.trace['guidance']['needed_groups_delivered'] == 0
            assert len(transport.requests) == actor.total_steps == n + 1
            assert actor.last_trace['mini_recovery']['report_rejections'] == 0
        assert commands == ['DONE']
        assert 'Keyboard is optional' in actor.context_label
        snapshot = actor.checkpoint_state()
        actor.restore_checkpoint_state(snapshot)
        snapshot['mini_guidance']['version'] = 'capability_guidance_v7'
        with pytest.raises(Exception, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(snapshot)
        assert policy['usage'] == 'optional_reference_not_action_requirement'
    finally:
        actor.close()


def test_matching_reference_does_not_constrain_the_native_action_to_its_binding(monkeypatch, tmp_path):
    import test_mini_taskviews as native
    from test_mini_artifact_protocol import annotate
    monkeypatch.setattr(native, 'TASK', 'Copy selected text')
    configure(monkeypatch, native.TASK, 'legacy')
    actor, obs, transport = native.make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'right_click', 'coordinate': [20, 30]}])
    annotate(transport, lambda request, n: 'Use the visible context menu for Copy.')
    try:
        commands = native.predict(actor, obs)
        records = native.packet(transport)['views']['keyboard']['records']
        assert records[0]['recipes'][0]['tool']['keys'] == ['ctrl', 'c']
        assert 'rightClick' in commands[0] and len(transport.requests) == 1
    finally:
        actor.close()


def test_lookup_in_public_response_is_consumed_next_request_not_during_thinking(monkeypatch, tmp_path):
    import test_mini_taskviews as native
    from test_mini_artifact_protocol import annotate
    monkeypatch.setattr(native, 'TASK', 'Copy selected text')
    configure(monkeypatch, native.TASK, 'legacy')
    actor, obs, transport = native.make_actor(monkeypatch, tmp_path, actions=[
        {'action': 'screenshot'}, {'action': 'right_click', 'coordinate': [20, 30]}])
    annotate(transport, lambda request, n: 'Copy selected text. <key_lookup>clipboard.copy_paste</key_lookup>' if n == 1 else '')
    try:
        native.predict(actor, obs)
        assert native.packet(transport)['views']['keyboard']['records'][0]['guide_id'].startswith('clipboard.copy:')
        native.predict(actor, obs)
        assert native.packet(transport)['views']['keyboard']['records'][0]['guide_id'].startswith('clipboard.copy_paste:')
        assert len(transport.requests) == actor.total_steps == 2
    finally:
        actor.close()


def test_empty_keyboard_budget_and_flat_linked_same_input(monkeypatch, tmp_path):
    from mini_graph_support import actor_fixture, projection_snapshot
    from test_mini_taskviews import TASK
    with actor_fixture(monkeypatch, tmp_path) as (actor, obs, _, predict):
        predict(actor, obs)
        index, args = projection_snapshot(actor)
        selection = route(instruction='Align the panels.', observation_ref=args['current']['ref'])
        policy = task_keyboard_policy({'instruction': TASK}, mode='task_capabilities')['mini_guidance']
        from kobe_views.review_presentation import schema
        # Match the caller's stage display; the old fixture predates this policy.
        args['current']['artifact']['review_schema'] = schema(policy)
        for budget in (0, 1, 950, 1600, 2300, 3000, 8000):
            modes = {}
            for mode in ('legacy', 'flat', 'linked'):
                value = materialize(episode_id=index.episode_id, index=index, instruction=TASK,
                    graph_mode=mode, packing=mini_graph.DELIVERY_PACKING, selection=selection,
                    review_policy=policy, **{**deepcopy(args), 'max_bytes': budget})
                modes[mode] = value
                if value:
                    assert len(dumps(value).encode()) <= min(3000, budget)
                    display = value if mode == 'legacy' else mini_graph.expand(value)
                    assert display['views']['keyboard'] == {'records': [], 'omitted_records': 0}
                    assert 'guidance_status' not in display['views']['current']['records'][0]
            assert (modes['flat'] is None) == (modes['linked'] is None)
            if modes['flat']:
                assert {k: v for k, v in modes['flat'].items() if k not in ('links', 'mode')} == {
                    k: v for k, v in modes['linked'].items() if k not in ('links', 'mode')}


def test_audit_does_not_count_an_empty_keyboard_as_successful_reference_delivery(tmp_path):
    from scripts.audit_mini_guidance import summarize
    selection = route(instruction='Align the panels.')
    receipt = guidance.delivery_audit(selection, [], False, delivered=True)
    prepared = guidance.delivery_audit(selection, [], False)
    events = tmp_path/'events.jsonl'
    events.write_text('\n'.join(json.dumps(e) for e in [
        {'event': 'mini_guidance_prepared', 'episode_id': 'synthetic', 'frame_id': 'f1', 'selection': selection, 'metrics': prepared},
        {'event': 'mini_guidance_delivery', 'episode_id': 'synthetic', 'frame_id': 'f1', 'metrics': receipt}]), encoding='utf-8')
    result = summarize([events])
    assert result['packet_delivery_rate'] == result['empty_keyboard_frame_rate'] == 1
    assert result['delivered_reference_frame_rate'] == 0
    assert result['needed_group_delivery_rate'] is result['needed_recipe_delivery_rate'] is None
