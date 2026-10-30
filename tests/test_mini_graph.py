from copy import deepcopy
import json
from pathlib import Path

import pytest

from kobe_views import mini_graph as graph
from kobe_views.fixed_views import materialize as legacy_materialize
from kobe_views.model import dumps
from mini_graph_support import actor_fixture, legacy_capture, projection_snapshot


def test_legacy_packets_and_actor_requests_match_operation_only_capture(monkeypatch, tmp_path):
    expected = json.loads(Path(__file__).with_name('fixtures').joinpath('mini_graph_legacy_v11.json').read_text())
    assert legacy_capture(monkeypatch, tmp_path) == expected


def test_legacy_fixture_changes_only_checks_and_budget_admitted_key_memory():
    fixtures = Path(__file__).with_name('fixtures')
    before = json.loads((fixtures / 'mini_graph_legacy.json').read_text())
    after = json.loads((fixtures / 'mini_graph_legacy_v11.json').read_text())
    assert before['label'] == after['label']
    assert len(before['packets']) == len(after['packets'])
    for old, new in zip(before['packets'], after['packets']):
        packet = json.loads(old)
        updated = json.loads(new)
        for row, replacement in zip(packet['views']['keyboard']['records'], updated['views']['keyboard']['records']):
            row.pop('check', None)
            # Removing the long generic check leaves room for one existing
            # source-bound key record; it does not fabricate success/history.
            assert replacement['memory'][:len(row['memory'])] == row['memory']
            assert len(row['memory']) + row['memory_omitted'] == len(replacement['memory']) + replacement['memory_omitted']
            for memory in replacement['memory'][len(row['memory']):]:
                assert memory['ref'] == 6 and str(memory['ref']) in updated['sources']
                assert memory['keys'] == ['ctrl', 'a'] and memory['effect_status'] == 'unknown'
            row['memory'], row['memory_omitted'] = replacement['memory'], replacement['memory_omitted']
        assert packet == updated


def snapshot(actor):
    return projection_snapshot(actor)


def packets(actor, index, arguments):
    from test_mini_taskviews import TASK

    common = dict(index=index, instruction=TASK, toolsets=actor.keyboard_toolsets,
                  task_catalog=actor.task_keyboard, **arguments)
    linked = graph.materialize(graph_mode='linked', **common)
    flat = graph.materialize(graph_mode='flat', **common)
    return flat, linked


def test_cross_view_entities_and_strict_ablation(monkeypatch, tmp_path):
    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, transport, predict):
        predict(actor, obs, error='Original controller error')
        predict(actor, obs)
        index, args = snapshot(actor)
        flat, linked = packets(actor, index, args)
        assert linked is not None
        assert {**flat, 'mode': 'linked', 'links': linked['links']} == linked
        assert len(dumps(linked).encode()) <= 3000
        assert len(dumps(flat).encode()) < len(dumps(linked).encode())
        assert all(a in linked['nodes'] and b in linked['nodes'] for a, _, b in linked['links'])
        attempts = linked['views']['attempts']['record_refs']
        errors = [r for r in linked['views']['lessons']['record_refs'] if r[1] == 'execution_error_record']
        assert errors and attempts[0][0] == errors[0][0]
        action = linked['nodes'][errors[0][0]]
        assert action['facets']['execution_error_record']['error'] == 'Original controller error'
        assert action['effect_status'] == 'unknown'
        assert {'before', 'after', 'issued_by', 'in_task', 'reports_on'} <= {r for _, r, _ in linked['links']}
        assert not {'caused_by', 'resolved_by', 'achieves_goal'} & {r for _, r, _ in linked['links']}
        assert len(transport.requests) == 2
        assert actor.mini_context.graph_audit['projection']['delivered']
        expanded = graph.expand(linked)
        assert expanded['views']['current']['records'][0]['artifact']['grade'] == 'unverified'
        assert expanded['views']['attempts']['records'][0]['tool']['arguments'] == {'action': 'key', 'keys': ['ctrl', 'a']}


@pytest.mark.parametrize('budget', [0, 1, 900, 1700, 2200, 2800, 3000])
def test_same_selection_at_every_budget(monkeypatch, tmp_path, budget):
    with actor_fixture(monkeypatch, tmp_path, 'flat') as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        index, args = snapshot(actor)
        args['max_bytes'] = budget
        args['attempts'][0]['error_details'] = '中文数据' * 80
        flat, linked = packets(actor, index, args)
        if linked is None:
            assert flat is None
        else:
            assert len(dumps(linked).encode()) <= budget
            assert {**flat, 'mode': 'linked', 'links': linked['links']} == linked


