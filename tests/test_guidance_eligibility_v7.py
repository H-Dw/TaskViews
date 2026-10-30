"""Independent generic intent/target examples, no benchmark objects or answers."""
from copy import deepcopy

import pytest

from kobe_views import keyboard_guidance as g
from kobe_views.guidance_semantics import analyze, operations, immediate_actions
from kobe_views.guidance_groups import validate_library
from test_keyboard_guidance import route, names, event


CARD_CASES = [
    ('clipboard.copy_paste', 'Copy and paste selected text'),
    ('clipboard.move_paste', 'Cut and paste selected text'),
    ('clipboard.transfer', 'Copy or cut selected text, paste at the destination'),
    ('files.transfer', 'Transfer files'), ('clipboard.copy', 'Copy selected text'),
    ('clipboard.cut', 'Cut selected text'), ('clipboard.paste', 'Paste selected text'),
    ('files.copy', 'Copy files'), ('files.move', 'Move files'), ('files.rename', 'Rename the file'),
    ('text.edit', 'Type a label'), ('text.replace_confirm', 'Replace text and confirm'),
    ('text.confirm', 'Confirm the dialog'), ('ui.dismiss', 'Dismiss the popup'),
    ('history.undo', 'Undo the edit'), ('document.find', 'Find the phrase in the document'),
    ('document.open', 'Open the document'), ('document.save', 'Save the document'),
    ('document.save_as', 'Save as a new document'),
    ('navigation.down', 'Scroll down'), ('navigation.up', 'Scroll up'),
    ('capture.image', 'Take a desktop screenshot'), ('export.file', 'Export the document'),
    ('vlc.capture', 'Take a snapshot in VLC'), ('gimp.export', 'Export in GIMP'),
    ('navigation.horizontal', 'Scroll right'), ('view.zoom_value', 'Set zoom to 125%'),
    ('view.readability', 'Adjust the zoom'), ('menu.open', 'Open the View menu'),
    ('document.read', 'Read the document'), ('window.maximize', 'Maximize the window'),
    ('view.zoom_in', 'Zoom in'), ('view.zoom_out', 'Zoom out'),
    ('pointer.drag', 'Drag the object'),
    ('image.edit', 'Edit the image'), ('window.locate', 'Find the Archive window'),
    ('folder.open', 'Enter the folder'), ('url.open', 'Open the website'),
    ('files.find', 'Find the file'),
]


@pytest.mark.parametrize('card,text', CARD_CASES)
def test_each_authored_card_has_a_matching_public_need(card, text):
    value = route(instruction=text, enabled=['general', 'type.file_manager', 'app.vlc', 'app.gimp'])
    assert names(value)[0] == card
    assert not value['groups'][0]['record']['recipes'] or value['groups'][0]['record']['scope']


def test_three_phase_cards_require_real_phase_and_complete_contract_inventory():
    assert names(route(rows=[event(['ctrl', 'v'])]))[0] == 'clipboard.verify'
    for phase, name in [('confirm_once', 'view.zoom_confirm'), ('inspect_effect', 'view.zoom_check')]:
        assert names(route(instruction='Read content', pending_effect={'phase': phase, 'refs': [4]}))[0] == name
        value = route(instruction='Read content', proposals=[(3, f'<key_lookup>{name}</key_lookup>', 1)])
        assert name not in names(value)
    assert {n for n, _ in CARD_CASES} | {'clipboard.verify', 'view.zoom_confirm', 'view.zoom_check'} == set(g.LIBRARY['guides'])
    bad = deepcopy(g.LIBRARY)
    bad['guides']['document.open']['operations'] = ['menu_open']
    with pytest.raises(ValueError, match='contract mismatch'):
        validate_library(bad)


@pytest.mark.parametrize('text,expected,forbidden', [
    ('Open menu', {'menu_open'}, {'open'}),
    ('Open the folder', {'folder_open'}, {'open'}),
    ('Open the Archive window', {'window_locate'}, {'open'}),
    ('Find the application window', {'window_locate'}, {'find'}),
    ('Find the file', {'file_find'}, {'find'}),
    ('Open the website', {'url_open'}, {'open'}),
    ('Save as a new document', {'save_as'}, {'save'}),
    ('另存为新文件', {'save_as'}, {'save'}),
    ('Confirm the details', set(), {'confirm'}),
    ('Confirm that the file exists', set(), {'confirm'}),
    ('The text is cut off', set(), {'cut'}),
    ('Cut off the power', set(), {'cut'}),
    ('Move the mouse', set(), {'move'}),
    ('Do not copy the files', set(), {'copy'}),
    ('The copy of the document is open', set(), {'copy', 'open'}),
    ('Open copy.pdf', {'open'}, {'copy'}),
    ('Type "paste" into the field', {'edit'}, {'paste'}),
    ('<key_lookup>clipboard.copy', set(), {'copy'}),
    ('The topic is clipboard.copy', set(), {'copy'}),
    ('The file type is PDF', set(), {'edit'}),
    ('Capture attention', set(), {'capture'}),
    ('Save time', set(), {'save'}),
    ('Find out whether it exists', set(), {'find'}),
    ('If needed, copy the text', set(), {'copy'}),
    ('Zoom in is disabled', set(), {'zoom_in'}),
    ('I can read the content clearly', set(), {'reading'}),
    ('不要剪切文件', set(), {'cut'}),
    ('打开目标文件夹', {'folder_open'}, {'open'}),
    ('查看内容，然后打开菜单', {'reading', 'menu_open'}, {'open'}),
])
def test_keywords_require_an_action_and_correct_object(text, expected, forbidden):
    assert expected <= operations(text)
    assert not forbidden & operations(text)


