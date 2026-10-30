"""Generic positive and negative examples, independent of benchmark prompts."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance
from kobe_views.guidance_semantics import analyze, operations
from kobe_views.keyboard_selection import task_keyboard_policy
from test_keyboard_guidance import event, names, route


@pytest.mark.parametrize('text,expected,absent', [
    ('The text is cut off.', set(), {'cut'}), ('Cut off the extra border.', set(), {'cut'}),
    ('Cut the selected file.', {'cut'}, set()), ('Do not cut the file.', set(), {'cut'}),
    ('Open menu', {'menu_open'}, {'open'}), ('Open the View menu', {'menu_open'}, {'open'}),
    ('Open a context menu', {'menu_open'}, {'open'}),
    ('The menu is open.', set(), {'open'}), ('Open the document', {'open'}, {'menu_open'}),
    ('Zoom in', {'zoom_in'}, set()), ('Do not zoom in', set(), {'zoom_in'}),
    ('Zoom in is disabled', set(), {'zoom_in'}), ('The window is full screen.', set(), {'fullscreen'}),
    ('The Cut command is disabled', set(), {'cut'}), ('The file is read-only', set(), {'reading'}),
    ('I can see the context menu', set(), {'context_menu'}),
    ('Type a larger zoom value', {'readability'}, {'edit', 'zoom_value'}),
    ('The zoom field is visible', set(), {'zoom_value'}),
    ('Scroll right to see more content', {'horizontal_scroll'}, {'down'}),
    ('Confirm that the file exists', set(), {'confirm'}),
    ('Read the document, then zoom out', {'reading', 'zoom_out'}, set()),
    ('Move the mouse to the top', set(), {'move'}),
    ('Put the selected files into a folder', {'transfer'}, set()),
    ('将文件放入目标文件夹', {'transfer'}, set()),
    ('文字被截断。打开菜单。不要剪切。', {'menu_open'}, {'cut', 'open'}),
])
def test_actions_are_not_reported_state_or_object_name(text, expected, absent):
    assert expected <= operations(text)
    assert not absent & operations(text)
    assert analyze(text) == analyze(text)


def test_freeze_capabilities_and_auxiliary_directories_from_generic_relations():
    for text in ('Put the files into a folder', 'Read and compare PDF documents'):
        plan = task_keyboard_policy({'instruction': text}, mode='task_capabilities')
        assert 'type.file_manager' in plan['mini_guidance']['enabled_toolsets']
    assert 'app.evince' in plan['mini_guidance']['enabled_toolsets']
    assert plan['mini_guidance']['focus_confirmation'] == 'required_not_inferred'
    assert plan['mini_guidance']['semantics'] == 'public_operation_semantics_v6'
    assert {'zoom_in', 'zoom_out', 'down', 'up'} <= set(plan['mini_guidance']['capabilities'])
    copy = task_keyboard_policy({'instruction': 'Copy files'}, mode='task_capabilities')
    assert 'paste' in copy['mini_guidance']['capabilities']


def test_runtime_file_intent_is_independent_of_original_task_and_gap_is_explicit():
    kwargs = {'instruction': 'Inspect visible application', 'proposals': [(3, 'Move the files into a folder', 1)]}
    value = route(**kwargs)
    assert names(value) == []
    assert any('move' in gap['missing'] for gap in value['coverage_gaps'])
    disabled = route(**kwargs, enabled=['general'])
    assert any(g['reason'] == 'capability_not_frozen' for g in disabled['coverage_gaps'])
    directory_only = route(instruction='Move files', enabled=['general'])
    assert any(g['reason'] == 'directory_not_frozen' for g in directory_only['coverage_gaps'])
    assert disabled['enabled_directories'] == ['general']
    assert names(disabled) == []


def test_cut_off_never_delivers_clipboard_and_menu_never_delivers_ctrl_o():
    value = route(instruction='Read content', proposals=[(3, 'The right edge is cut off', 1)])
    assert names(value)[0] == 'view.readability'
    assert not any('cut' in n for n in names(value))
    value = route(instruction='Inspect application', proposals=[(3, 'Open menu', 1)])
    assert names(value)[0] == 'menu.open'
    assert value['groups'][0]['record']['recipes'] == []


def test_zoom_card_has_edit_confirmation_and_check_or_scoped_binding():
    value = route(instruction='Read document', proposals=[(3, 'Zoom in', 1)], enabled=['general'])
    card = value['groups'][0]['record']
    assert names(value)[0] == 'view.zoom_in'
    assert not card['recipes']
    assert 'Zoom In control' in card['scope'] and 'inspect' in card['steps']
    scoped = route(instruction='Read PDF', proposals=[(3, 'Zoom in Evince', 1)], enabled=['general', 'app.evince'])
    assert scoped['groups'][0]['record']['recipes'][0]['tool']['keys'] == ['ctrl', '+']


def test_old_specific_catalog_match_cannot_outrank_new_action():
    value = route(instruction='Inspect content', proposals=[(6, 'Type the new label', 2),
                   (3, 'context menu', 1)], step=3)
    assert names(value)[0] == 'text.edit'
    value = route(instruction='Read content', proposals=[(6, 'The text is cut off; scroll right', 2),
                   (3, 'Scroll down', 1)], step=3)
    assert names(value)[0] == 'navigation.horizontal'


def test_compact_card_preserves_all_actionable_fields_and_audit_resolves_source():
    value = route(instruction='Move files')
    original = value['groups'][0]['record']
    card = guidance.model_card(original)
    assert value['guide_sources'][card['source_ref']] == original['source']
    assert 'https://' not in json.dumps(card)
    for key in ('scope', 'recipes', 'steps', 'evidence', 'guide_id'):
        assert original[key] == card[key]
    assert guidance.delivery_audit(value, [card], False, True)['complete_workflow_groups'] == 1
    wrong = deepcopy(card)
    wrong['steps'] = 'paste'
    assert guidance.delivery_audit(value, [wrong], False, True)['complete_workflow_groups'] == 0
    wrong = deepcopy(card)
    wrong['recipes'][0]['tool']['keys'] = ['ctrl', 'c']
    assert guidance.delivery_audit(value, [wrong], False, True)['needed_recipes_delivered'] == 1


def test_exact_toggle_cycle_is_advisory_and_clipboard_is_not_failure():
    rows = [(n, {'kind': 'observation', 'id': str(n), 'images': {'original': {'sha256': h * 64}}}, 'a' * 64)
            for n, h in [(1, 'a'), (2, 'b'), (3, 'a'), (4, 'b'), (5, 'a')]]
    rows += [event(['super'], seq=10+n, source=str(n), target=str(n+1)) for n in range(1, 5)]
    value = route(rows=rows)
    assert value['literal_cycle']['period'] == 2
    assert value['literal_cycle']['effect_status'] == 'unknown'
    assert names(value) == ['files.copy']
    for _, row, _ in rows:
        if row['kind'] == 'transition':
            row['tool']['arguments']['keys'] = ['ctrl', 'c']
    assert route(rows=rows)['literal_cycle'] is None


def test_changed_pixels_or_failed_dispatch_cannot_prove_cycle():
    observations = {str(n): (n, {'images': {'original': {'sha256': str(n) * 64}}}) for n in range(1, 6)}
    actions = [(seq, row) for seq, row, _ in [event([], seq=10+n, source=str(n), target=str(n+1),
        tool={'arguments': {'action': 'scroll', 'direction': 'down', 'pixels': 200}}) for n in range(1, 5)]]
    assert guidance.repeated_cycle(actions, observations) is None
