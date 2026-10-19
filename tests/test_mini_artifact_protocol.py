"""Public-report protocol regressions; all responses and GUI receipts are synthetic."""
from copy import deepcopy
import json
import re

import pytest

from kobe_views import artifact_view as artifact
from kobe_views.fixed_views import MAX_BYTES, materialize
from kobe_views.model import dumps
from ui_kobe.api.kimi_stream import Completion
from test_mini_taskviews import make_actor, packet, predict


def report(ref=1, **changes):
    value = {'applicable': True, 'candidate': '/work/result.ext', 'checks': {
        key: {'ref': ref, 'observed': 'Synthetic visible fact'} for key in artifact.CHECKS}}
    value.update(changes)
    return value


def request_packet(request):
    text = next(p['text'] for p in request['messages'][-1]['content']
                if p.get('text', '').startswith('TaskViews:'))
    return json.loads(text.split('\n', 1)[1])


def annotate(transport, content, reasoning_chars=0):
    original = transport.create
    def create(**request):
        body = original(**request).model_dump()
        message = body['choices'][0]['message']
        message['content'] = content(request, len(transport.requests))
        message['reasoning_content'] = 'x' * reasoning_chars
        return Completion(body)
    transport.create = create


def test_complete_examples_and_limits_share_the_validator_contract(monkeypatch):
    # A changed limit must update guidance and actual acceptance, not just docs.
    monkeypatch.setattr(artifact, 'MAX_OBSERVED_CHARS', 17)
    schema = artifact.review_schema()
    assert 'observed 1..17 chars' in schema
    blocks = re.findall(r'<artifact_review>.*?</artifact_review>', schema)
    assert len(blocks) == 2
    example, no_file = [artifact.validate_review(block, final=True) for block in blocks]
    assert tuple(example['checks']) == artifact.CHECKS
    assert no_file == {'applicable': False, 'reason': 'WHY'}
    assert 'assistant.content' in schema and 'not reasoning/tool args' in schema
    assert 'content_previewed[0]=current.ref' in schema
    assert 'ALL example values' in schema and 'No-file tasks only' in schema
    value = report()
    with pytest.raises(artifact.ReviewError, match='allowed 1..17'):
        artifact.validate_review(artifact.tagged_review(value), final=True)


@pytest.mark.parametrize('text,code', [
    (None, 'missing_tag'), ('Task completed.', 'missing_tag'),
    ('<artifact_review>{}</artifact_review><artifact_review>', 'tag_count'),
    (artifact.tagged_review(report()).replace('}}}</artifact_review>', '}}</artifact_review>'), 'invalid_json'),
])
def test_distinct_format_failures_are_not_collapsed(text, code):
    with pytest.raises(artifact.ReviewError) as error:
        artifact.validate_review(text, final=True)
    assert error.value.code == code
    assert artifact.parse_review(text) is None


def test_three_step10_length_errors_are_reported_together_without_original_prose():
    value = report()
    for key, size in zip(artifact.CHECKS, (262, 251, 141, 189)):
        value['checks'][key]['observed'] = 'x' * size
    text = artifact.tagged_review(value)
    with pytest.raises(artifact.ReviewError) as error:
        artifact.validate_review(text, final=True)
    detail = str(error.value)
    for key, size in (('source_confirmed', 262), ('content_previewed', 251), ('destination_confirmed', 189)):
        assert f'{key}.observed: {size} chars; allowed 1..160' in detail
    assert 'name_correct' not in detail and 'x' * 20 not in detail
    assert len(detail) < 500 and text == artifact.tagged_review(value)


@pytest.mark.parametrize('length,accepted', [(160, True), (161, False)])
def test_observed_limit_counts_characters_not_utf8_bytes(length, accepted):
    value = report()
    value['checks']['source_confirmed']['observed'] = '图' * length
    text = artifact.tagged_review(value)
    assert (artifact.parse_review(text) is not None) is accepted


def test_total_json_utf8_limit_is_enforced_separately():
    value = report(candidate='图' * 300)
    for check in value['checks'].values():
        check['observed'] = '图' * 160
    with pytest.raises(artifact.ReviewError) as error:
        artifact.validate_review(artifact.tagged_review(value))
    assert error.value.code == 'report_bytes' and 'UTF8 bytes' in str(error.value)


def test_partial_history_is_not_sufficient_for_success_and_claims_are_not_certified():
    value = report(checks={'name_correct': {'ref': 1, 'observed': 'Synthetic name'}})
    text = artifact.tagged_review(value)
    assert artifact.parse_review(text) == value
    with pytest.raises(artifact.ReviewError, match='checks missing:'):
        artifact.validate_review(text, final=True)
    value['checks']['name_correct']['ref'] = True
    assert artifact.parse_review(artifact.tagged_review(value)) is None
    assert artifact.unknown_checks() == dict.fromkeys(artifact.CHECKS, 'unknown')


def test_first_success_uses_actual_prompt_template_without_a_repair(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}])
    def from_prompt(request, attempt):
        current = request_packet(request)['views']['current']['records'][0]
        schema = current['artifact']['review_schema']
        example = json.loads(re.findall(r'<artifact_review>(.*?)</artifact_review>', schema)[0])
        example['candidate'] = '/work/synthetic.ext'
        for key in artifact.CHECKS:
            example[key] = [current['ref'], 'Synthetic fixture evidence']
        assert current['artifact']['verification'] == artifact.unknown_checks()
        return artifact.tagged_review(example)
    annotate(transport, from_prompt, reasoning_chars=16939)
    assert predict(actor, obs) == ['DONE']
    assert len(transport.requests) == 1 and actor.total_steps == 1
    assert actor.last_trace['step_tokens']['semantic_regenerations'] == 0
    assert actor.mini_context.trace['artifact_protocol_in_packet'] and actor.mini_context.trace['delivered']
    assert packet(transport)['views']['current']['records'][0]['artifact']['verification'] == artifact.unknown_checks()
    actor.close()