@pytest.mark.parametrize('text,expected', [
    ('Read the document, then move the file', {'reading'}),
    ('Open the view menu to zoom in', {'menu_open'}),
    ('Open the app menu', {'menu_open'}),
    ('Open the Edit menu', {'menu_open'}),
    ('Open the document then find the Archive window', {'open'}),
    ('I need to zoom in', {'zoom_in'}),
    ('Zoom in to read the text', {'zoom_in'}),
])
def test_explicit_sequence_and_purpose_do_not_compete_by_score(text, expected):
    assert immediate_actions(analyze(text)) == expected


def test_missing_frozen_capability_blocks_all_origins_and_keeps_explicit_gap():
    value = route(instruction='Read the text', proposals=[(3, 'Move the file. <key_lookup>files.move</key_lookup>', 1)])
    assert names(value) == []
    assert any('move' in gap['missing'] for gap in value['coverage_gaps'])
    for card in ('clipboard.paste', 'clipboard.verify'):
        value = route(instruction='Read content', rows=[event(['ctrl', 'v'], instruction='Read content')])
        assert card not in names(value)
    assert any(gap['reason'] == 'capability_not_frozen' for gap in value['coverage_gaps'])


def test_current_need_lookup_and_software_must_agree_before_ranking():
    value = route(instruction='Read then export in GIMP',
                  proposals=[(3, 'Read the document. <key_lookup>gimp.export</key_lookup>', 1)],
                  enabled=['general', 'app.gimp'])
    assert names(value) == ['document.read']
    assert any(e['reason'] == 'operation_mismatch' for e in value['excluded'])
    value = route(instruction='Take a desktop screenshot', enabled=['general', 'app.vlc'])
    assert names(value) == ['capture.image']
    value = route(instruction='Take a desktop screenshot in VLC', enabled=['general', 'app.vlc'])
    assert names(value) == ['capture.image']
    value = route(instruction='Read PDF', proposals=[(3, 'Zoom out', 1)], enabled=['general', 'app.gimp', 'app.evince'])
    assert names(value) == ['view.zoom_out']
    value = route(instruction='Read PDF', proposals=[(3, 'Zoom out in Evince', 1)], enabled=['general', 'app.gimp', 'app.evince'])
    assert names(value)[0] == 'catalog.app.evince.zoom'
    assert [r['intent'] for r in value['groups'][0]['record']['recipes']] == ['zoom out']
    assert 'catalog.app.gimp.zoom' not in names(value)


def test_terminal_is_not_generic_clipboard_and_lookup_is_not_a_bypass():
    value = route(instruction='Copy text from the terminal', proposals=[(3, 'Copy terminal text. <key_lookup>clipboard</key_lookup>', 1)])
    assert names(value) == []
    assert any(e['reason'] == 'terminal_requires_distinct_bindings' for e in value['excluded'])
    value = route(instruction='Copy terminal text', rows=[event(['ctrl', 'c'], instruction='Copy terminal text')])
    assert names(value) == []
    value = route(instruction='Copy the file terminal.txt')
    assert names(value) == ['files.copy']


def test_unmapped_catalog_binding_stays_local_with_explicit_gap():
    value = route(instruction='Read content', proposals=[(3, '<key_lookup>slider_adjust</key_lookup>', 1)])
    assert names(value) == []
    assert any(e['reason'] == 'no_audited_operation_contract' for e in value['coverage_gaps'])
    assert all(not c['record']['recipes'] for c in value['groups'])


def test_old_intent_and_future_task_stage_do_not_compete_with_current_need():
    value = route(instruction='Read the document, then move files')
    assert names(value) == ['document.read']
    value = route(instruction='Read the document, then move files', step=3,
        proposals=[(6, 'Read the content', 2), (3, 'Move the files', 1)])
    assert names(value) == ['document.read']
    assert any(e['reason'] == 'superseded_public_intention' for e in value['excluded'])
    value = route(instruction='Read documents and move files')
    assert names(value) == []
    assert value['coverage_gaps'][0]['reason'] == 'current_phase_unspecified'


def test_eligibility_and_phase_invariant_under_reordering():
    args = dict(instruction='Read content', proposals=[(3, 'Zoom in. <key_lookup>view.zoom_in</key_lookup>', 1)],
                pending_effect={'phase': 'confirm_once', 'refs': [3, 4]})
    first = route(**args)
    assert names(first) == ['view.zoom_confirm']
    reverse = deepcopy(g.LIBRARY)
    reverse['guides'] = dict(reversed(list(reverse['guides'].items())))
    assert route(**args, library=reverse) == first
    # Readability in an earlier view cannot override an explicit window change.
    value = route(instruction='Read the document', proposals=[(3, 'Open the Archive window', 1)],
                  readability={'state': 'readable', 'ref': 1, 'before': 2})
    assert names(value) == ['window.locate']
