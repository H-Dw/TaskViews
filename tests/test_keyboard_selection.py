"""Public task matching, reproducible preparation and actual scoped delivery."""
from copy import deepcopy
import json
import os
from types import SimpleNamespace

import pytest

from kobe_views.keyboard_selection import resolve_task_toolsets, task_keyboard_policy, validate_task_keyboard
from kobe_views.keyboard_view import DATA, TOOLSETS
from scripts import verified_invoice as verified
from scripts.run_official_native_tasks import configure_profile
from test_keyboard_view import annotated
from test_mini_profiles import mini_plan
from test_mini_taskviews import make_actor, packet, predict


@pytest.mark.parametrize('toolset', DATA['task_aliases'])
def test_every_registered_name_is_selected_or_has_a_platform_skip_reason(toolset):
    alias = DATA['task_aliases'][toolset][0]
    result = resolve_task_toolsets({'instruction': f'Use {alias} for this task.'})
    entry = TOOLSETS[toolset]
    usable = not entry['reference_only'] and bool(entry['topics']) and 'linux' in entry['platforms']
    assert result['enabled_toolsets'] == (['general', toolset] if usable else ['general'])
    evidence = result['matches'] if usable else result['skipped']
    assert evidence == [{'toolset': toolset, 'source': 'instruction', 'alias': alias,
                         **({} if usable else {'reason': 'unavailable_on_runtime_platform'})}]


def test_aliases_unicode_multiple_apps_and_explicit_additions_are_deterministic():
    task = {'instruction': '用ＶＬＣ播放，在vs code编辑，使用CHROME查看。'}
    result = resolve_task_toolsets(task, requested=['type.browser', 'app.vlc'])
    assert result['enabled_toolsets'] == ['general', 'app.chrome', 'app.vlc', 'app.vscode', 'type.browser']
    assert result == resolve_task_toolsets(deepcopy(task), requested=['app.vlc', 'type.browser'])
    assert result['requested_toolsets'] == ['app.vlc', 'type.browser']


def test_structured_apps_allow_exact_ids_without_ambiguous_prose_inference():
    task = {'instruction': 'Write a word, preview files, open mail and take notes in the writer.',
            'related_apps': ['libreoffice_calc', 'app.vscode', 'word']}
    result = resolve_task_toolsets(task)
    assert result['enabled_toolsets'] == ['general', 'app.libreoffice_calc', 'app.vscode']
    assert all(row['source'] == 'related_apps' for row in result['matches'])
    assert result['skipped'][0]['toolset'] == 'app.word'


@pytest.mark.parametrize('instruction', [
    'Write a word; preview files, mail and notes. A writer can calc the result.',
    'Use my_vlc_player, GIMPicture, NotChrome and VSCodeExtension.',
    'Open the document in LibreOffice.', 'Use an unknown application.',
])
def test_ambiguous_names_substrings_and_unknown_apps_do_not_enable_directories(instruction):
    result = resolve_task_toolsets({'instruction': instruction})
    assert result['enabled_toolsets'] == ['general']
    assert not result['matches'] and not result['skipped']


def test_only_public_task_fields_are_read_and_manual_mode_disables_name_matching():
    task = {'instruction': 'Use VLC.', 'related_apps': ['Chrome'],
            'evaluator': {'instruction': 'Use GIMP'}, 'config': [{'command': 'firefox'}],
            'observation': 'Evince', 'actor_prose': 'Use MATLAB'}
    public = {key: task[key] for key in ('instruction', 'related_apps')}
    assert resolve_task_toolsets(task) == resolve_task_toolsets(public)
    manual = resolve_task_toolsets(task, mode='manual', requested=['app.evince'])
    assert manual['enabled_toolsets'] == ['general', 'app.evince']
    assert not manual['matches'] and not manual['skipped']
    assert resolve_task_toolsets(task, mode='manual')['enabled_toolsets'] == ['general']
    with pytest.raises(ValueError, match='incompatible'):
        resolve_task_toolsets(task, requested=['app.word'])


@pytest.mark.parametrize('task', [[], {'instruction': None}, {'related_apps': 'vlc'}, {'related_apps': [None]}])
def test_malformed_task_metadata_fails_before_preparation(task):
    with pytest.raises(ValueError):
        resolve_task_toolsets(task)


@pytest.mark.parametrize('change', ['mode', 'evidence', 'task', 'catalog'])
def test_changed_selection_task_or_catalog_invalidates_a_frozen_plan(change):
    task = {'instruction': 'Use VLC.'}
    plan = task_keyboard_policy(task)
    validate_task_keyboard(plan, task)
    if change == 'mode':
        plan['mini_keyboard_selection']['mode'] = 'manual'
    elif change == 'evidence':
        plan['mini_keyboard_selection']['matches'][0]['alias'] = 'invented'
    elif change == 'task':
        task['instruction'] = 'Use GIMP.'
    else:
        plan['mini_keyboard_tools']['catalog_sha256'] = 'old'
    with pytest.raises(ValueError, match='Frozen task keyboard'):
        validate_task_keyboard(plan, task)