@pytest.mark.parametrize('failure,expected', [('missing_tag', 'missing_tag'), ('invalid_json', 'invalid_json'),
                                          ('too_long', 'observed: 161 chars; allowed 1..160')])
def test_mini_report_feedback_is_separate_from_native_tool_repair(monkeypatch, tmp_path, failure, expected):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}] * 2)
    def content(request, attempt):
        value = report(request_packet(request)['views']['current']['records'][0]['ref'])
        if attempt == 1:
            if failure == 'missing_tag':
                return 'Task completed.'
            if failure == 'invalid_json':
                return artifact.tagged_review(value).replace('}}}</artifact_review>', '}}</artifact_review>')
            value['checks']['name_correct']['observed'] = 'x' * 161
        return artifact.tagged_review(value)
    annotate(transport, content)
    assert predict(actor, obs) == ['DONE']
    assert len(transport.requests) == 2 and actor.total_steps == 1
    repair = transport.requests[1]['messages']
    assert not any(m.get('tool_call_id') == 'original-1' or m.get('role') == 'assistant' for m in repair)
    feedback = next(p['text'] for m in repair if m.get('role') == 'user' and isinstance(m.get('content'), list)
                    for p in m['content'] if 'Mini auxiliary report rejected' in p.get('text', ''))
    assert expected in feedback and 'Correct assistant.content' in feedback
    assert actor.last_trace['mini_recovery']['report_rejections'] == 1
    assert actor.last_trace['mini_recovery']['native_rejections'] == 0
    assert actor.pending == 'original-2' and actor.contract.tool_repair_retries == 2
    assert actor.execution_journal.position == 1  # Only the accepted DONE was dispatched by the fixture.
    actor.close()


@pytest.mark.parametrize('which', ['unknown', 'decision', 'old'])
def test_reference_errors_identify_the_field_without_inventing_evidence(monkeypatch, tmp_path, which):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    old = packet(transport)['views']['current']['records'][0]['ref']
    predict(actor, obs)
    current = packet(transport)['views']['current']['records'][0]['ref']
    value = report(current)
    value['checks']['content_previewed']['ref'] = (10**100 if which == 'unknown' else old if which == 'old' else
        actor.execution_journal.db.execute("SELECT seq FROM events WHERE json_extract(payload,'$.kind')='decision' LIMIT 1").fetchone()[0])
    with pytest.raises(artifact.ReviewError) as error:
        actor.mini_context.validate_review_references(value, final=True)
    assert error.value.code == ('stale_preview' if which == 'old' else 'invalid_reference')
    assert 'content_previewed.ref' in str(error.value)
    actor.close()


def test_large_bad_report_does_not_replay_reasoning_into_native_repair(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'terminate', 'status': 'success'}] * 2)
    annotate(transport, lambda request, attempt: 'No tagged report' if attempt == 1 else artifact.tagged_review(
        report(request_packet(request)['views']['current']['records'][0]['ref'])), reasoning_chars=33000)
    assert predict(actor, obs) == ['DONE']
    assert len(transport.requests) == 2 and actor.contract.context_max_text_chars == 32000
    assert not any('reasoning_content' in message for message in transport.requests[1]['messages'])
    actor.close()


def test_protocol_and_active_evidence_precede_optional_reminders_at_3000_bytes():
    current = {'ref': 55, 'artifact': {'verification': artifact.unknown_checks(), 'grade': 'unverified',
               'review_schema': artifact.REVIEW_SCHEMA},
               'grade': 'original_input', 'image_source': 'current_native_message',
               'interaction_contract': {'optional': 'x'*1200}, 'keyboard_lookup': {'optional': 'x'*1200}}
    operation = {'ref': 54, 'grade': 'execution_attempt', 'tool': {'id': 'synthetic-call',
                 'arguments': {'action': 'double_click', 'coordinate': [500, 500]}},
                 'before': 50, 'after': 55, 'effect_status': 'unknown', 'receipt': 'returned'}
    lessons = [{'grade': 'artifact_verification_state', 'current_ref': 55, 'verification': artifact.unknown_checks()},
               {'grade': 'model_intent_proposal', 'ref': 52, 'text': 'x'*180}]
    sources = {str(ref): {'sha256': str(ref)[0]*64, 'kind': kind} for ref, kind in
               [(50, 'observation'), (55, 'observation'), (54, 'transition'), (52, 'decision')]}
    original = deepcopy(current)
    value = materialize(episode_id='e'*32, frame_id='native-frame-0010', current=current,
        attempts=[operation], lessons=lessons, totals={'attempts': 9, 'lessons': 10}, sources=sources, max_bytes=3000)
    assert current == original and len(dumps(value).encode()) <= MAX_BYTES == 3000
    assert value['views']['attempts']['records'] == [operation]
    retained = value['views']['current']['records'][0]
    assert retained['artifact'] == current['artifact'] and retained['interaction_contract_omitted']
    assert value['views']['lessons']['records'][0] == lessons[0]
    assert all(value['sources'][ref] == sources[ref] for ref in ('50', '54', '55'))
    assert 'keyboard_lookup' not in retained
