from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from kobe_views.fixed_views import PROFILE
from scripts import osworld_native_experiment as experiment
from scripts.run_official_native_tasks import agent_class, configure_profile
from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, QwenGenerationProfile
from ui_kobe.osworld.checkpoints import Checkpoints, ReadAnomaly
from ui_kobe.osworld.mini_taskviews_native import QwenMiniTaskViewsNativeAgent
from ui_kobe.osworld.qwen_native_base import QwenTransitionNativeAgent
from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
from ui_kobe.osworld.taskviews_profiles import FULL_PROFILE, frozen_profile, mini_cua_contract, validate_profile
from ui_kobe.osworld.transitions import TransitionJournal
from test_mini_taskviews import TASK, make_actor, predict
from test_taskviews_checkpoints import VM


def mini_plan(arm='taskviews'):
    return {'task_id': '059', 'implementation_version': 10, 'agent_interface': 'qwen-native',
        'arms': [arm], 'protocols': [PROTOCOL], 'model': MODEL, 'base_url': BASE_URL,
        'api_key_env': 'QWEN_API_KEY', 'generation_profile': QwenGenerationProfile().__dict__,
        'provider_compatibility': {'compatible': True}, 'checkpoint_policy': {'enabled': True},
        'taskviews_profile': PROFILE, 'mini_profile': frozen_profile(arm), 'taskviews_feedback': False,
        'cua_contract': mini_cua_contract(), 'source_branch': 'main'}


@pytest.mark.parametrize('arm,cls', [('taskviews', QwenMiniTaskViewsNativeAgent),
                                   ('ui_kobe_like', QwenTransitionNativeAgent)])
def test_explicit_factory_and_frozen_mini_profile(arm, cls):
    plan = mini_plan(arm)
    experiment.check_interface(plan)
    assert validate_profile(plan) == PROFILE
    assert agent_class('qwen-native', arm, PROFILE) is cls
    assert experiment.taskviews_workflow(plan) == {'UI_KOBE_TASKVIEWS_FEEDBACK_V10': '0'}
    assert agent_class('qwen-native', 'taskviews') is QwenTaskViewsNativeAgent
    with pytest.raises(KeyError):
        agent_class('qwen-native', 'ui_kobe_like')
    with pytest.raises(ValueError):
        agent_class('k3-native', arm, PROFILE)


@pytest.mark.parametrize('change', [
    {'taskviews_feedback': True}, {'arms': ['taskviews', 'ui_kobe_like']},
    {'source_branch': 'backup/main-20261021'}, {'mini_profile': {'profile': PROFILE}},
    {'taskviews_profile': FULL_PROFILE}, {'taskviews_profile': 'implicit'},
    {'cua_contract': {**mini_cua_contract(), 'context_max_text_chars': 64000}},
    {'implementation_version': 9}, {'task_id': '046'}, {'checkpoint_policy': {}},
    {'agent_interface': 'k3-native'}, {'protocols': ['xml']}])
def test_mixed_profiles_or_larger_budgets_rejected_before_runtime(change):
    plan = {**mini_plan(), **change}
    with pytest.raises((ValueError, RuntimeError)):
        experiment.check_interface(plan)


@pytest.mark.parametrize('branch', ['mini', 'backup/main-20261021', '', 'another-mini'])
def test_branch_admission_rejects_other_or_detached_checkouts(monkeypatch, branch):
    monkeypatch.setattr(experiment.subprocess, 'check_output', lambda *a, **k: branch)
    with pytest.raises(RuntimeError, match='Switch Git to main'):
        experiment.require_mini_branch()


def test_main_branch_admitted_and_legacy_plan_metadata_preserved(monkeypatch):
    monkeypatch.setattr(experiment.subprocess, 'check_output', lambda *a, **k: 'main\n')
    experiment.require_mini_branch()
    legacy = {**mini_plan(), 'source_branch': 'mini'}
    before = deepcopy(legacy)
    assert validate_profile(legacy) == PROFILE
    assert legacy == before


