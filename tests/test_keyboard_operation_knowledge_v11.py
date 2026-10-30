"""Keyboard references cannot stand in for task/result verification."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as guidance
from kobe_views.guidance_eligibility import GUIDE_OPS
from kobe_views.keyboard_view import record
from test_keyboard_guidance import event, names, route


REMOVED = {'view.zoom_check', 'view.readability', 'clipboard.verify', 'capture.image',
           'export.file', 'image.edit', 'pointer.drag', 'document.read', 'no_match'}


@pytest.mark.parametrize('guide', sorted(REMOVED))
def test_removed_cards_cannot_be_reintroduced_by_explicit_lookup(guide):
    assert guide not in guidance.LIBRARY['guides'] and guide not in GUIDE_OPS
    value = route(instruction='Inspect the result', proposals=[(3, f'<key_lookup>{guide}</key_lookup>', 1)])
    assert value['groups'] == []


@pytest.mark.parametrize('task', ['Read the document', 'Adjust the zoom', 'Take a desktop screenshot',
                                'Export the document', 'Edit the image', 'Drag the object'])
def test_uncovered_operations_do_not_receive_a_generic_substitute(task):
    value = route(instruction=task, enabled=['general'], missing_knowledge='Procedure and parameters')
    assert value['groups'] == value['needed_groups'] == []
    assert value['selection_status'] == 'empty'


@pytest.mark.parametrize('gap', ['Result verification', 'Check the result', 'Inspect the effect',
                               'Validate the outcome', 'Was the operation successful?',
                               '检查结果', '验证效果', '核验任务结果', '核查结果', '验收', '是否完成',
                               'Keyboard binding and result verification'])
def test_verification_is_not_covered_by_operation_steps(gap):
    value = route(instruction='Copy selected text', enabled=['general'], missing_knowledge=gap)
    assert value['groups'] == []
    assert any('result_check' in entry['missing'] for entry in value['coverage_gaps'])


def test_catalog_checks_and_generic_steps_cannot_supply_a_procedure(monkeypatch):
    from kobe_views import keyboard_view
    catalog = deepcopy(keyboard_view.CATALOG)
    catalog['window_switch']['check'] = 'Complete workflow: inspect, verify and check the result.'
    monkeypatch.setattr(keyboard_view, 'CATALOG', catalog)
    assert route(instruction='Switch window', enabled=['general'], missing_knowledge='Procedure')['groups'] == []
    assert route(instruction='Switch window', enabled=['general'], missing_knowledge='Result verification')['groups'] == []
    binding = route(instruction='Switch window', enabled=['general'], missing_knowledge='Exact keyboard binding')
    assert names(binding) == ['catalog.window_switch']
    card = guidance.model_card(binding['groups'][0]['record'])
    assert 'Complete workflow' not in json.dumps(card)
    assert 'when' not in card and 'check' not in card


def test_generic_menu_hint_is_not_a_declared_operation_procedure():
    assert route(instruction='Open the menu', missing_knowledge='Procedure')['groups'] == []
    workflow = route(instruction='Copy selected text', enabled=['general'],
                     missing_knowledge='Complete copy and paste workflow')
    assert names(workflow) == ['clipboard.copy_paste']
    assert workflow['groups'][0]['record']['dependencies'] == [['copy', 'paste']]


def test_a_declared_workflow_can_answer_its_paste_dependency_procedure():
    value = route(instruction='Copy selected text', enabled=['general'], missing_knowledge='The paste procedure')
    assert names(value) == ['clipboard.copy_paste']
    assert value['groups'][0]['gap_coverage']['requirements'] == {'procedure': True}


def test_paste_completion_and_zoom_effect_produce_no_keyboard_verification_card():
    paste = route(rows=[event(['ctrl', 'v'])])
    assert paste['groups'] == [] and paste['workflow']['phase'] == 'completed'
    assert route(instruction='Read the document',
                 pending_effect={'phase': 'inspect_effect', 'refs': [3, 4]})['groups'] == []
    confirm = route(instruction='Read the document',
                    pending_effect={'phase': 'confirm_once', 'refs': [3, 4]})
    assert names(confirm) == ['view.zoom_confirm']
    assert confirm['groups'][0]['record']['recipes'][0]['tool']['keys'] == ['return']


def test_specific_app_actions_survive_and_delivered_cards_have_no_generic_when():
    for task, app, expected in [('Export in GIMP', 'app.gimp', 'gimp.export'),
                                ('Take a snapshot in VLC', 'app.vlc', 'vlc.capture')]:
        value = route(instruction=task, enabled=['general', app], missing_knowledge='Exact keyboard binding')
        assert names(value) == [expected]
        card = guidance.model_card(value['groups'][0]['record'])
        assert 'when' not in card and 'check' not in card and card['recipes']
    legacy = record('clipboard', 'explicit_lookup')
    assert 'check' not in legacy and legacy['recipes']


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
def test_empty_lookup_still_dispatches_native_action_without_a_pseudo_card(monkeypatch, tmp_path, mode):
    from test_decision_flow_v9 import install, query, reply, display
    from test_mini_taskviews import predict
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Drag the object',
        [query('Drag the object'), reply('computer_use', {'action': 'left_click_drag', 'coordinate': [60, 70]})], mode)
    try:
        commands = predict(actor, obs)
        assert commands and len(transport.requests) == 2
        for request in transport.requests:
            packet = display(request)
            assert packet['views']['keyboard'] == {'records': [], 'omitted_records': 0}
            assert 'guidance_status' not in packet['views']['current']['records'][0]
            assert 'no_match' not in json.dumps(request)
        tool_reply = next(m for m in transport.requests[-1]['messages'] if m.get('tool_call_id') == 'knowledge-1')
        assert json.loads(tool_reply['content'])['status'] == 'empty'
    finally:
        actor.close()
