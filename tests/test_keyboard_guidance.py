"""Generic synthetic cases only: no benchmark prompts, assets, or solutions."""
from copy import deepcopy
import itertools
import json

import pytest

from kobe_views import keyboard_guidance as guidance, mini_graph
from kobe_views.keyboard_selection import task_keyboard_policy, validate_task_keyboard
from kobe_views.task_keyboard import environment
from test_keyboard_view import annotated
from test_mini_taskviews import TASK, make_actor, packet, predict


def event(keys, *, step=1, seq=4, **changes):
    row = {'kind': 'transition', 'instruction': 'Copy files', 'step': step,
           'dispatch_observed': True, 'command_alignment': 'matched', 'gaps': [],
           'controller_receipts': [{'result': {'success': True, 'error': ''}}],
           'tool': {'arguments': {'action': 'key', 'keys': keys}}, **changes}
    return seq, row, '1' * 64


def route(**kwargs):
    return guidance.route(**{'instruction': 'Copy files', 'enabled': ['general', 'type.file_manager'],
                             'rows': [], 'proposals': [], 'step': 2, 'observation_ref': 5, **kwargs})


def names(value):
    return [c['record']['guide_id'].split(':')[0] for c in value['groups']]


@pytest.mark.parametrize('instruction,need', [
    ('Move some files to another folder.', 'file_operations'),
    ('Take a screenshot of the window.', 'capture'), ('Export the document.', 'export'),
    ('将文件复制到另一个目录。', 'file_operations'), ('截屏并导出图像。', 'capture'),
])
def test_public_capabilities_freeze_helper_directory_without_naming_software(instruction, need):
    task = {'instruction': instruction, 'related_apps': ['GIMP']}
    plan = task_keyboard_policy(task, mode='task_capabilities')
    assert {'general', 'app.gimp', 'type.file_manager'} <= set(plan['mini_guidance']['enabled_toolsets'])
    assert need in plan['mini_guidance']['capabilities']
    assert plan['mini_guidance']['focus_confirmation'] == 'required_not_inferred'
    validate_task_keyboard(plan, {**task, 'config': 'Copy gold', 'evaluator': {'answer': 'SECRET'}})
    with pytest.raises(ValueError):
        validate_task_keyboard(plan, {'instruction': instruction + ' changed'})


def test_old_mode_and_missing_field_remain_old_and_baseline_clears_extension():
    old = task_keyboard_policy({'instruction': 'Copy files'})
    assert 'mini_guidance' not in old
    assert old['mini_keyboard_tools']['enabled_toolsets'] == ['general']
    plan = task_keyboard_policy({'instruction': 'Copy files'}, mode='task_capabilities')
    assert json.loads(environment(plan, arm='taskviews')[guidance.ENV]) == plan['mini_guidance']
    assert environment(plan, arm='baseline')[guidance.ENV] == ''
    assert environment(old, arm='taskviews')[guidance.ENV] == ''
    plan['mini_guidance']['pending_decision_ttl'] = 999
    with pytest.raises(ValueError):
        guidance.validate(plan['mini_guidance'], ['type.file_manager'])


def test_copy_and_cut_are_alternatives_but_move_dependency_group_contains_paste():
    copy = route()
    move = route(instruction='Move files')
    generic = route(instruction='Transfer files')
    assert names(copy) == ['files.copy']
    assert names(move) == ['files.move']
    assert names(generic) == ['files.transfer']
    assert [r['tool']['keys'] for r in move['groups'][0]['record']['recipes']] == [['ctrl', 'x'], ['ctrl', 'v']]
    assert generic['groups'][0]['record']['alternatives'] == [['copy', 'cut']]
    text = route(instruction='Copy and paste the selected text', enabled=['general'])
    assert names(text) == ['clipboard.copy_paste']
    assert [r['tool']['keys'] for r in text['groups'][0]['record']['recipes']] == [['ctrl', 'c'], ['ctrl', 'v']]


