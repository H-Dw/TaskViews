from copy import deepcopy
import json

import pytest

from kobe_views import mini_graph as graph
from kobe_views.artifact_view import REVIEW_SCHEMA
from kobe_views.mini_delivery import compact, lookup_guide, unpack
from kobe_views.model import dumps
from mini_graph_support import actor_fixture, projection_snapshot


def test_codec_preserves_all_selected_facts_links_and_source_hashes(monkeypatch, tmp_path):
    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        original = json.loads(actor.mini_context.cached)
        encoded = compact(original)
        assert unpack(encoded) == original
        assert graph.expand(encoded) == graph.expand(original)
        assert len(dumps(encoded).encode()) < len(dumps(original).encode())


@pytest.mark.parametrize('mode', ['flat', 'linked'])
def test_actual_actor_delivers_directory_and_literal_recipe_without_extra_calls(monkeypatch, tmp_path, mode):
    with actor_fixture(monkeypatch, tmp_path, mode, packing=graph.DELIVERY_PACKING) as (actor, obs, transport, predict):
        predict(actor, obs)
        initial = graph.expand(json.loads(actor.mini_context.cached))
        assert initial['views']['current']['records'][0]['keyboard_lookup']['groups'] == ['general']
        predict(actor, obs)
        packet = json.loads(actor.mini_context.cached)
        view = graph.expand(packet)['views']
        assert view['keyboard']['records'], len(dumps(packet).encode())
        assert view['keyboard']['records'][0]['recipes']
        assert view['attempts']['records']
        assert view['current']['records'][0]['artifact']['review_schema'] == REVIEW_SCHEMA
        assert len(transport.requests) == 2
        assert len(dumps(packet).encode()) <= 3000
        assert actor.mini_context.graph_audit['projection']['delivered']
        state = actor.checkpoint_state()
        actor.restore_checkpoint_state(state)
        changed = deepcopy(state)
        changed['mini_graph'] = graph.policy(mode)
        from ui_kobe.osworld.checkpoints import ReadAnomaly
        with pytest.raises(ReadAnomaly, match='cannot be switched'):
            actor.restore_checkpoint_state(changed)


@pytest.mark.parametrize('budget', [0, 1500, 2200, 2600, 2800, 3000])
def test_strict_ablation_complete_units_and_multibyte_budget(monkeypatch, tmp_path, budget):
    from test_mini_taskviews import TASK

    with actor_fixture(monkeypatch, tmp_path, 'linked', packing=graph.DELIVERY_PACKING) as (actor, obs, _, predict):
        predict(actor, obs)
        predict(actor, obs)
        index, args = projection_snapshot(actor)
        args['max_bytes'] = budget
        args['lessons'].append({'ref': args['attempts'][0]['ref'], 'grade': 'execution_error_record',
                                'error': '长错误原样保留' * 100, 'effect_status': 'unknown'})
        args['totals']['lessons'] += 1
        common = dict(index=index, instruction=TASK, packing=graph.DELIVERY_PACKING, **args)
        linked = graph.materialize(graph_mode='linked', **common)
        flat = graph.materialize(graph_mode='flat', **common)
        if linked is None:
            assert flat is None
        else:
            assert len(dumps(linked).encode()) <= budget
            assert {**flat, 'mode': 'linked', 'links': linked['links']} == linked
            assert all(a in linked['nodes'] and b in linked['nodes'] for a, _, b in unpack(linked)['links'])
            for record in graph.expand(linked)['views']['keyboard']['records']:
                assert record['recipes'] == args['keyboard']['recipes'][:len(record['recipes'])]
                assert len(record['recipes']) + record['recipes_omitted'] == len(args['keyboard']['recipes'])


def test_group_directory_is_enabled_scoped_and_does_not_infer_focus():
    guide = lookup_guide([], ('app.gimp',))
    assert 'app.gimp' in guide['groups'] and 'app.vlc' not in guide['groups']
    assert any(t.startswith('app.gimp.') for t in guide['topics'])
    full = lookup_guide(['<key_lookup>general</key_lookup>'], ('app.gimp',))
    assert len(full['topics']) > len(guide['topics'])
    assert all('.' not in t for t in full['topics'])
    assert lookup_guide(['<key_lookup>app.vlc</key_lookup>'], ('app.gimp',)) == guide
    assert lookup_guide(['', '<key_lookup>general</key_lookup>'], ('app.gimp',)) == guide
    assert lookup_guide(['List keys: <key_lookup>general</key_lookup>'], ('app.gimp',)) == full
    assert lookup_guide(['<key_lookup>general</key_lookup><key_lookup>app.gimp</key_lookup>'], ('app.gimp',)) == guide


def test_shared_error_and_keyboard_facets_survive_codec(monkeypatch, tmp_path):
    from test_mini_taskviews import TASK

    with actor_fixture(monkeypatch, tmp_path, 'linked') as (actor, obs, _, predict):
        predict(actor, obs, error='Original failure')
        predict(actor, obs)
        index, args = projection_snapshot(actor)
        raw = {'episode_id': index.episode_id, 'frame_id': args['frame_id'], 'sources': args['sources'],
               'views': {k: {'records': [], 'omitted_records': 0} for k in graph.VIEW_IDS}}
        raw['views']['current']['records'] = [args['current']]
        raw['views']['attempts']['records'] = args['attempts']
        raw['views']['lessons']['records'] = args['lessons']
        raw['views']['keyboard']['records'] = [args['keyboard']]
        original = graph.normalize(raw, index, TASK)
        assert unpack(compact(original)) == original
        action = original['views']['attempts']['record_refs'][0][0]
        assert {'execution_attempt', 'execution_error_record', 'key_memory'} <= set(original['nodes'][action]['facets'])


def test_strategy_is_frozen_without_upgrading_old_or_legacy_plans():
    from scripts.verified_invoice import specification

    assert graph.plan_policy({}) == graph.policy('legacy')
    for mode in ('flat', 'linked'):
        old = specification(mini_graph_mode=mode)
        new = specification(mini_graph_mode=mode, mini_graph_packing=graph.DELIVERY_PACKING)
        assert graph.plan_policy(old)['packing'] == graph.PACKING
        assert graph.plan_policy(new)['packing'] == graph.DELIVERY_PACKING
        assert graph.environment(new)[graph.PACKING_ENV] == graph.DELIVERY_PACKING
        assert graph.environment(new, 'baseline')[graph.ENV] == 'legacy'
        assert new['arm_profiles']['taskviews']['graph'] == graph.plan_policy(new)
        altered = deepcopy(new)
        altered['mini_graph']['schema_version'] = graph.VERSION
        with pytest.raises(ValueError):
            graph.plan_policy(altered)
    with pytest.raises(ValueError):
        graph.policy('legacy', graph.DELIVERY_PACKING)