def test_identity_rebuild_goal_isolation_and_source_integrity(monkeypatch, tmp_path):
    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        index, args = snapshot(actor)
        _, linked = packets(actor, index, args)
        again, _ = snapshot(actor)
        _, rebuilt = packets(actor, again, args)
        assert rebuilt == linked
        assert index.goal('task one') != index.goal('task two')
        assert index.goal('task one') == again.goal('task one')
        other = graph.GraphIndex('another-episode', index.task_id)
        with pytest.raises(graph.GraphIntegrityError):
            other.sync(actor.mini_context.read)
        broken = deepcopy(args)
        ref = next(iter(broken['sources']))
        broken['sources'][ref]['sha256'] = '0' * 64
        with pytest.raises(graph.GraphIntegrityError):
            packets(actor, index, broken)
        assert index.cursor == again.cursor
        index.sync(lambda query, params: actor.mini_context.read(
            query.replace('WHERE seq>?', 'WHERE seq>? AND seq<=?'), (params[0], again.cursor)))
        assert index.cursor == again.cursor


def test_recipe_identity_is_content_based_and_namespaced():
    from kobe_views.keyboard_view import active_catalog

    index = graph.GraphIndex('episode', 'task')
    recipes = deepcopy(active_catalog()['editing']['recipes'])
    before = [index.recipe('editing', r) for r in recipes]
    after = [index.recipe('editing', r) for r in reversed(recipes)]
    assert before == list(reversed(after))
    assert index.recipe('popup_dismiss', active_catalog()['popup_dismiss']['recipes'][0]) not in before
    with pytest.raises(graph.GraphIntegrityError):
        index.recipe('editing', {'tool': {'action': 'key', 'keys': ['made_up']}})


def test_temporary_recipe_identity_does_not_escape_its_task_namespace():
    from kobe_views.keyboard_view import active_catalog

    index = graph.GraphIndex('episode', 'task')
    entry = deepcopy(active_catalog()['editing'])
    catalog = {'identity': {'scope_id': 'task-one'}, 'topics': {'task.app.editing': entry},
               'sources': deepcopy(graph.DATA['sources'])}
    first = index.recipe('task.app.editing', entry['recipes'][0], task_catalog=catalog)
    other = deepcopy(catalog)
    other['identity']['scope_id'] = 'task-two'
    assert first != index.recipe('task.app.editing', entry['recipes'][0], task_catalog=other)
    entry['scope'] = 'another focus precondition'
    assert first != index.recipe('task.app.editing', entry['recipes'][0], task_catalog=catalog)


def test_foreign_task_unexecuted_commands_and_repeated_action_identity(monkeypatch, tmp_path):
    from test_mini_taskviews import TASK

    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        predict(actor, obs, dispatch=False)
        index, args = snapshot(actor)
        assert len(args['attempts']) == 2
        assert len({index.event(r['ref']) for r in args['attempts']}) == 2
        raw = {'episode_id': index.episode_id, 'frame_id': args['frame_id'], 'sources': args['sources'],
               'views': {k: {'records': [], 'omitted_records': 0} for k in graph.VIEW_IDS}}
        raw['views']['attempts']['records'] = args['attempts']
        with pytest.raises(graph.GraphIntegrityError, match='another task'):
            graph.normalize(raw, index, TASK + ' changed')
        actor.execution_journal.finish_pending('unexecuted fixture')
        index.sync(actor.mini_context.read)
        unexecuted = [r for r in index.events.values() if r['kind'] == 'unexecuted_command']
        assert unexecuted
        assert all(index.identities[index.event(r['seq'])]['kind'] != 'action' for r in unexecuted)


def test_graph_proof_cannot_qualify_a_different_mode(tmp_path, monkeypatch):
    from scripts import verified_invoice as verified

    plan = verified.specification()
    identity = {'fixture': 'source'}
    monkeypatch.setattr(verified, 'project_identity', lambda: identity)
    for case in ('limit', 'terminate', 'empty'):
        value = {k: deepcopy(plan[k]) for k in ('model', 'base_url', 'cua_contract', 'generation_fields',
            'max_steps', 'experiment', 'mini_keyboard_tools', 'mini_keyboard_selection', 'mini_graph_mode', 'mini_graph')}
        value.update(passed=True, arm='taskviews', case=case, provider='autodl', project_source=identity,
                     source_unchanged=True, live_api_called=False, vm_started=False)
        verified.write(tmp_path / f'taskviews-{case}/validation.json', value)
    assert verified.validation_evidence(tmp_path, 'autodl', plan['base_url'], plan['cua_contract'], plan)
    changed = deepcopy(plan)
    changed.update(mini_graph_mode='flat', mini_graph=graph.policy('flat'))
    with pytest.raises(ValueError, match='offline integration'):
        verified.validation_evidence(tmp_path, 'autodl', plan['base_url'], plan['cua_contract'], changed)


