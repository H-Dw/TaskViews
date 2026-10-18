"""Catalog provenance, opt-in isolation, native compilation and frozen selection."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re

import pytest

from kobe_views.keyboard_view import (CATALOG, DATA, TOOLSETS, active_catalog, key_topic,
                                      normalize_toolsets, policy, record, select_topic)
from scripts.render_keyboard_tools import PROJECT, render_documents
from scripts.run_official_native_tasks import configure_profile
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.taskviews_profiles import validate_profile
from test_keyboard_view import annotated
from test_mini_profiles import mini_plan
from test_mini_taskviews import make_actor, packet, predict


@pytest.mark.parametrize('intent', ['Zoom out in Evince', 'Rename the selected file', 'Maximize the window',
    'Minimize the window', '缩小文档', '重命名文件', '先最大化再编辑', 'edit then zoom out'])
def test_scoped_intents_never_receive_a_software_default(intent):
    assert select_topic([intent])[0] is None
    assert not {'zoom', 'rename', 'window_maximize', 'window_minimize', 'file_transfer'} & CATALOG.keys()


@pytest.mark.parametrize('lookup', ['app.evince.zoom', 'type.browser.zoom', 'platform.gnome.window_maximize',
                                   'type.file_manager.rename', 'app.vlc.playback'])
def test_exact_lookup_cannot_enable_its_own_toolset(lookup):
    assert select_topic([f'<key_lookup>{lookup}</key_lookup>'])[0] is None
    with pytest.raises(KeyError):
        record(lookup, 'untrusted_request')


@pytest.mark.parametrize('toolsets', ['app.evince', ['general'], ['app.evince', 'app.evince'], ['unknown'],
    ['platform.windows'], ['platform.macos'], ['app.word'], ['app.safari'], ['type.android'], ['type.graphics'], [None]])
def test_unknown_duplicate_and_foreign_toolsets_fail_before_generation(toolsets):
    with pytest.raises(ValueError):
        normalize_toolsets(toolsets)


def test_explicit_scoped_lookup_preserves_chord_semantics_and_never_overrides_general():
    selected = ['app.evince', 'type.browser', 'platform.gnome']
    active = active_catalog(selected)
    assert active['page_navigation'] == CATALOG['page_navigation']
    assert [r['tool']['keys'] for r in active['page_navigation']['recipes']] == [['pagedown'], ['pageup']]
    assert select_topic(['zoom out'], selected)[0] is None
    request = '<key_lookup>app.evince.page_navigation</key_lookup>'
    topic, reason = select_topic([request], selected)
    assert record(topic, reason, toolsets=selected)['recipes'][0]['tool']['keys'] == ['ctrl', 'pagedown']
    assert 'app.vlc.playback' not in active


def test_latest_empty_or_invalid_intent_does_not_revive_an_old_request():
    for latest in ('', None, {}, '<key_lookup>../app.evince</key_lookup>',
                   '<key_lookup>editing</key_lookup></key_lookup>'):
        assert select_topic([latest, '<key_lookup>page_navigation</key_lookup>'])[0] is None


def test_unknown_or_different_keys_are_not_editing_or_page_memory():
    assert key_topic(['f2'], 'editing') is None
    assert key_topic(['ctrl', 'pagedown'], 'page_navigation') is None
    assert key_topic(['pagedown'], 'page_navigation') == 'page_navigation'
    value = record('editing', 'test')
    value['recipes'][0]['tool']['keys'].append('f2')
    assert record('editing', 'test')['recipes'][0]['tool']['keys'] == ['ctrl', 'a']


def test_all_declared_key_recipes_compile_with_real_pinned_compiler_and_valid_backend_tokens():
    from mm_agents.qwen.actions import translate_tool_calls
    from mm_agents.qwen.images import ProcessedScreenshot
    from mm_agents.qwen.parser import ToolCall, parse_keys

    # Read the installed keyboard-name table without importing PyAutoGUI or
    # opening a display. The compiler is real; commands are never executed.
    tree = ast.parse(Path(importlib.util.find_spec('pyautogui').origin).read_text())
    names = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'KEY_NAMES' for target in node.targets))
    for toolset_id, toolset in TOOLSETS.items():
        assert set(toolset['platforms']) <= {'linux', 'windows', 'macos', 'android'}
        for entry in toolset['topics'].values():
            assert entry['scope'] and entry['check'] and entry['sources']
            assert set(entry['sources']) <= DATA['sources'].keys()
            for recipe in entry['recipes']:
                action = recipe['tool']
                assert set(action) == {'action', 'keys'} and action['action'] == 'key'
                assert action['keys'] and parse_keys(action['keys']) == action['keys']
                assert not {'page_down', 'page_up', 'minus'} & set(action['keys'])
                assert all(token in names for token in action['keys']), (toolset_id, action)
                if toolset['reference_only'] or 'linux' not in toolset['platforms']:
                    continue
                result = translate_tool_calls([ToolCall(action, 0, 0)],
                    screenshot=ProcessedScreenshot('', 'absolute', 1920, 1080, 1920, 1080),
                    coordinate_type='absolute', enable_zoom=False)
                assert result.commands and len(result.commands) == 1
                call = ast.parse(result.commands[0]).body[0].value
                assert isinstance(call, ast.Call) and call.func.value.id == 'pyautogui'
                assert call.func.attr in ('press', 'hotkey')


def test_generated_documents_and_json_examples_are_synchronized():
    for path, content in render_documents().items():
        assert (PROJECT / 'tools/keyboard' / path).read_text(encoding='utf-8') == content, path
        for block in re.findall(r'```json\n(.*?)\n```', content, re.S):
            assert isinstance(json.loads(block), list)


def test_runner_freezes_opt_in_and_clears_undeclared_environment(monkeypatch):
    monkeypatch.setattr('scripts.osworld_native_experiment.require_mini_branch', lambda: None)
    plan = mini_plan()
    manifest = {key: plan[key] for key in ('taskviews_profile', 'mini_profile', 'source_branch')}
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', '["app.evince"]')
    configure_profile(plan, manifest)
    import os
    assert json.loads(os.environ['UI_KOBE_MINI_KEYBOARD_TOOLS']) == []
    plan['mini_keyboard_tools'] = policy(['app.evince'])
    with pytest.raises(RuntimeError, match='frozen Mini plan'):
        configure_profile(plan, manifest)
    manifest['mini_keyboard_tools'] = deepcopy(plan['mini_keyboard_tools'])
    configure_profile(plan, manifest)
    assert json.loads(os.environ['UI_KOBE_MINI_KEYBOARD_TOOLS']) == ['app.evince']
    manifest['mini_keyboard_tools']['catalog_sha256'] = 'foreign'
    with pytest.raises(RuntimeError):
        configure_profile(plan, manifest)
    plan['mini_keyboard_tools']['enabled_toolsets'].append('app.word')
    with pytest.raises(ValueError):
        validate_profile(plan)


def test_actor_retrieves_only_explicitly_enabled_scoped_tool_and_checkpoint_preserves_it(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', '["app.evince"]')
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    annotated(transport, lambda: '<key_lookup>app.evince.zoom</key_lookup>')
    predict(actor, obs)
    predict(actor, obs)
    value = packet(transport)['views']['keyboard']['records'][0]
    assert value['toolset'] == 'app.evince'
    assert value['recipes'][0]['tool'] == {'action': 'key', 'keys': ['ctrl', '-']}
    assert actor.mini_context.trace['packet_bytes'] <= 3000 and len(transport.requests) == 2
    saved = actor.checkpoint_state()
    actor.restore_checkpoint_state(saved)
    actor.keyboard_toolsets = ()
    with pytest.raises(ReadAnomaly, match='profile differs'):
        actor.restore_checkpoint_state(saved)
    actor.close()


def test_default_actor_prompt_never_advertises_application_topics(monkeypatch, tmp_path):
    monkeypatch.delenv('UI_KOBE_MINI_KEYBOARD_TOOLS', raising=False)
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    annotated(transport, lambda: '<key_lookup>app.evince.zoom</key_lookup>')
    predict(actor, obs)
    predict(actor, obs)
    assert not packet(transport)['views']['keyboard']['records']
    first_packet = json.loads(transport.requests[0]['messages'][-1]['content'][-1]['text'].split('\n', 1)[1])
    hint = first_packet['views']['current']['records'][0]['keyboard_lookup']
    assert 'app.evince.zoom' not in hint['topics'] and 'page_navigation' in hint['topics']
    assert actor.checkpoint_state()['keyboard_tools']['enabled_toolsets'] == ['general']
    actor.close()


def test_runtime_catalog_is_part_of_source_freeze():
    from scripts.osworld_native_experiment import project_snapshot
    assert any(path.replace('\\', '/') == 'kobe_views/key_tools/catalog.json' for path in project_snapshot())
    from scripts.verified_invoice import project_identity, specification
    assert any(path.replace('\\', '/') == 'kobe_views/key_tools/catalog.json' for path in project_identity())
    assert specification()['mini_keyboard_tools']['enabled_toolsets'] == ['general']


def test_scoped_tools_cannot_be_silently_hidden_by_legacy_controls(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', '["app.evince"]')
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'mini_controls_v1')
    with pytest.raises(ValueError, match='legacy controls-only'):
        make_actor(monkeypatch, tmp_path)