@pytest.mark.parametrize('keys', [['ctrl', 'c'], ['ctrl', 'x'], 'ctrl+c', 'ctrl+x'])
def test_dispatch_advances_to_paste_with_empty_intent_and_never_claims_success(keys):
    value = route(rows=[event(keys)])
    assert names(value)[0] == 'clipboard.paste'
    state = value['workflow']
    assert state == {'phase': 'pending_paste', 'ref': 4, 'started_step': 1,
                     'expires_step': 7, 'effect_status': 'unknown'}
    assert {'ref': 4} in value['groups'][0]['record']['evidence']
    assert value == route(rows=[event(keys)])  # Rebuild, not mutable carried state.


def test_paste_moves_to_inspection_and_suppresses_stale_copy_and_paste_proposals():
    value = route(rows=[event(['ctrl', 'c']), event(['ctrl', 'v'], seq=8, step=2)], step=3,
                  proposals=[(7, 'copy then paste', 2)])
    assert names(value) == ['clipboard.verify']
    assert value['groups'][0]['record']['recipes'] == []
    assert value['workflow']['effect_status'] == 'unknown'


@pytest.mark.parametrize('changes', [
    {'dispatch_observed': False}, {'kind': 'decision'}, {'gaps': ['missing_target']},
    {'error': 'failed'}, {'command_alignment': 'unknown'}, {'controller_receipts': []},
    {'controller_receipts': [{'result': {'success': False}}]},
    {'controller_receipts': [{'result': {'returncode': 1}}]},
    {'tool': {'arguments': {'action': 'key_down', 'keys': ['ctrl', 'c']}}},
    {'tool': {'arguments': {'action': 'key_up', 'keys': ['ctrl', 'c']}}},
    {'tool': {'arguments': {'action': 'key', 'keys': ['ctrl', 'c'], 'extra': True}}},
    {'tool': {'arguments': {'action': 'key', 'keys': ['ctrl', 'ctrl', 'c']}}},
])
def test_only_complete_confirmed_actions_advance_phase(changes):
    assert route(rows=[event(['ctrl', 'c'], **changes)])['workflow'] is None


def test_expiry_task_boundary_dismiss_and_failed_intervening_key_invalidate():
    copy = event(['ctrl', 'c'])
    assert route(rows=[copy], step=8)['invalidations'] == [{'ref': 4, 'reason': 'expired'}]
    boundary = (6, {'kind': 'task_input', 'instruction': 'Different task'}, '2' * 64)
    assert route(rows=[copy, boundary])['workflow'] is None
    for ending in [event(['escape'], seq=7), event(['ctrl', 'c'], seq=7, error='failure')]:
        assert route(rows=[copy, ending])['workflow'] is None
    # Later successful writes replace the previous source; repeated operations remain distinct.
    assert route(rows=[copy, event(['ctrl', 'x'], seq=9)])['workflow']['ref'] == 9


def test_mixed_scoped_intent_does_not_veto_other_operations_and_unknown_has_safe_fallback():
    value = route(instruction='Rename the file, then paste.', proposals=[(3, 'Rename the file, then paste.', 1)])
    assert names(value) == ['files.rename']  # The later stage is frozen, not selected now.
    no_match = route(instruction='Inspect the visible application', enabled=['general'])
    assert names(no_match) == ['focus.verify']
    assert not no_match['groups'][0]['record']['recipes']
    assert names(route(instruction='Take a snapshot in VLC', enabled=['general', 'app.vlc']))[0] == 'vlc.capture'
    assert names(route(instruction='Export in GIMP', enabled=['general', 'app.gimp']))[0] == 'gimp.export'


