"""Generic public traces: no benchmark objects, answers or model requests."""
from copy import deepcopy

import pytest

from kobe_views.attempt_retrieval import retrieve
from kobe_views.decision_flow import attempt_recall
from kobe_views.operation_support import navigation_recall


class Journal:
    def __init__(self):
        self.rows = []
        self.step = 0
        self.observation = self.add(kind='observation')

    def add(self, **event):
        seq = len(self.rows) + 1
        self.rows.append((seq, {'id': str(seq), 'instruction': 'Arrange documents',
                               'episode_id': 'episode-A', **event}, '1' * 64))
        return seq

    def act(self, text, args, *, failure=False):
        self.step += 1
        source = self.observation
        dec = self.add(kind='decision', source=str(source), local_instruction=text, step=self.step)
        self.observation = self.add(kind='observation')
        return self.add(kind='transition', source=str(source), target=str(self.observation),
                        decision_id=str(dec), step=self.step, tool={'arguments': args},
                        dispatch_observed=True, command_alignment='matched', gaps=[],
                        controller_receipts=[{'result': {'success': not failure,
                            'error': 'Original tool error' if failure else ''}}])

    def query(self, text):
        self.step += 1
        seq = self.add(kind='decision', source=str(self.observation), local_instruction=text, step=self.step)
        return [(seq, text, self.step)]

    def retrieve(self, proposals):
        return retrieve(self.rows, 'Arrange documents', proposals, self.step)


@pytest.mark.parametrize('entry', [attempt_recall, navigation_recall])
@pytest.mark.parametrize('bad', ['source', 'target', 'issuer', 'order', 'episode', 'partial', 'expired'])
def test_both_entrypoints_require_complete_fresh_same_episode_evidence(entry, bad):
    j = Journal()
    old = j.act('Open the Archive window.', {'action': 'left_click', 'coordinate': [20, 30]})
    q = j.query('Open the Archive window again.')
    e = j.rows[old-1][1]
    if bad == 'source':
        e['source'] = 'absent'
    elif bad == 'target':
        e['target'] = 'absent'
    elif bad == 'issuer':
        e['decision_id'] = 'absent'
    elif bad == 'order':
        e['target'] = e['source']
    elif bad == 'episode':
        e['episode_id'] = 'episode-B'
    elif bad == 'partial':
        e['dispatch_observed'] = False
    else:
        e['step'] = -50
    assert entry(j.rows, 'Arrange documents', q, j.step) is None


@pytest.mark.parametrize('entry', [attempt_recall, navigation_recall])
@pytest.mark.parametrize('old,new', [
    ('Open reference alpha.pdf.', 'Open reference beta.pdf again.'),
    ('Open reference panel in GIMP.', 'Open reference panel in Evince again.'),
    ('Open reference "Archive" window.', 'Open reference "Settings" window again.'),
])
def test_known_object_or_software_conflicts_are_not_hidden_by_shared_terms(entry, old, new):
    j = Journal()
    j.act(old, {'action': 'left_click', 'coordinate': [20, 30]})
    assert entry(j.rows, 'Arrange documents', j.query(new), j.step) is None


@pytest.mark.parametrize('entry', [attempt_recall, navigation_recall])
def test_navigation_fallback_cannot_restore_a_phase_superseded_click(entry):
    j = Journal()
    old = j.act('Open the Archive zoom window.', {'action': 'left_click', 'coordinate': [20, 30]})
    j.act('Type the Archive zoom value 200%.', {'action': 'type', 'text': '200'})
    q = j.query('Open the Archive zoom window again.')
    assert entry(j.rows, 'Arrange documents', q, j.step) is None
    assert any(c['ref'] == old and c['reason'] == 'phase_advanced' for c in j.retrieve(q)['audit']['candidates'])


@pytest.mark.parametrize('text', ['Type the zoom value 100%.',
    'I can see the zoom field is selected. Let me type a higher zoom level to read the document clearly.'])
def test_later_zoom_input_replaces_old_value_and_confirmation_completes_input_phase(text):
    j = Journal()
    old = j.act(text, {'action': 'type', 'text': '100'})
    newer = j.act('Type the zoom value 200%.', {'action': 'type', 'text': '200'})
    j.act('Confirm the zoom value.', {'action': 'key', 'keys': ['return']})
    q = j.query('Type the zoom value again.')
    original = deepcopy(j.rows)
    value = j.retrieve(q)
    reasons = {c['ref']: c for c in value['audit']['candidates']}
    assert reasons[old]['reason'] == 'parameters_superseded'
    assert reasons[old]['superseding_ref'] == newer
    assert reasons[newer]['reason'] == 'phase_advanced'
    assert value['selected'] is None and j.rows == original  # Raw actions remain intact.


@pytest.mark.parametrize('query', ['Confirm the zoom value.', 'Read the zoom content.',
                                 'Type the zoom to 200%.', 'Type 200 in the zoom field.'])
