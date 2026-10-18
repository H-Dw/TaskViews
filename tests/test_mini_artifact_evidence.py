"""Offline artifact/source and budget regressions; no model, guest or evaluator."""
from copy import deepcopy
import json

import pytest

from kobe_views.artifact_view import CHECKS, parse_review, unknown_checks
from kobe_views.fixed_views import MAX_BYTES, REVISION
from kobe_views.keyboard_view import CATALOG, select_topic
from ui_kobe.api.kimi_stream import Completion, StreamProtocolError
from ui_kobe.osworld.qwen_native_base import QwenNativeAgent
from test_mini_taskviews import TASK, make_actor, original_event, packet, predict


def annotate(transport, text):
    original = transport.create
    def create(**request):
        body = original(**request).model_dump()
        body['choices'][0]['message']['content'] = text(request)
        return Completion(body)
    transport.create = create


def current_ref(request):
    text = request['messages'][-1]['content'][-1]['text']
    return json.loads(text.split('\n', 1)[1])['views']['current']['records'][0]['ref']


def review(ref, **changes):
    value = {'applicable': True, 'candidate': '/work/final-report.svg', 'checks': {
        key: {'ref': ref, 'observed': 'Visible ' + key.replace('_', ' ')} for key in CHECKS}}
    value.update(changes)
    return '<artifact_review>' + json.dumps(value) + '</artifact_review>'


@pytest.mark.parametrize('text', [
    'Everything is confirmed and verified.', '<artifact_review>{"confirmed":true}</artifact_review>',
    review(2).replace('"ref": 2', '"ref": true'), review(2) + review(2),
    review(2, verified=True), review(2, candidate=''),
])
def test_plain_confirmation_and_untyped_or_forged_truth_are_not_reviews(text):
    assert parse_review(text) is None


def test_model_review_never_upgrades_unknown_checks_in_prompt(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    annotate(transport, lambda request: review(current_ref(request)))
    predict(actor, obs)
    decision_id = actor.execution_journal.decision['id']
    predict(actor, obs)
    value = packet(transport)
    current = value['views']['current']['records'][0]
    assert current['artifact']['verification'] == unknown_checks()
    assert current['artifact']['candidate_reported'] == '/work/final-report.svg'
    rows = value['views']['lessons']['records']
    note = next(row for row in rows if row['grade'] == 'model_artifact_review')
    assert original_event(actor, value, note)['id'] == decision_id
    assert note['verification'] == unknown_checks()
    assert set(note['report']['checks']) == set(CHECKS)
    assert all(value['sources'][str(c['ref'])]['kind'] == 'observation' for c in note['report']['checks'].values())
    actor.close()


def test_active_operation_and_followup_survive_more_than_four_passive_calls(monkeypatch, tmp_path):
    click = {'action': 'left_click', 'coordinate': [710, 201]}
    passive = [{'action': 'screenshot'}, {'action': 'wait'}] * 4
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[click, *passive, click])
    for _ in range(10):
        predict(actor, obs)
    value = packet(transport)
    attempts = value['views']['attempts']['records']
    assert len(attempts) == 1 and attempts[0]['tool']['arguments'] == click
    event = original_event(actor, value, attempts[0])
    assert event['step'] == 1 and attempts[0]['effect_status'] == 'unknown'
    assert original_event(actor, value, {'ref': attempts[0]['after']})['id'] == event['target']
    followup = original_event(actor, value, attempts[0]['followup'])
    assert followup['step'] == 9 and followup['tool']['arguments']['action'] == 'wait'
    assert original_event(actor, value, {'ref': attempts[0]['followup']['after']})['id'] == followup['target']
    assert actor.mini_context.trace['selected_operations'] == [click]
    assert len(actor.mini_context.cached.encode()) <= MAX_BYTES == 3000
    assert not value['views']['keyboard']['records']
    actor.close()