def test_runner_contract_cannot_mix_manifest_and_plan(monkeypatch):
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_PROFILE', FULL_PROFILE)
    plan = mini_plan()
    manifest = {'taskviews_profile': PROFILE, 'mini_profile': plan['mini_profile'], 'source_branch': 'main'}
    calls = []
    monkeypatch.setattr(experiment, 'require_mini_branch', lambda: calls.append('branch'))
    assert configure_profile(plan, manifest) == PROFILE and calls == ['branch']
    for field in ('taskviews_profile', 'mini_profile', 'source_branch'):
        with pytest.raises(RuntimeError):
            configure_profile(plan, {**manifest, field: 'foreign'})
    assert calls == ['branch']


@pytest.mark.parametrize('arm', ['taskviews', 'ui_kobe_like'])
@pytest.mark.parametrize('inspection', [None, 10])
@pytest.mark.parametrize('effort', [None, 'low', 'high', 'xhigh'])
def test_offline_preparation_and_launch_freeze_one_profile_without_starting_services(tmp_path, monkeypatch, arm, inspection, effort):
    low50 = effort is not None
    from examples import osworld2_eval
    from ui_kobe.osworld import official_base, task_examples, runner
    monkeypatch.setattr(official_base, 'verify_official_base', lambda *a: None)
    monkeypatch.setattr(osworld2_eval, 'official_identity',
                        lambda *a: {'task': '059', 'instruction': 'Use VLC and Chrome.'})
    monkeypatch.setattr(task_examples, 'task_example', lambda *a: SimpleNamespace(assets=[]))
    monkeypatch.setattr(runner, 'source_snapshot', lambda *a: {})
    monkeypatch.setattr(experiment, 'project_snapshot', lambda: {})
    monkeypatch.setattr(experiment, 'host_status', lambda: {'offline_fixture': True})
    monkeypatch.setattr(experiment, 'committed_source', lambda: 'offline-validated-commit')
    checks, commands = [], []
    monkeypatch.setattr(experiment, 'require_mini_branch', lambda: checks.append('branch'))
    proof = tmp_path / 'compatibility-fixture.json'
    experiment.write(proof, {'compatible': True, 'vision_json': True, 'native_tools': True,
        'original_tool_history': True, 'model': MODEL, 'base_url': BASE_URL, 'key_env': 'QWEN_API_KEY',
        'stream': False, 'requests': [{'http_status': 200, 'usage': {'total_tokens': 1}}] * 3})
    validation = tmp_path / 'validation-fixture.json'
    experiment.write(validation, {'exit_code': 0, 'project_source': {}})
    root = tmp_path / 'offline-plan'
    experiment.prepare(root, '059', validation, agent_interface='qwen-native', compatibility=proof,
                       checkpoints=True, taskviews_profile=PROFILE, qwen_arm=arm, inspection_minutes=inspection,
                       purpose='checkpoint_evaluation' if low50 else 'evaluation', max_steps=50 if low50 else None,
                       qwen_generation_profile=f'qwen-sse-{effort}-total16k' if low50 else None,
                       evaluation_steps=[15, 30, 50] if low50 else None)
    plan = experiment.load(root / 'plan.json')
    from ui_kobe.api.qwen_png_transport import policy as image_policy
    assert plan['qwen_image_transport_policy'] == image_policy()
    assert plan['arms'] == [arm] and plan['implementation_version'] == 10
    assert plan['mini_profile'] == frozen_profile(arm, plan['mini_graph_mode']) and plan['taskviews_feedback'] is False
    assert plan['source_branch'] == 'main' and plan['iteration_commit_required']
    assert plan['cua_contract'] == mini_cua_contract() and plan['max_steps'] == (50 if low50 else 500)
    assert plan['checkpoint_policy']['inspection_minutes'] == (30 if inspection is None else inspection)
    if arm == 'taskviews':
        assert plan['mini_keyboard_tools']['enabled_toolsets'] == ['general', 'app.chrome', 'app.vlc']
        assert plan['mini_keyboard_selection']['mode'] == 'task_names'
    else:
        assert 'mini_keyboard_tools' not in plan and 'mini_keyboard_selection' not in plan
    if low50:
        assert plan['generation_profile']['reasoning_effort'] == effort
        assert plan['provider_request']['enable_thinking'] is True and plan['provider_request']['stream'] is True
        assert plan['provider_request']['output_field'] == 'max_completion_tokens'
        assert plan['provider_request']['stream_options'] == {'include_usage': True}
        assert plan['evaluation_policy']['completed_decisions'] == [15, 30, 50]
    else:
        assert 'does not authorize' in plan['user_authorization']
        assert plan['provider_request']['enable_thinking'] is False
    home = tmp_path / 'home'
    (home / '.config/systemd/user').mkdir(parents=True)
    monkeypatch.setattr(experiment.Path, 'home', lambda: home)
    monkeypatch.setattr(experiment, 'resources_ready', lambda: checks.append('resources'))
    monkeypatch.setattr(experiment.subprocess, 'check_output', lambda *a, **k: '')
    monkeypatch.setattr(experiment.subprocess, 'run', lambda args, **k: commands.append(args))
    experiment.launch(root, arm)
    manifest = experiment.load(root / arm / 'manifest.json')
    assert manifest['mini_profile'] == plan['mini_profile'] and manifest['taskviews_profile'] == PROFILE
    assert manifest['source_branch'] == 'main' and manifest['checkpoint_policy'] == plan['checkpoint_policy']
    assert manifest['qwen_request_policy'] == plan['qwen_request_policy']
    assert manifest['qwen_image_transport_policy'] == plan['qwen_image_transport_policy']
    assert manifest.get('mini_keyboard_selection') == plan.get('mini_keyboard_selection')
    assert manifest.get('mini_keyboard_tools') == plan.get('mini_keyboard_tools')
    assert manifest['official_arguments'][manifest['official_arguments'].index('--max_steps') + 1] == str(50 if low50 else 500)
    if low50:
        assert manifest['evaluation_policy'] == plan['evaluation_policy']
        assert manifest['generation_profile'] == plan['generation_profile']
        assert '--enable_thinking' in manifest['official_arguments'] and '--stream' in manifest['official_arguments']
    assert checks == ['branch', 'branch', 'resources']
    assert commands[-1][-2:] == ['start', manifest['unit']]


