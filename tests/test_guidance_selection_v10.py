"""Layered rules on generic operation demands; no benchmark objects or answers."""
from copy import deepcopy
import json

import pytest

from kobe_views import keyboard_guidance as g, guidance_selection as rules
from test_keyboard_guidance import event, names, route


def selected(value):
    return value['groups'][0]


def test_candidates_use_named_criteria_without_numeric_priorities():
    value = route(instruction='Export in GIMP', enabled=['general', 'app.gimp'])
    assert names(value)[0] == 'gimp.export'
    assert all('score' not in c and set(c['criteria']) == set(rules.LAYERS) for c in value['groups'])
    why = value['selection_explanation']
    assert why['winner_criteria']['software_object'] == 'explicit_application'
    assert why['comparisons'][0]['deciding_layer'] == 'software_object'
    assert rules.policy()['numeric_priorities'] is False


def test_frozen_layer_policy_roundtrips_json_without_relaxing_validation():
    from kobe_views.keyboard_selection import task_keyboard_policy
    policy = task_keyboard_policy({'instruction': 'Read the content'}, mode='task_capabilities')['mini_guidance']
    tools = [t for t in policy['enabled_toolsets'] if t != 'general']
    loaded = json.loads(json.dumps(policy))
    assert policy == loaded
    g.validate(loaded, tools)
    loaded['selection']['branches']['intent_match'].reverse()
    with pytest.raises(ValueError, match='frozen policy'):
        g.validate(loaded, tools)


def test_explicit_reference_is_an_intent_choice_and_cannot_override_eligibility():
    kwargs = {'instruction': 'Export in GIMP', 'enabled': ['general', 'app.gimp'],
              'proposals': [(3, 'Export in GIMP <key_lookup>export.file</key_lookup>', 1)]}
    value = route(**kwargs)
    assert names(value)[0] == 'export.file'
    assert value['selection_explanation']['comparisons'][0]['deciding_layer'] == 'intent_match'
    # An explicitly requested card that lacks the needed binding is still rejected.
    value = route(**kwargs, missing_knowledge='Exact export keyboard shortcut')
    assert names(value)[0] == 'gimp.export'
    assert any(c['reason'] == 'knowledge_gap_not_covered' for c in value['excluded'])
    assert not any(gap['reason'] == 'knowledge_gap_not_covered' for gap in value['coverage_gaps'])


@pytest.mark.parametrize('gap,expected', [
    (None, 'clipboard.copy'), ('Exact copy binding', 'clipboard.copy'),
    ('Complete copy and paste workflow', 'clipboard.copy_paste'),
    ('Copy and paste keyboard shortcuts and procedure', 'clipboard.copy_paste'),
])
def test_current_operation_can_request_its_complete_followup_group(gap, expected):
    value = route(instruction='Copy selected text', enabled=['general'], missing_knowledge=gap)
    assert names(value)[0] == expected
    if expected.endswith('copy_paste'):
        assert selected(value)['record']['dependencies'] == [['copy', 'paste']]
        assert selected(value)['criteria']['knowledge_gap'] == 'fully_covered'


def test_detailed_gap_is_a_filter_not_permission_to_expand_frozen_capabilities():
    value = route(instruction='Copy selected text', enabled=['general'],
                  missing_knowledge='Cut and paste keyboard shortcuts')
    assert names(value) == []
    assert any(x['reason'] == 'knowledge_gap_not_covered' for x in value['coverage_gaps'])


@pytest.mark.parametrize('gap,matched', [
    ('Exact keyboard binding for editing the image', False),
    ('The procedure for editing the image', True),
    ('A binding or procedure for editing the image', True),
])
def test_unrelated_undo_binding_does_not_fill_an_image_edit_binding_gap(gap, matched):
    value = route(instruction='Edit the image', missing_knowledge=gap)
    assert bool(value['groups']) == matched
    if matched:
        assert names(value)[0] == 'image.edit'


@pytest.mark.parametrize('gap,matched', [
    ('Exact keyboard shortcut for dragging', False),
    ('Procedure and parameters for dragging', True),
    ('Keyboard binding or applicable procedure', True),
])
def test_procedure_can_be_useful_without_a_binding_but_not_when_a_binding_is_required(gap, matched):
    value = route(instruction='Drag the object', missing_knowledge=gap)
    assert bool(value['groups']) == matched
    if matched:
        assert selected(value)['record']['recipes'] == []


def test_app_directory_alone_is_not_an_application_match():
    value = route(instruction='Export the document', enabled=['general', 'app.gimp'])
    assert names(value) == ['export.file']
    value = route(instruction='Export the document', enabled=['general', 'app.gimp'],
                  missing_knowledge='Exact export keyboard binding')
    assert names(value) == []  # No invented GIMP shortcut from an enabled directory.


@pytest.mark.parametrize('phase,name', [('confirm_once', 'view.zoom_confirm'), ('inspect_effect', 'view.zoom_check')])
def test_phase_is_a_gate_before_explicit_reference_or_scope(phase, name):
    value = route(instruction='Read content', proposals=[(3, 'Zoom in <key_lookup>view.zoom_in</key_lookup>', 1)],
                  pending_effect={'phase': phase, 'refs': [3, 4]})
    assert names(value) == [name]
    assert selected(value)['criteria']['phase'] == 'current_stage'
    assert value['selection_explanation']['phase']['kind'] == 'zoom_' + phase
    assert value['selection_explanation']['phase']['effect_status'] == 'unknown'