def test_order_invariant_routing_and_stable_content_identity():
    expected = route(proposals=[(3, 'copy cut paste rename', 1)])
    library = deepcopy(guidance.LIBRARY)
    for _ in range(2):
        for key in ('guides', 'bindings', 'sources'):
            library[key] = dict(reversed(list(library[key].items())))
        assert route(library=library, proposals=[(3, 'copy cut paste rename', 1)]) == expected
    changed = deepcopy(library)
    changed['guides']['files.copy']['scope'] += ' changed'
    assert guidance.guide('files.copy', [], library=changed)['guide_id'] != guidance.guide('files.copy', [])['guide_id']


def test_supplemental_lookup_retains_old_topics_but_cannot_enable_software():
    value = route(proposals=[(3, '<key_lookup>app.gimp.zoom</key_lookup>', 1)], enabled=['general', 'app.gimp'])
    assert names(value) == ['focus.verify']  # A directory tag cannot establish action or focus.
    value = route(instruction='Zoom out in GIMP', proposals=[(3, 'Zoom out in GIMP <key_lookup>app.gimp.zoom</key_lookup>', 1)],
                  enabled=['general', 'app.gimp'])
    assert names(value)[0] == 'catalog.app.gimp.zoom'
    disabled = route(proposals=[(3, '<key_lookup>app.gimp.zoom</key_lookup>', 1)])
    assert 'catalog.app.gimp.zoom' not in names(disabled)
    empty_latest = route(proposals=[(7, None, 2), (3, '<key_lookup>app.gimp.zoom</key_lookup>', 1)],
                         enabled=['general', 'app.gimp'], step=3)
    assert 'catalog.app.gimp.zoom' not in names(empty_latest)


@pytest.mark.parametrize('text,enabled,intent', [
    ('Zoom out in GIMP', ['general', 'app.gimp'], 'zoom out'),
    ('Pause playback in VLC', ['general', 'app.vlc'], 'toggle playback'),
    ('Seek forward in VLC', ['general', 'app.vlc'], 'short seek forward'),
])
def test_specific_action_in_scoped_catalog_is_automatically_retrieved_without_tag(text, enabled, intent):
    value = route(instruction=text, proposals=[(3, text, 1)], enabled=enabled)
    recipes = value['groups'][0]['record']['recipes']
    assert [r['intent'] for r in recipes] == [intent]
    assert value['groups'][0]['record']['applicability'] == 'conditional_verify_app_and_focus'


def test_explicit_negative_operations_and_confirm_dependencies():
    assert 'copy' not in guidance.operations('Do not copy; move files instead.')
    assert guidance.operations('不要复制，而是移动文件。') == {'move'}
    assert names(route(proposals=[(3, 'replace text and confirm', 1)]))[0] == 'text.replace_confirm'
    value = route(rows=[event(['ctrl', 'c'])], proposals=[(3, 'Type the destination path', 1)])
    assert names(value)[0] == 'text.edit' and 'clipboard.paste' in names(value)


def test_existing_observations_support_literal_repetition_but_not_semantic_success():
    rows = []
    for seq in (2, 3, 6):
        rows.append((seq, {'kind': 'observation', 'id': str(seq),
                          'images': {'original': {'sha256': '0' * 64}}}, '0' * 64))
    for seq, source, target in ((4, '2', '3'), (7, '3', '6')):
        rows.append(event([], seq=seq, source=source, target=target,
                          tool={'arguments': {'action': 'left_click', 'coordinate': [10, 10]}}))
    value = route(rows=rows, step=3)
    assert names(value)[0] == 'focus.verify'
    assert value['observed_deltas'] == [
        {'ref': 7, 'before': 3, 'after': 6, 'pixels': 'same', 'effect_status': 'unknown'},
        {'ref': 4, 'before': 2, 'after': 3, 'pixels': 'same', 'effect_status': 'unknown'}]