@pytest.mark.parametrize('interval,checkpoints', [(0, True), (True, True), (1441, True), (10, False)])
def test_invalid_inspection_interval_fails_before_plan_or_resource_reads(tmp_path, monkeypatch, interval, checkpoints):
    monkeypatch.setattr(experiment, 'require_mini_branch', lambda: pytest.fail('No branch or resource read required'))
    with pytest.raises(ValueError, match='Inspection interval'):
        experiment.prepare(tmp_path / 'plan', '059', tmp_path / 'proof',
                           taskviews_profile=PROFILE, checkpoints=checkpoints, inspection_minutes=interval)
    assert not (tmp_path / 'plan').exists()


def manager(tmp_path, arm='taskviews'):
    result = Checkpoints(tmp_path / 'stage', {'taskviews_profile': PROFILE, 'arm': arm}, qmp=VM())
    result.vm = {'container': 'offline-whole-vm'}
    return result


@pytest.mark.parametrize('arm,cls', [('taskviews', QwenMiniTaskViewsNativeAgent),
                                   ('ui_kobe_like', QwenTransitionNativeAgent)])
def test_profile_checkpoint_restores_native_ids_history_and_clears_old_views(tmp_path, monkeypatch, arm, cls):
    actor, obs, _ = make_actor(monkeypatch, tmp_path / 'first', cls=cls)
    if actor.execution_journal is None:
        actor.execution_journal = TransitionJournal(tmp_path / 'journal', task_id='059',
                                                   run_id='offline-ui-kobe', contract=actor.contract)
    predict(actor, obs, error='Original controller error')
    cp = manager(tmp_path, arm)
    tag = cp.save(actor, TASK, obs)
    before, pending = deepcopy(actor.turns), deepcopy(actor.pending)
    original = actor.execution_journal.path
    actor.execution_journal.append('bad_read', error='Preserve the original failed branch')
    restored, _, _ = make_actor(monkeypatch, tmp_path / 'restored', cls=cls)
    saved = cp.restore_agent(restored)
    assert saved['tag'] == tag and restored.total_steps == 1
    assert restored.turns == before and restored.pending == pending
    assert 'control' not in saved and 'task-memory' not in saved
    assert restored.execution_journal.path != original
    if arm == 'taskviews':
        assert restored.mini_context.cached is None and restored.cached_context is None
        assert restored.mini_context.delivery == actor.mini_context.delivery
    else:
        assert restored.context_provider.cached is None
    row = actor.execution_journal.db.execute("SELECT payload FROM events WHERE json_extract(payload,'$.kind')='bad_read'").fetchone()
    assert 'Preserve the original failed branch' in row[0]
    actor.close()
    restored.close()