def test_readability_conflict_has_one_named_branch_and_preserves_proposal_grade():
    value = route(instruction='Read the document', proposals=[(3, 'Read the document', 1)],
        pending_effect={'phase': 'inspect_effect', 'refs': [3, 4]},
        readability={'state': 'readable', 'ref': 3, 'before': 2})
    assert names(value) == ['document.read']
    assert selected(value)['origins'] == ['public_proposal', 'public_readability_report_unverified']
    assert {'ref': 2} in selected(value)['record']['evidence']
    assert value['selection_explanation']['phase']['kind'] == 'readable_report'
    assert value['selection_explanation']['phase']['readability_is'] == 'unverified_public_report'


def test_explicit_destination_action_precedes_pending_paste_without_a_threshold():
    value = route(rows=[event(['ctrl', 'c'])], proposals=[(3, 'Type the destination path', 1)])
    assert names(value)[0] == 'text.edit'
    assert selected(value)['criteria']['phase'] == 'current_prerequisite'
    assert next(c for c in value['groups'] if c['record']['guide_id'].startswith('clipboard.paste:'))['criteria']['phase'] == 'pending_continuation'
    value = route(rows=[event(['ctrl', 'v'])], proposals=[(3, 'Type the destination path', 1)])
    assert names(value)[0] == 'clipboard.verify'
    assert selected(value)['criteria']['phase'] == 'post_action_check'


@pytest.mark.parametrize('kind', ['pending_effect', 'readability', 'adjustment_chain'])
def test_expired_source_state_is_filtered_before_phase_selection(kind):
    record = {'refs': [3], 'ref': 3, 'before': 2, 'evidence': [{'ref': 3}],
              'phase': 'confirm_once', 'state': 'readable', 'expires_step': 1}
    value = route(instruction='Read content', **{kind: record})
    assert names(value) == ['document.read']
    assert any(c['reason'] == 'expired_or_outside_task_state' for c in value['excluded'])


def test_unknown_gap_is_not_reported_as_proven_coverage():
    value = route(instruction='Copy selected text', enabled=['general'], missing_knowledge='Some contextual assistance')
    assert selected(value)['criteria']['knowledge_gap'] == 'unspecified'
    assert value['need_basis'] == 'deterministic_router_estimate_not_ground_truth'


def test_or_gap_reports_which_alternative_is_available_without_inventing_a_binding():
    value = route(instruction='Drag the object', missing_knowledge='A keyboard binding or procedure')
    assert selected(value)['criteria']['knowledge_gap'] == 'alternative_covered'
    assert selected(value)['gap_coverage']['requirements'] == {'binding': False, 'procedure': True}


def test_uncovered_workflow_does_not_become_proven_by_a_steps_field_alone():
    value = route(instruction='Copy selected text', enabled=['general'], missing_knowledge='Complete workflow')
    assert names(value)[0] == 'clipboard.copy_paste'
    # Known dependent workflow is available, instead of calling a lone Copy a full process.
    assert selected(value)['contract']['workflow'] is True


def test_malformed_selection_branch_is_not_silently_dropped():
    rows = deepcopy(route()['groups'])
    rows[0]['criteria']['phase'] = 'unknown_rule'
    with pytest.raises(ValueError, match='Unknown guidance selection branch'):
        rules.partition_order(rows)


def test_library_reordering_preserves_all_decisions_and_explanations():
    kwargs = {'instruction': 'Copy selected text', 'enabled': ['general'],
              'missing_knowledge': 'Complete copy and paste workflow'}
    value = route(**kwargs)
    library = deepcopy(g.LIBRARY)
    for key in ('guides', 'bindings', 'sources'):
        library[key] = dict(reversed(list(library[key].items())))
    assert route(**kwargs, library=library) == value


def test_stable_id_is_the_last_rule_not_directory_order():
    value = route(instruction='Export in GIMP', enabled=['general', 'app.gimp'])
    rows = deepcopy(value['groups'])
    for c in rows:
        c['criteria'] = {k: rules.BRANCHES[k][-1] for k in rules.LAYERS}
    assert [c['record']['guide_id'] for c in rules.partition_order(rows)] == sorted(c['record']['guide_id'] for c in rows)
    assert rules.partition_order(list(reversed(rows))) == rules.partition_order(rows)


@pytest.mark.parametrize('mode', ['legacy', 'flat', 'linked'])
def test_real_query_uses_missing_knowledge_in_the_current_request(monkeypatch, tmp_path, mode):
    from test_decision_flow_v9 import install, query, reply, display
    import test_mini_taskviews as native
    lookup = query('Copy selected text')
    lookup['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps({
        'intent': 'Copy selected text', 'missing_knowledge': 'Complete copy and paste workflow'})
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text',
        [lookup, reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})], mode)
    try:
        native.predict(actor, obs)
        first, after = (display(r) for r in transport.requests)
        assert first['views']['keyboard']['records'][0]['guide_id'].startswith('clipboard.copy:')
        assert after['views']['keyboard']['records'][0]['guide_id'].startswith('clipboard.copy_paste:')
        assert len(transport.requests) == 2 and actor.total_steps == 1
        assert len(transport.requests[-1]['messages'][-1]['content'][-1]['text'].split('\n', 1)[1].encode()) <= 3000
        assert all('criteria' not in r for r in after['views']['keyboard']['records'])
        saved = actor.checkpoint_state()
        actor.restore_checkpoint_state(saved)
        saved['mini_guidance']['version'] = 'capability_guidance_v9'
        with pytest.raises(Exception, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(saved)
    finally:
        actor.close()
