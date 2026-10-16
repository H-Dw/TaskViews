from copy import deepcopy
import hashlib
import json

import pytest

from kobe_views.fixed_views import materialize
from kobe_views.controls_view import record
from ui_kobe.osworld.checkpoints import ReadAnomaly
from test_mini_controls_view import enable
from test_mini_taskviews import make_actor, packet, predict


def last_attempts(actor):
    return actor.mini_context.read("SELECT seq,id,payload FROM events WHERE json_extract(payload,'$.kind')='transition' ORDER BY seq DESC LIMIT 4")


def test_repeat_feedback_delivered_with_original_commands_sources_and_unknown_effect(monkeypatch, tmp_path):
    enable(monkeypatch)
    action = {'action': 'left_click', 'coordinate': [400, 200]}
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[action] * 5)
    for _ in range(5):
        assert predict(actor, obs) == ['pyautogui.click(400, 200)']
    value = packet(transport)
    feedback = value['views']['current']['records'][0]['recent_repetition']
    assert feedback['repeat_count'] == feedback['same_image_count'] == 4
    assert feedback['effect_status'] == 'unknown' and feedback['grade'] == 'literal_journal_comparison'
    assert feedback['action'] == 'pyautogui.click(400, 200)'
    rows = actor.execution_journal.db.execute('SELECT seq,payload FROM events WHERE seq IN (?,?,?,?) ORDER BY seq', feedback['source_seqs']).fetchall()
    assert len({json.loads(encoded)['tool']['id'] for _, encoded in rows}) == 4
    assert feedback['latest_event_id'] == json.loads(rows[-1][1])['id']
    assert feedback['latest_event_sha256'] == hashlib.sha256(rows[-1][1].encode()).hexdigest()
    assert actor.mini_context.trace['packet_bytes'] <= 3000 and len(transport.requests) == 5
    assert value['views']['controls']['records'][0]['current_focus'] == 'unknown'
    actor.close()


def test_changed_parameters_end_repeat_window(monkeypatch, tmp_path):
    enable(monkeypatch)
    a = {'action': 'left_click', 'coordinate': [400, 200]}
    b = {'action': 'double_click', 'coordinate': [400, 200]}
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[a, a, b, a])
    for _ in range(4):
        predict(actor, obs)
    assert 'recent_repetition' not in packet(transport)['views']['current']['records'][0]
    actor.close()


@pytest.mark.parametrize('action', [{'action': 'wait'}, {'action': 'screenshot'}])
def test_passive_calls_are_not_repeat_feedback(monkeypatch, tmp_path, action):
    enable(monkeypatch)
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    attempts = last_attempts(actor)
    row = deepcopy(attempts[0])
    row[1]['tool']['arguments'] = action
    assert actor.mini_context.recent_repetition([row, row]) is None
    actor.close()


def test_image_change_is_reported_without_inventing_success_or_failure(monkeypatch, tmp_path):
    enable(monkeypatch)
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    predict(actor, obs)
    attempts = last_attempts(actor)
    original_read = actor.mini_context.read
    target = attempts[0][1]['target']

    def changed(query, parameters=()):
        rows = original_read(query, parameters)
        if parameters == (target,):
            rows = deepcopy(rows)
            rows[0][1]['frame']['original_sha256'] = 'a' * 64
            rows[0][1]['images']['original']['sha256'] = 'a' * 64
        return rows

    actor.mini_context.read = changed
    result = actor.mini_context.recent_repetition(attempts)
    assert result['repeat_count'] == 2 and result['same_image_count'] == 1 and result['effect_status'] == 'unknown'
    actor.close()


def test_bad_image_provenance_is_integrity_error(monkeypatch, tmp_path):
    enable(monkeypatch)
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    predict(actor, obs)
    attempts = last_attempts(actor)
    original_read = actor.mini_context.read

    def corrupt(query, parameters=()):
        rows = deepcopy(original_read(query, parameters))
        rows[0][1]['frame']['original_sha256'] = 'a' * 64
        return rows

    actor.mini_context.read = corrupt
    with pytest.raises(ReadAnomaly):
        actor.mini_context.recent_repetition(attempts)
    actor.close()


def test_oversized_optional_repeat_summary_is_whole_omitted_without_evicting_controls():
    current = {'frame': 'frame', 'recent_repetition': {'action': 'x' * 4000}}
    result = materialize(episode_id='episode', frame_id='frame', current=current, attempts=[], lessons=[],
        totals={'attempts': 0, 'lessons': 0}, controls=record('frame'), max_bytes=3000)
    assert result['views']['current']['records'] == [{'frame': 'frame', 'recent_repetition_omitted': True}]
    assert result['views']['controls']['records'][0]['version'] == 'mini_controls_v1'
    assert current['recent_repetition']['action'] == 'x' * 4000


def test_disabled_controls_still_deliver_repeat_evidence_without_extra_roles(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    for _ in range(3):
        predict(actor, obs)
    value = packet(transport)
    assert set(value['views']) == {'current', 'keyboard', 'attempts', 'lessons'}
    repeated = value['views']['current']['records'][0]['recent_repetition']
    assert repeated['repeat_count'] == repeated['same_image_count'] == 2
    assert repeated['effect_status'] == 'unknown'
    assert any('re-ground' in p.get('text','') for p in transport.requests[-1]['messages'][-1]['content'])
    assert len(transport.requests) == 3
    actor.close()