def test_old_full_checkpoint_cannot_be_saved_or_restored_as_mini(tmp_path, monkeypatch):
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    cp = Checkpoints(tmp_path / 'full-stage', {}, qmp=VM())
    cp.vm = {}
    with pytest.raises(ReadAnomaly, match='profile'):
        cp.save(actor, TASK, obs)
    assert not cp.qmp.calls
    mini_cp = manager(tmp_path)
    tag = mini_cp.save(actor, TASK, obs)
    _, boundary = mini_cp.read(tag, metadata_only=True)
    assert boundary['completed_steps'] == 0 and boundary['checkpoint_actor_profile'] == PROFILE
    foreign = SimpleNamespace(checkpoint_profile=FULL_PROFILE, total_steps=99)
    with pytest.raises(ReadAnomaly, match='profile'):
        mini_cp.restore_agent(foreign)
    assert foreign.total_steps == 99
    actor.close()


def test_later_real_command_blocks_checkpoint_replay_before_actor_mutation(tmp_path, monkeypatch):
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    cp = manager(tmp_path)
    cp.save(actor, TASK, obs)
    predict(actor, obs)
    before = deepcopy(actor.turns)
    with pytest.raises(ReadAnomaly, match='refuse replay'):
        cp.restore_agent(actor)
    assert actor.total_steps == 2 and actor.turns == before
    actor.close()


def test_missing_original_journal_and_foreign_cursor_fail_closed(tmp_path, monkeypatch):
    actor, obs, _ = make_actor(monkeypatch, tmp_path)
    predict(actor, obs)
    cp = manager(tmp_path)
    cp.save(actor, TASK, obs)
    _, boundary = cp.read(metadata_only=True)
    with pytest.raises(ReadAnomaly, match='unavailable'):
        cp.require_no_replay({**boundary, 'journal_origin': {**boundary['journal_origin'], 'path': '/missing.sqlite'}})
    state = deepcopy(actor.checkpoint_state())
    state['delivery']['seq'] += 1000
    with pytest.raises(ReadAnomaly, match='cursor exceeds'):
        actor.restore_checkpoint_state(state)
    actor.close()


def test_frozen_cua_config_is_the_shared_mini_comparison_contract():
    value = json.loads((experiment.PROJECT / 'configs/cua-mini-fixed-v1.json').read_text())
    assert value == mini_cua_contract()


def test_mini_validation_entry_checks_branch_before_exec(monkeypatch):
    from scripts import validate_mini
    checks = []
    monkeypatch.setattr(experiment, 'require_scope', lambda cap: checks.append(cap))
    def wrong_branch():
        raise RuntimeError('Switch Git to mini')
    monkeypatch.setattr(experiment, 'require_mini_branch', wrong_branch)
    monkeypatch.setattr(validate_mini.os, 'execv', lambda *a: pytest.fail('No test execution on another branch'))
    with pytest.raises(RuntimeError, match='Switch Git'):
        validate_mini.main(['--output', 'new-proof.json'])
    assert checks == [128 * 1024**2]


def test_mini_validation_entry_forwards_arguments_in_same_python_exec_chain(monkeypatch):
    from scripts import validate_mini
    checks, commands = [], []
    monkeypatch.setattr(experiment, 'require_scope', lambda cap: checks.append(cap))
    monkeypatch.setattr(experiment, 'require_mini_branch', lambda: checks.append('mini'))
    monkeypatch.setattr(validate_mini.os, 'execv', lambda *args: commands.append(args))
    validate_mini.main(['--output', 'new-proof.json', '--tests', 'test_mini_profiles.py'])
    assert checks == [128 * 1024**2, 'mini']
    executable, command = commands[0]
    assert executable == validate_mini.sys.executable
    assert command[1].endswith('validate_cua.py') and command[2:] == [
        '--output', 'new-proof.json', '--tests', 'test_mini_profiles.py']