def test_delivery_metrics_distinguish_prepared_delivered_needed_workflow_and_unknown_applicability():
    selection = route()
    records = [selection['groups'][0]['record']]
    prepared = guidance.delivery_audit(selection, records, True)
    assert not prepared['packet_delivered'] and prepared['needed_recipes_delivered'] == 0
    sent = guidance.delivery_audit(selection, records, True, True)
    assert sent['needed_recipe_count'] == sent['needed_recipes_delivered'] == 2
    assert sent['complete_workflow_groups'] == 1
    assert sent['semantic_inapplicability_rate'] is None and sent['applicability_unknown_groups'] == 1
    wrong = deepcopy(records)
    wrong[0]['recipes'].pop()
    broken = guidance.delivery_audit(selection, wrong, True, True)
    assert broken['complete_workflow_groups'] == 0 and broken['known_stale_or_inapplicable_groups'] == 1
    absent = guidance.delivery_audit(selection, [], True, True)
    assert absent['directory_visible'] and absent['needed_recipes_delivered'] == 0


def test_audit_aggregates_real_receipts_and_does_not_count_preparation_as_delivery(tmp_path):
    from scripts.audit_mini_guidance import summarize
    selection = route()
    records = [selection['groups'][0]['record']]
    ready = guidance.delivery_audit(selection, records, True)
    sent = guidance.delivery_audit(selection, records, True, True)
    lines = [{'episode_id': 'a', 'frame_id': frame, 'event': 'mini_guidance_prepared', 'metrics': ready, 'selection': selection}
             for frame in ('f1', 'f2')]
    lines += [{'episode_id': 'a', 'frame_id': 'f1', 'event': 'mini_guidance_delivery', 'metrics': sent}] * 2
    path = tmp_path / 'events.jsonl'
    path.write_text('\n'.join(json.dumps(row) for row in lines), encoding='utf-8')
    result = summarize([path])
    assert result['packet_delivery_rate'] == result['directory_visibility_rate'] == 0.5
    assert result['needed_recipe_delivery_rate'] == result['workflow_completeness_rate'] == 0.5
    assert result['request_receipts_including_retries'] == 2 and result['frames'] == 2
    assert result['semantic_inapplicability_rate'] is None and result['adoption'] == 'unknown'
    labels = [{'episode_id': 'a', 'frame_id': 'f1',
               'needed_recipe_ids': [r['id'] for r in records[0]['recipes']],
               'needed_workflow_group_ids': [records[0]['guide_id']],
               'stale_or_inapplicable_delivered_group_ids': [], 'applicability_review_complete': True}]
    measured = summarize([path], labels)['independent_annotations']
    assert measured['coverage_rate'] == 0.5 and measured['needed_recipe_delivery_rate'] == 1
    labels[0]['stale_or_inapplicable_delivered_group_ids'] = ['unknown']
    with pytest.raises(ValueError):
        summarize([path], labels)