@pytest.mark.parametrize('mode', ['task_names', 'manual'])
def test_verified_prepare_and_validation_use_the_actual_public_task(tmp_path, monkeypatch, mode):
    task = {'instruction': 'Use VLC and VS Code.', 'related_apps': ['Chrome']}
    task_file = tmp_path / verified.task_path('invoice')
    verified.write(task_file, task)
    sources = {'benchmark': {'repo': str(tmp_path)}, 'actor_compiler': {'repo': str(tmp_path)}}
    evidence = {'directory': str(tmp_path / 'proof'), 'sha256': {}}
    monkeypatch.setattr(verified, 'verify_task', lambda *a: verified.read(task_file))
    monkeypatch.setattr(verified, 'sources', lambda *a: sources)
    monkeypatch.setattr(verified, 'project_identity', lambda: {})
    monkeypatch.setattr(verified, 'asset_files', lambda task: [])
    observed = []

    def validation(*args):
        observed.append(args[-1]['mini_keyboard_selection'])
        return evidence

    monkeypatch.setattr(verified, 'validation_evidence', validation)
    monkeypatch.setattr(verified.subprocess, 'check_output', lambda *a, **k: 'fixture-commit')
    args = SimpleNamespace(root=tmp_path / 'plan', benchmark_repo=tmp_path, compiler_repo=tmp_path,
        assets=tmp_path, image=tmp_path / 'no-image', image_proof=tmp_path / 'no-proof',
        validation_dir=tmp_path / 'proof', provider='qwen', sx_url_env='SX_URL',
        coordinate_type='absolute', experiment='legacy-low35', keyboard_mode=mode,
        keyboard_toolset=['type.browser'])
    verified.prepare(args)
    plan = verified.validate_plan(args.root)
    expected = task_keyboard_policy(task, mode=mode, requested=['type.browser'])
    assert all(plan[key] == value for key, value in expected.items())
    assert observed == [expected['mini_keyboard_selection']] * 2
    # Even a rehashed plan cannot change its selection evidence silently.
    plan['mini_keyboard_selection']['task_input_sha256'] = 'different'
    verified.write(args.root / 'plan.json', plan)
    verified.write(args.root / 'plan.sha256.json', {'sha256': verified.sha(args.root / 'plan.json')})
    with pytest.raises(ValueError, match='Frozen task keyboard'):
        verified.validate_plan(args.root)


AVAILABLE = [key for key in DATA['task_aliases']
             if not TOOLSETS[key]['reference_only'] and 'linux' in TOOLSETS[key]['platforms']
             and TOOLSETS[key]['topics']]


@pytest.mark.parametrize('toolset,topic', [(key, topic) for key in AVAILABLE for topic in TOOLSETS[key]['topics']])
def test_automatic_choice_reaches_actor_and_scoped_lookup_stays_within_budget(monkeypatch, tmp_path, toolset, topic):
    task = {'related_apps': [toolset]}
    plan = {**mini_plan(), 'official': task, **task_keyboard_policy(task)}
    manifest = {key: plan[key] for key in ('taskviews_profile', 'mini_profile', 'source_branch',
                                           'mini_keyboard_tools', 'mini_keyboard_selection')}
    from scripts import osworld_native_experiment
    monkeypatch.setattr(osworld_native_experiment, 'require_mini_branch', lambda: None)
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', '["app.gimp"]')  # Must not leak into a different plan.
    configure_profile(plan, manifest)
    assert json.loads(os.environ['UI_KOBE_MINI_KEYBOARD_TOOLS']) == [toolset]
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    lookup = toolset + '.' + topic
    try:
        annotated(transport, lambda: f'<key_lookup>{lookup}</key_lookup>')
        predict(actor, obs)
        guide = packet(transport)['views']['current']['records'][0]['keyboard_lookup']
        assert lookup in guide['topics']
        predict(actor, obs)
        rows = packet(transport)['views']['keyboard']['records']
        assert rows and rows[0]['topic'] == lookup
        assert actor.mini_context.trace['packet_bytes'] <= 3000 and len(transport.requests) == 2
        assert actor.checkpoint_state()['keyboard_tools']['enabled_toolsets'] == ['general', toolset]
        with pytest.raises(RuntimeError, match='Manifest fixed-view contract'):
            configure_profile(plan, {**manifest, 'mini_keyboard_selection': {}})
    finally:
        actor.close()


def test_multi_app_topics_are_discoverable_together_without_larger_view_budget(monkeypatch, tmp_path):
    task = {'instruction': 'Use Chrome, VSCode, VLC, LibreOffice Writer and GIMP.'}
    selected = resolve_task_toolsets(task)['enabled_toolsets'][1:]
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', json.dumps(selected))
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    try:
        predict(actor, obs)
        guide = packet(transport)['views']['current']['records'][0]['keyboard_lookup']
        assert all(any(topic.startswith(key + '.') for topic in guide['topics']) for key in selected)
        assert actor.mini_context.trace['packet_bytes'] <= 3000
    finally:
        actor.close()