def test_exact_recipe_match_and_no_suggested_or_partial_key_matches(monkeypatch, tmp_path):
    from kobe_views.keyboard_view import record
    from test_mini_taskviews import TASK

    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        index, args = snapshot(actor)
        # Normalize the same candidate facts without budget pressure to examine every relation.
        raw = {'episode_id': index.episode_id, 'frame_id': args['frame_id'], 'sources': args['sources'],
               'views': {k: {'records': [], 'omitted_records': 0} for k in ('current', 'keyboard', 'attempts', 'lessons')}}
        raw['views']['current']['records'] = [args['current']]
        raw['views']['attempts']['records'] = args['attempts']
        raw['views']['keyboard']['records'] = [record('editing', 'same_actor_explicit_lookup')]
        value = graph.normalize(raw, index, TASK)
        assert any(r == 'matches_recipe' for _, r, _ in value['links'])
        raw['views']['keyboard']['records'][0]['memory'] = deepcopy(args['keyboard']['memory'])
        raw['views']['lessons']['records'] = args['lessons']
        shared = graph.normalize(raw, index, TASK)
        action_alias = shared['views']['attempts']['record_refs'][0][0]
        keyboard_alias, keyboard_facet = shared['views']['keyboard']['record_refs'][0]
        assert shared['nodes'][keyboard_alias]['facets'][keyboard_facet]['memory'][0][0] == action_alias
        memory = deepcopy(args['keyboard']['memory'][0])
        memory.update(key_status='suggested_correction_not_executed', effect_status='key_not_emitted')
        raw['views']['keyboard']['records'][0]['memory'] = [memory]
        assert not any(r == 'matches_recipe' for _, r, _ in graph.normalize(raw, index, TASK)['links'])


def test_model_artifact_review_links_remain_unverified(monkeypatch, tmp_path):
    from kobe_views.artifact_view import CHECKS, tagged_review
    from test_mini_taskviews import TASK

    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, _, predict):
        predict(actor, obs)
        journal = actor.execution_journal
        observed = journal.current
        review = tagged_review({'candidate': '/synthetic/candidate',
                                **{key: [observed['seq'], 'Synthetic visual proposal'] for key in CHECKS}})
        journal.append('decision', instruction=TASK, response=review, local_instruction=review,
                       source=observed['id'], commands=[], tools=[])
        predict(actor, obs)
        index, args = snapshot(actor)
        raw = {'episode_id': index.episode_id, 'frame_id': args['frame_id'], 'sources': args['sources'],
               'views': {k: {'records': [], 'omitted_records': 0} for k in graph.VIEW_IDS}}
        raw['views']['current']['records'] = [args['current']]
        raw['views']['lessons']['records'] = args['lessons']
        value = graph.normalize(raw, index, TASK)
        reports = [ref for ref in value['views']['lessons']['record_refs'] if ref[1] == 'model_artifact_review']
        assert reports
        alias, facet = reports[0]
        assert set(value['nodes'][alias]['facets'][facet]['verification'].values()) == {'unknown'}
        assert any(a == alias and relation == 'reports_on' for a, relation, _ in value['links'])


@pytest.mark.parametrize('action', ['key_down', 'key_up'])
def test_partial_key_events_do_not_match_a_recipe(monkeypatch, tmp_path, action):
    from kobe_views.keyboard_view import record
    from test_mini_taskviews import TASK

    with actor_fixture(monkeypatch, tmp_path, 'linked', actions=[{'action': action, 'keys': ['ctrl']}] * 2
                       ) as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        index, args = snapshot(actor)
        raw = {'episode_id': index.episode_id, 'frame_id': args['frame_id'], 'sources': args['sources'],
               'views': {k: {'records': [], 'omitted_records': 0} for k in graph.VIEW_IDS}}
        raw['views']['attempts']['records'] = args['attempts']
        raw['views']['keyboard']['records'] = [record('editing', 'same_actor_explicit_lookup')]
        assert not any(r == 'matches_recipe' for _, r, _ in graph.normalize(raw, index, TASK)['links'])


def test_checkpoint_modes_and_legacy_missing_declaration(monkeypatch, tmp_path):
    from ui_kobe.osworld.checkpoints import ReadAnomaly

    for mode in graph.MODES:
        with actor_fixture(monkeypatch, tmp_path / mode, mode) as (actor, obs, _, predict):
            predict(actor, obs)
            state = actor.checkpoint_state()
            actor.restore_checkpoint_state(deepcopy(state))
            assert actor.mini_context.cached is None and actor.mini_context.graph_index is None
            changed = deepcopy(state)
            changed['mini_graph_mode'] = 'flat' if mode != 'flat' else 'linked'
            changed['mini_graph'] = graph.policy(changed['mini_graph_mode'])
            with pytest.raises(ReadAnomaly, match='cannot be switched'):
                actor.restore_checkpoint_state(changed)
            missing = {k: v for k, v in state.items() if not k.startswith('mini_graph')}
            if mode == 'legacy':
                actor.restore_checkpoint_state(missing)
            else:
                with pytest.raises(ReadAnomaly):
                    actor.restore_checkpoint_state(missing)


def test_new_plan_default_and_frozen_modes():
    from scripts.verified_invoice import specification

    assert specification()['mini_graph_mode'] == 'linked'
    assert graph.plan_policy({}) == graph.policy('legacy')
    for mode in graph.MODES:
        plan = specification(mini_graph_mode=mode)
        assert graph.plan_policy(plan) == graph.policy(mode)
        assert plan['arm_profiles']['taskviews'].get('graph') == (graph.policy(mode) if mode != 'legacy' else None)
    with pytest.raises(ValueError):
        graph.plan_policy({'mini_graph_mode': 'linked'})


def test_legacy_materializer_is_still_independent():
    assert legacy_materialize.__module__ == 'kobe_views.fixed_views'