def test_old_input_is_not_a_current_confirmation_reading_or_different_value(query):
    j = Journal()
    j.act('Type the zoom value 100%.', {'action': 'type', 'text': '100'})
    assert j.retrieve(j.query(query))['selected'] is None


def test_new_input_in_another_named_object_does_not_replace_the_original_input():
    j = Journal()
    old = j.act('Type the zoom in alpha.pdf to 100%.', {'action': 'type', 'text': '100'})
    j.act('Type the zoom in beta.pdf to 200%.', {'action': 'type', 'text': '200'})
    value = j.retrieve(j.query('Type the zoom in alpha.pdf to 100% again.'))
    assert value['selected']['ref'] == old


def test_failed_later_input_cannot_certify_replacement_of_a_value():
    j = Journal()
    old = j.act('Type the zoom value 100%.', {'action': 'type', 'text': '100'})
    j.act('Type the zoom value 200%.', {'action': 'type', 'text': '200'}, failure=True)
    value = j.retrieve(j.query('Type the zoom value again.'))
    assert next(c for c in value['audit']['candidates'] if c['ref'] == old)['reason'] == 'later_attempt_failed'
    assert value['selected']['purpose'] == 'avoid_repeat'


def test_distinct_named_fields_are_not_the_same_parameter_slot():
    j = Journal()
    old = j.act('Type a value in the reference title field.', {'action': 'type', 'text': 'alpha'})
    j.act('Type a value in the reference total field.', {'action': 'type', 'text': 'beta'})
    value = j.retrieve(j.query('Type a value in the reference title field.'))
    assert value['selected']['ref'] == old


@pytest.mark.parametrize('later', [['ctrl', 'x'], ['ctrl', 'c'], ['ctrl', 'v']])
def test_clipboard_write_or_paste_retires_the_old_pending_copy(later):
    j = Journal()
    old = j.act('Copy reference selection.', {'action': 'key', 'keys': ['ctrl', 'c']})
    j.act('Use the clipboard.', {'action': 'key', 'keys': later})
    value = j.retrieve(j.query('Copy reference selection.'))
    assert value['selected'] is None
    assert any(c['ref'] == old and c['reason'] in ('clipboard_replaced', 'phase_advanced')
               for c in value['audit']['candidates'])


def test_failed_dispatch_is_an_avoidance_reference_not_a_successful_route():
    j = Journal()
    ref = j.act('Open the Archive window.', {'action': 'left_click', 'coordinate': [20, 30]}, failure=True)
    q = j.query('Open the Archive window again.')
    for entry in (attempt_recall, navigation_recall):
        value = entry(j.rows, 'Arrange documents', q, j.step)
        assert value['ref'] == ref and value['purpose'] == 'avoid_repeat'
        assert value['parameters'] == 'historical_only_rebuild_current'
        assert 'not_success' in value['basis']


def test_private_reasoning_empty_query_and_unbound_proposals_never_start_retrieval():
    j = Journal()
    j.act('Open the Archive window.', {'action': 'left_click', 'coordinate': [20, 30]})
    q = j.query('')
    j.rows[q[0][0]-1][1]['response'] = '{"content":"","reasoning_content":"Open the Archive window again."}'
    assert j.retrieve(q)['selected'] is None
    assert j.retrieve([(q[0][0], 'Open the Archive window again.', j.step)])['selected'] is None


def test_results_and_rejection_audit_are_deterministic_under_row_order():
    j = Journal()
    j.act('Open the Archive window.', {'action': 'left_click', 'coordinate': [20, 30]})
    q = j.query('Open the Archive window again.')
    value = j.retrieve(q)
    assert value == retrieve(list(reversed(j.rows)), 'Arrange documents', q, j.step)


def test_a_ui_state_report_alone_does_not_become_an_action_request():
    j = Journal()
    j.act('Type the zoom value 100%.', {'action': 'type', 'text': '100'})
    value = j.retrieve(j.query('The zoom is now 100%.'))
    assert value['selected'] is None and value['audit']['reason'] == 'no_public_operation'