def test_bare_success_is_rejected_before_dispatch_and_repairs_in_original_pool(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}] * 2)
    annotate(transport, lambda request: 'confirmed' if len(transport.requests)==1 else
        '<artifact_review>{"applicable":false,"reason":"This task changes a setting without creating a file"}</artifact_review>')
    assert predict(actor, obs) == ['DONE']
    assert len(transport.requests) == 2 and actor.total_steps == 1
    assert actor.last_trace['step_tokens']['semantic_regenerations'] == 1
    assert actor.contract.tool_repair_retries == 2
    assert any(m.get('tool_call_id') == 'original-1' and 'review' in m.get('content', '').lower()
               for m in transport.requests[-1]['messages'])
    actor.close()


def test_current_content_review_allows_success_without_claiming_certification(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}])
    annotate(transport, lambda request: review(current_ref(request)))
    assert predict(actor, obs) == ['DONE']
    assert packet(transport)['views']['current']['records'][0]['artifact']['verification'] == unknown_checks()
    assert len(transport.requests) == 1
    actor.close()


@pytest.mark.parametrize('bad_reference', [999999, 'old'])
def test_missing_or_stale_content_review_cannot_terminate_success(monkeypatch, tmp_path, bad_reference):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'left_click'}] + [{'action': 'terminate', 'status': 'success'}]*3)
    predict(actor, obs)
    old = packet(transport)['views']['current']['records'][0]['ref']
    annotate(transport, lambda request: review(old if bad_reference=='old' else bad_reference))
    with pytest.raises(StreamProtocolError):
        predict(actor, obs)
    assert actor.execution_journal.decision is None and actor.executions == []
    assert actor.total_steps == 2 and len(transport.requests) == 4
    actor.close()


def test_changed_task_cannot_reuse_old_artifact_review(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    annotate(transport, lambda request: review(current_ref(request)))
    predict(actor, obs)
    old_ref = packet(transport)['views']['current']['records'][0]['ref']
    actor.flush_execution()
    actor.execution_journal.begin('A different task', obs, step=2)
    with pytest.raises(ValueError, match='different task'):
        actor.mini_context.validate_review_references(parse_review(review(old_ref)), final=False)
    actor.close()


def test_failure_and_baseline_success_keep_original_native_policy(monkeypatch, tmp_path):
    actor, obs, _ = make_actor(monkeypatch, tmp_path/'mini', actions=[{'action':'terminate','status':'failure'}])
    assert predict(actor, obs) == ['FAIL']
    actor.close()
    baseline, obs, transport = make_actor(monkeypatch, tmp_path/'baseline', cls=QwenNativeAgent,
        actions=[{'action':'terminate','status':'success'}])
    assert baseline.predict(TASK, obs)[1] == ['DONE']
    assert not any('artifact_review' in str(message) for message in transport.requests[0]['messages'])
    baseline.close()


@pytest.mark.parametrize('text', ['Observe the current image.', 'The folder is open.', 'The window is visible.', ''])
def test_no_concrete_operation_omits_keyboard_instead_of_guessing(text):
    assert select_topic([text, 'Maximize the window']) == (None, 'no_matching_intent')


def test_rename_reference_explains_selection_and_extension_once():
    from kobe_views.keyboard_view import record
    topic, reason = select_topic(['<key_lookup>type.file_manager.rename</key_lookup>'], ['type.file_manager'])
    value = record(topic, reason, toolsets=['type.file_manager'])
    assert 'basename' in value['scope'] and 'extension exactly once' in value['check']
    assert 'window_switch' in CATALOG and 'window_maximize' not in CATALOG and 'rename' not in CATALOG


def test_old_checkpoint_does_not_gain_new_review_semantics(monkeypatch, tmp_path):
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    state = deepcopy(actor.checkpoint_state())
    assert state['contract']['implementation_revision'] == REVISION == 'mini_artifact_protocol_v6'
    state['contract']['implementation_revision'] = 'mini_keyboard_memory_v3'
    from ui_kobe.osworld.checkpoints import ReadAnomaly
    with pytest.raises(ReadAnomaly):
        actor.restore_checkpoint_state(state)
    actor.close()