def test_guidance_plan_manifest_and_validation_are_bound_to_actual_configuration(monkeypatch):
    from scripts.run_official_native_tasks import configure_profile
    from scripts import osworld_native_experiment
    from ui_kobe.osworld.taskviews_profiles import validate_profile
    from test_mini_profiles import mini_plan

    task = {'instruction': TASK}
    plan = {**mini_plan(), 'official': task, **task_keyboard_policy(task, mode='task_capabilities')}
    manifest = {key: plan[key] for key in ('taskviews_profile', 'mini_profile', 'source_branch',
                                         'mini_keyboard_tools', 'mini_keyboard_selection', 'mini_guidance')}
    monkeypatch.setattr(osworld_native_experiment, 'require_mini_branch', lambda: None)
    validate_profile(plan)
    configure_profile(plan, manifest)
    with pytest.raises(RuntimeError, match='Manifest fixed-view'):
        configure_profile(plan, {**manifest, 'mini_guidance': None})
    changed = deepcopy(plan)
    changed['mini_guidance']['library_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        validate_profile(changed)


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
def test_real_actor_dispatch_receipts_and_restore_without_extra_calls(monkeypatch, tmp_path, mode):
    import test_mini_taskviews
    monkeypatch.setattr(test_mini_taskviews, 'TASK', 'Copy selected text')
    plan = task_keyboard_policy({'instruction': test_mini_taskviews.TASK}, mode='task_capabilities')
    monkeypatch.setenv(guidance.ENV, json.dumps(plan['mini_guidance']))
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_PACKING', mini_graph.policy(mode,
        mini_graph.DELIVERY_PACKING if mode != 'legacy' else None)['packing'])
    actions = [{'action': 'key', 'keys': ['ctrl', 'c']}, {'action': 'key', 'keys': ['ctrl', 'v']}, {'action': 'screenshot'}]
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=actions)
    annotated(transport, lambda: '')
    try:
        for expected in ('clipboard.copy', 'clipboard.paste', 'clipboard.verify'):
            predict(actor, obs)
            wire = packet(transport)
            display = wire if mode == 'legacy' else mini_graph.expand(wire)
            records = display['views']['keyboard']['records']
            assert records and records[0]['guide_id'].startswith(expected + ':')
            assert all(set(source) == {'kind'} for source in display['sources'].values())
            assert 'https://' not in json.dumps(records)
            assert all('source_ref' in r and 'source' not in r for r in records)
            assert all(r['source_ref'] in actor.mini_context.guidance_selection['guide_sources'] for r in records)
            assert len(actor.mini_context.cached.encode()) <= 3000
            assert actor.mini_context.trace['guidance']['packet_delivered']
            snapshot = actor.checkpoint_state()
            actor.restore_checkpoint_state(snapshot)
        assert len(transport.requests) == 3
        assert actor.mini_context.trace['guidance']['needed_groups_delivered'] == 1
        snapshot['mini_guidance']['pending_decision_ttl'] += 1
        with pytest.raises(Exception, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(snapshot)
    finally:
        actor.close()


def test_packet_budgets_atomic_groups_and_same_input_flat_linked(monkeypatch, tmp_path):
    from kobe_views.guidance_delivery import materialize
    from mini_graph_support import actor_fixture, projection_snapshot
    from kobe_views.model import dumps

    with actor_fixture(monkeypatch, tmp_path) as (actor, obs, transport, predict_once):
        predict_once(actor, obs)
        index, args = projection_snapshot(actor)
        current_ref = args['current']['ref']
        selection = route(instruction='Move files', observation_ref=current_ref)
        for budget, mode in itertools.product((0, 1, 1500, 2500, 3000, 99999), ('legacy', 'flat', 'linked')):
            value = materialize(episode_id=index.episode_id, index=index, instruction=TASK,
                graph_mode=mode, packing=mini_graph.DELIVERY_PACKING, selection=selection,
                **{**args, 'max_bytes': budget})
            if value:
                assert len(dumps(value).encode()) <= min(3000, budget)
                display = value if mode == 'legacy' else mini_graph.expand(value)
                records = display['views']['keyboard']['records']
                assert not records or records == [guidance.model_card(selection['groups'][0]['record'])]
        linked, flat = [materialize(episode_id=index.episode_id, index=index, instruction=TASK,
            graph_mode=mode, packing=mini_graph.DELIVERY_PACKING, selection=selection, **args)
            for mode in ('linked', 'flat')]
        assert linked is not None and flat is not None
        assert {k: v for k, v in linked.items() if k not in ('links', 'mode')} == {
            k: v for k, v in flat.items() if k not in ('links', 'mode')}
        oversized = deepcopy(selection)
        oversized['groups'][0]['record']['steps'] = '通用流程说明' * 1000
        value = materialize(episode_id=index.episode_id, index=index, instruction=TASK, graph_mode='flat',
            packing=mini_graph.DELIVERY_PACKING, selection=oversized, **args)
        assert len(dumps(value).encode()) <= 3000
        assert value['views']['keyboard']['omitted_records'] == 1
        assert mini_graph.expand(value)['views']['keyboard']['records'] == []
        display = mini_graph.expand(value)
        assert display['views']['current']['records'][0]['guidance_status']['card'] == 'omitted_budget'