@pytest.mark.parametrize('mode', ['legacy', 'flat'])
@pytest.mark.parametrize('failed', [False, True])
@pytest.mark.parametrize('tiny', [False, True])
def test_actual_wire_recall_without_keyboard_query_and_no_navigation_bypass(monkeypatch, tmp_path, mode, failed, tiny):
    import test_mini_taskviews as native
    import kobe_views.operation_support as support
    from test_decision_flow_v9 import display, install, reply
    replies = [reply('computer_use', {'action': 'key', 'keys': ['ctrl', 'c']}, 'Copy reference selection.')]
    replies += [reply('computer_use', {'action': 'left_click', 'coordinate': [100+i, 200]}, '', str(i))
                for i in range(4)]
    replies += [reply('computer_use', {'action': 'screenshot'}, 'Copy reference selection.'),
                reply('computer_use', {'action': 'right_click', 'coordinate': [20, 30]})]
    actor, obs, transport, _ = install(monkeypatch, tmp_path, 'Copy selected text in reference panel.', replies, mode, tiny=tiny)
    # Even a bad legacy source cannot bypass the single native eligibility gate.
    monkeypatch.setattr(support, 'navigation_recall', lambda *a, **k: {'ref': 999999})
    try:
        native.predict(actor, obs, error='Original tool failure' if failed else None)
        for _ in replies[1:]:
            native.predict(actor, obs)
        trace = actor.mini_context.trace['attempt_retrieval']
        assert len(transport.requests) == actor.total_steps == len(replies)
        assert not [e for e in actor.execution_journal.read() if e['kind'] == 'knowledge_query']
        if tiny:
            assert trace['selected_ref'] is not None and not trace['in_packet_refs'] and not trace['delivered']
            assert trace['delivery_status'] not in ('pending', 'packaged', 'delivered')
            return
        packet = display(transport.requests[-1])
        records = [r for r in packet['views']['attempts']['records'] if r.get('recall')]
        assert len(records) == 1 and 'strategy' not in packet['views']['current']['records'][0]
        assert records[0]['recall']['purpose'] == ('avoid_repeat' if failed else 'procedure_reference')
        assert records[0]['effect_status'] == 'unknown'
        assert 'tool' in records[0]  # Original action facts are not rewritten.
        assert trace['selected_ref'] == records[0]['ref']
        assert trace['in_packet_refs'] == [records[0]['ref']] and trace['delivered']
        assert trace['delivery_status'] == 'delivered'
        saved = actor.checkpoint_state()
        saved['mini_guidance']['decision_flow']['attempt_retrieval']['version'] = 'old-retrieval'
        from ui_kobe.osworld.checkpoints import ReadAnomaly
        with pytest.raises(ReadAnomaly, match='guidance cannot be switched'):
            actor.restore_checkpoint_state(saved)
    finally:
        actor.close()


def test_whole_recall_precedes_keyboard_even_without_strategy_and_cannot_expand_budget():
    from kobe_views import mini_graph
    from kobe_views.guidance_delivery import materialize
    from kobe_views.keyboard_selection import task_keyboard_policy
    from kobe_views.model import dumps
    from kobe_views.review_presentation import schema
    from test_keyboard_guidance import route
    selection = route(instruction='Copy files', observation_ref=11)
    policy = task_keyboard_policy({'instruction': 'Copy files'}, mode='task_capabilities')['mini_guidance']
    records = [{'ref': 8, 'grade': 'execution_attempt', 'before': 6, 'after': 7,
                'tool': {'arguments': {'action': 'left_click', 'coordinate': [40, 50]}},
                'effect_status': 'unknown', 'receipt': 'returned'},
               {'ref': 4, 'grade': 'execution_attempt', 'before': 1, 'after': 3,
                'tool': {'arguments': {'action': 'key', 'keys': ['ctrl', 'c']}},
                'effect_status': 'unknown', 'receipt': 'returned',
                'recall': {'query': {'ref': 10}, 'purpose': 'procedure_reference',
                           'parameters': 'historical_only_rebuild_current'}}]
    args = dict(episode_id='test', index=None, instruction='Copy files', graph_mode='legacy',
        packing=mini_graph.PACKING, frame_id='frame', current={'ref': 11, 'grade': 'original_input',
            'artifact': {'grade': 'unverified', 'verification': {}, 'review_schema': schema(policy)}},
        attempts=records, lessons=[], totals={'attempts': 2, 'lessons': 0},
        sources={str(n): {'kind': 'observation' if n in (1, 3, 6, 7, 11) else 'decision' if n == 10 else 'transition'}
                 for n in (1, 3, 4, 6, 7, 8, 10, 11)}, review_policy=policy)
    empty = {**selection, 'groups': [], 'coverage_gaps': []}
    baseline = materialize(selection=empty, max_bytes=3000, **args)
    limit = len(dumps(baseline).encode()) + 160
    packet = materialize(selection=selection, max_bytes=limit, **args)
    assert len(dumps(packet).encode()) <= limit <= 3000
    assert any(r.get('recall') for r in packet['views']['attempts']['records'])
    assert packet['views']['keyboard']['records'] == []  # Whole card omitted, not a prefix slice.
    assert packet['views']['attempts']['omitted_records'] == 0
    for budget in (0, 64, 128, limit - 200):
        small = materialize(selection=selection, max_bytes=budget, **args)
        assert small is None or len(dumps(small).encode()) <= budget
        if small:
            assert not any(r.get('recall') for r in small['views']['attempts']['records'])
            assert small['views']['attempts']['omitted_records'] == 1
