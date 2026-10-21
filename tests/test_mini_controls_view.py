from copy import deepcopy
import json

import pytest

from kobe_views.controls_view import VERSION, BINDINGS, parse_note, policy
from scripts.run_official_native_tasks import configure_profile
from ui_kobe.api.kimi_stream import Completion
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.mini_taskviews_context import CONTROLS_LABEL
from ui_kobe.osworld.taskviews_profiles import validate_profile
from test_mini_profiles import mini_plan
from test_mini_taskviews import make_actor, packet, predict


def enable(monkeypatch):
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', VERSION)


def note(label='Maximize'):
    return '<controls>' + json.dumps({'items': [{'label': label, 'role': 'button',
        'shortcut': None, 'enabled': 'unknown', 'focused': 'unknown'}],
        'selected_binding': 'window.maximize', 'expected': 'target fills desktop work area'}) + '</controls>'


def test_control_view_is_independent_source_bound_and_stays_in_existing_budget(monkeypatch, tmp_path):
    enable(monkeypatch)
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[{'action': 'key', 'keys': ['alt', 'f10']}])
    commands = predict(actor, obs)
    value = packet(transport)
    controls = value['views']['controls']['records'][0]
    assert set(value['views']) == {'current', 'attempts', 'lessons', 'controls'}
    assert controls['frame_id'] == actor.frame.metadata['frame_id']
    assert actor.context_label == CONTROLS_LABEL
    assert controls['bindings'] == BINDINGS and controls['current_focus'] == 'unknown'
    assert controls['grade'] == 'documented_defaults' and controls['previous_note'] is None
    assert all(b['source'] in controls['sources'] for b in controls['bindings'])
    assert actor.mini_context.trace['packet_bytes'] <= 3000 and len(transport.requests) == 1
    assert commands == ['pyautogui.hotkey("alt", "f10")']
    assert actor.contract.taskviews_context_bytes == 8000 and actor.contract.tool_repair_retries == 2
    actor.close()


def test_same_actor_note_is_original_historical_proposal_and_never_current_focus(monkeypatch, tmp_path):
    enable(monkeypatch)
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    create = transport.create

    def annotated(**request):
        body = create(**request).model_dump()
        body['choices'][0]['message']['content'] = note()
        return Completion(body)

    transport.create = annotated
    predict(actor, obs)
    prior_id = actor.execution_journal.decision['id']
    predict(actor, obs)
    controls = packet(transport)['views']['controls']['records'][0]
    previous = controls['previous_note']
    assert previous['source_event_id'] == prior_id and previous['grade'] == 'model_proposal'
    assert previous.get('reobserve_required', previous.get('whole_note_omitted')) is True
    assert controls['current_focus'] == 'unknown' and controls['frame_id'] == actor.frame.metadata['frame_id']
    assert len(transport.requests) == 2 and actor.mini_context.delivery['count'] == 2
    actor.close()


@pytest.mark.parametrize('text', [None, 'plain prose', '<controls>{}</controls>',
    note('x' * 101), note() + note(), note().replace('unknown', 'success')])
def test_bad_optional_notes_do_not_create_facts(text):
    assert parse_note(text) is None


def test_note_identity_and_native_guard_are_not_overridden(monkeypatch, tmp_path):
    enable(monkeypatch)
    actor, obs, transport = make_actor(monkeypatch, tmp_path,
        actions=[{'action': 'made_up'}, {'action': 'key', 'keys': ['alt', 'f10']}])
    assert predict(actor, obs) == ['pyautogui.hotkey("alt", "f10")']
    assert len(transport.requests) == 2 and actor.pending == 'original-2'
    assert any(m.get('tool_call_id') == 'original-1' for m in transport.requests[-1]['messages'])
    assert all(packet_request['budget_role'] == 'executor' for packet_request in transport.requests)
    actor.close()


def test_profile_extension_requires_exact_plan_manifest_and_has_disabled_default(monkeypatch):
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
    plan = mini_plan()
    manifest = {'taskviews_profile': plan['taskviews_profile'], 'mini_profile': plan['mini_profile'], 'source_branch': 'main'}
    monkeypatch.setattr('scripts.osworld_native_experiment.require_mini_branch', lambda: None)
    configure_profile(plan, manifest)
    import os
    assert os.environ['UI_KOBE_MINI_CONTROLS_VIEW'] == 'disabled'
    plan['mini_controls_view'] = policy()
    validate_profile(plan)
    with pytest.raises(RuntimeError):
        configure_profile(plan, manifest)
    manifest['mini_controls_view'] = policy()
    configure_profile(plan, manifest)
    assert os.environ['UI_KOBE_MINI_CONTROLS_VIEW'] == VERSION
    bad = deepcopy(plan)
    bad['mini_controls_view']['focus_gate'] = True
    with pytest.raises(ValueError):
        validate_profile(bad)


def test_old_checkpoint_can_gain_readonly_extension_without_losing_delivery_cursor(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
    old, obs, _ = make_actor(monkeypatch, tmp_path / 'old')
    predict(old, obs)
    saved = old.checkpoint_state()
    enable(monkeypatch)
    new, _, _ = make_actor(monkeypatch, tmp_path / 'new')
    new.execution_journal = old.execution_journal
    new.restore_checkpoint_state(saved)
    assert new.mini_context.delivery == old.mini_context.delivery and new.cached_context is None
    assert new.checkpoint_state()['controls_view'] == policy()
    new.controls_view_enabled = False
    with pytest.raises(ReadAnomaly):
        new.restore_checkpoint_state({**saved, 'controls_view': policy()})
    old.close()


def test_whole_control_projection_omission_keeps_native_path(monkeypatch, tmp_path):
    enable(monkeypatch)
    actor, obs, transport = make_actor(monkeypatch, tmp_path, tiny=True)
    assert predict(actor, obs) == ['pyautogui.click()']
    assert actor.cached_context is None and len(transport.requests) == 1
    actor.close()
