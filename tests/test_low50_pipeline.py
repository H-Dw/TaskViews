from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import task059_low50_pipeline as pipeline
from scripts.osworld_native_experiment import digest, write


@pytest.fixture
def declared(tmp_path, monkeypatch):
    read_text = Path.read_text

    def controlled_host(path, *args, **kwargs):
        if path == Path('/proc/swaps'):
            return 'Filename\tType\tSize\tUsed\tPriority\n'
        return read_text(path, *args, **kwargs)

    # These unit tests simulate a ready host; do not depend on the test machine's swap.
    monkeypatch.setattr(Path, 'read_text', controlled_host)
    cfg = {'order': ['ui_kobe_like', 'taskviews'], 'max_steps': 50, 'evaluation_steps': [15, 30, 50],
           'generation_profile': 'qwen-sse-low-total16k', 'validation': str(tmp_path / 'proof.json'),
           'plans': {a: str(tmp_path / a) for a in ('ui_kobe_like', 'taskviews')}}
    write(tmp_path / 'pipeline.json', cfg)
    write(tmp_path / 'state.json', {'phase': 'prepared', 'config_sha256': digest(tmp_path / 'pipeline.json')})
    return tmp_path, cfg


def test_swap_enabled_still_blocks_successor_launch(declared, monkeypatch):
    root, cfg = declared
    stage = paused_stage(root, cfg)
    (stage / 'paused.json').unlink()
    write(stage / 'manifest.json', {'unit': 'offline-owned.service', 'run_id': 'offline-owned',
        'runtime_paths': [], 'generation_profile': {'name': cfg['generation_profile']}})
    write(stage / 'audit.json', {'valid_score': True, 'source_unchanged': True, 'cleanup_ok': True,
        'score': 0.0, 'counters': {'decisions': 50}, 'evaluation_milestones': []})
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '0', 'ActiveState': 'inactive'})
    monkeypatch.setattr(pipeline, 'settled_requests', lambda *_: ({'one'}, {'one'}))
    monkeypatch.setattr(pipeline, 'launch', lambda *_: pytest.fail('Swap must block the next VM'))
    read_text = Path.read_text

    def host_with_swap(path, *args, **kwargs):
        if path == Path('/proc/swaps'):
            return 'Filename\tType\tSize\tUsed\tPriority\n/dev/offline-test partition 1024 0 -2\n'
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', host_with_swap)
    with pytest.raises(RuntimeError, match='Swap is enabled'):
        pipeline.advance(root)


def paused_stage(root, cfg, kind='ConnectError'):
    stage = Path(cfg['plans']['ui_kobe_like']) / 'ui_kobe_like'
    write(stage / 'manifest.json', {'unit': 'offline-owned.service', 'plan_root': str(stage.parent),
                                  'generation_profile': {'name': cfg['generation_profile']}})
    write(stage / 'paused.json', {'error_type': kind, 'error': 'original failed transport'})
    return stage


def test_pipeline_initial_launch_submits_only_ui_and_never_creates_mini(declared, monkeypatch):
    root, cfg = declared
    calls = []
    monkeypatch.setattr(pipeline, 'frozen_check', lambda path: calls.append(('freeze', path)))
    monkeypatch.setattr(pipeline, 'launch', lambda path, arm: calls.append(('launch', arm)))
    state = pipeline.advance(root)
    assert calls == [('freeze', Path(cfg['plans']['ui_kobe_like'])), ('launch', 'ui_kobe_like')]
    assert state['phase'] == 'ui_kobe_like_launch_submitted'
    assert not (root / 'taskviews').exists()


@pytest.mark.parametrize('active', [True, False])
def test_provider_pause_never_auto_retries_or_advances_mini(declared, monkeypatch, active):
    root, cfg = declared
    paused_stage(root, cfg)
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '7' if active else '0',
                         'ActiveState': 'active' if active else 'inactive'})
    monkeypatch.setattr(pipeline, 'settled_requests', lambda *_: ({'one', 'two'}, {'one', 'two'}))
    monkeypatch.setattr(pipeline, 'launch', lambda *_: pytest.fail('No next episode before completion'))
    state = pipeline.advance(root)
    if not active:
        assert state['phase'] == 'ui_kobe_like_paused'
        assert state['pause']['requires_new_human_retry_authorization']
    assert not (root / 'taskviews').exists()


def test_startup_probe_permits_one_same_vm_resume_and_never_infinite_retries(declared, monkeypatch):
    from scripts import taskviews_recovery
    root, cfg = declared
    stage = paused_stage(root, cfg, 'StartupRecoveryProbe')
    write(stage.parent / 'validation.json', {'source': 'current replacement plan'})
    write(Path(cfg['validation']), {'source': 'old pipeline preparation'})
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '0', 'ActiveState': 'inactive'})
    monkeypatch.setattr(pipeline, 'settled_requests', lambda *_: (set(), set()))
    calls = []
    monkeypatch.setattr(taskviews_recovery, 'resume', lambda s, v, r: calls.append((s, v)) or {'status': 'resuming'})
    state = pipeline.advance(root)
    assert state['ui_kobe_like_startup_resumed'] and calls == [(stage, stage.parent / 'validation.json')]
    assert pipeline.load(calls[0][1])['source'] == 'current replacement plan'
    assert pipeline.advance(root)['phase'] == 'ui_kobe_like_paused'
    assert len(calls) == 1


def test_bad_predecessor_audit_prevents_next_vm(declared, monkeypatch):
    root, cfg = declared
    stage = paused_stage(root, cfg)
    (stage / 'paused.json').unlink()
    write(stage / 'audit.json', {'valid_score': True, 'source_unchanged': True, 'cleanup_ok': False})
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '0', 'ActiveState': 'inactive'})
    monkeypatch.setattr(pipeline, 'launch', lambda *_: pytest.fail('Owned overlay cleanup is required'))
    assert pipeline.advance(root)['phase'] == 'ui_kobe_like_audit_failed'


def test_valid_zero_score_and_owned_cleanup_allow_only_the_next_mini(declared, monkeypatch):
    import docker
    root, cfg = declared
    stage = paused_stage(root, cfg)
    (stage / 'paused.json').unlink()
    write(stage / 'manifest.json', {'unit': 'owned-ui.service', 'run_id': 'owned-ui', 'runtime_paths': [],
                                  'generation_profile': {'name': cfg['generation_profile']}})
    write(stage / 'audit.json', {'valid_score': True, 'source_unchanged': True, 'cleanup_ok': True,
                               'score': 0.0, 'counters': {'decisions': 50}, 'evaluation_milestones': []})
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '0', 'ActiveState': 'inactive'})
    monkeypatch.setattr(pipeline, 'settled_requests', lambda *_: ({'original'}, {'original'}))
    monkeypatch.setattr(docker, 'from_env', lambda **_: SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_: []), close=lambda: None))
    calls = []
    monkeypatch.setattr(pipeline, 'frozen_check', lambda p: calls.append(('freeze', p)))
    monkeypatch.setattr(pipeline, 'launch', lambda p, a: calls.append(('launch', a)))
    state = pipeline.advance(root)
    assert state['ui_kobe_like_completed']['score'] == 0.0
    assert state['phase'] == 'taskviews_launch_submitted'
    assert calls == [('freeze', Path(cfg['plans']['taskviews'])), ('launch', 'taskviews')]


def test_completion_handler_is_event_driven_and_bounded(declared, tmp_path):
    root, _ = declared
    units = tmp_path / 'units'
    units.mkdir()
    name = pipeline.completion_hook(root, 'original-run', units)
    text = (units / name).read_text()
    assert 'systemd-run --user --scope' in text and '--property=MemoryMax=128M' in text
    assert '--property=MemorySwapMax=0' in text and 'advance --root' in text
    assert 'Restart=no' in text and 'Timer' not in text
    assert pipeline.completion_hook(root, 'original-run', units) == name


def test_mismatched_pipeline_configuration_rejected(declared):
    root, cfg = declared
    cfg = deepcopy(cfg)
    cfg['max_steps'] = 500
    write(root / 'pipeline.json', cfg)
    with pytest.raises(RuntimeError, match='configuration changed'):
        pipeline.advance(root)


def test_cleanup_never_deletes_parent_or_unrelated_paths(tmp_path):
    stage = tmp_path / 'stage'
    write(stage / 'checkpoints/tv-original/manifest.json', {'files': {}})
    (stage / 'checkpoints/tv-original/actor.json').write_text('private history')
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    pipeline.retire_checkpoint_payloads(stage)
    assert unrelated.exists() and stage.exists() and not (stage / 'checkpoints').exists()
    assert (stage / 'retired-checkpoint-metadata/tv-original/manifest.json').exists()
    assert not (stage / 'retired-checkpoint-metadata/tv-original/actor.json').exists()


def test_diagnostic_authorization_does_not_resume_or_launch_an_episode(declared, monkeypatch):
    root, _ = declared
    state = pipeline.load(root / 'state.json')
    state.update(phase='interface_repair_ready_waiting_formal_resume_authorization', formal_actor_resume_authorized=False)
    write(root / 'state.json', state)
    monkeypatch.setattr(pipeline, 'launch', lambda *_: pytest.fail('API diagnostics are separate from actor resume'))
    assert pipeline.advance(root)['phase'] == state['phase']


def test_prepared_mini_override_is_explicit_and_hash_checked(declared):
    root, cfg = declared
    replacement = root / 'repair/mini-new-source'
    write(replacement / 'plan.json', {'preserve_old_plan': True})
    write(replacement / 'validation.json', {'exit_code': 0})
    state = {'plan_overrides': {'taskviews': {'root': str(replacement),
        'plan_sha256': digest(replacement / 'plan.json'), 'validation_sha256': digest(replacement / 'validation.json')}}}
    assert pipeline.active_plan(cfg, state, 'taskviews') == replacement
    assert pipeline.active_plan(cfg, state, 'ui_kobe_like') == Path(cfg['plans']['ui_kobe_like'])
    write(replacement / 'plan.json', {'tampered': True})
    with pytest.raises(RuntimeError, match='plan/proof changed'):
        pipeline.active_plan(cfg, state, 'taskviews')


def test_queued_ui_override_cannot_replace_an_existing_episode(declared):
    root, cfg = declared
    replacement = root / 'replacement-ui'
    write(replacement / 'plan.json', {'new_frozen_source': True})
    write(replacement / 'validation.json', {'exit_code': 0})
    state = {'plan_overrides': {'ui_kobe_like': {'root': str(replacement),
        'plan_sha256': digest(replacement / 'plan.json'), 'validation_sha256': digest(replacement / 'validation.json')}}}
    assert pipeline.active_plan(cfg, state, 'ui_kobe_like') == replacement
    (Path(cfg['plans']['ui_kobe_like']) / 'ui_kobe_like').mkdir(parents=True)
    with pytest.raises(ValueError, match='existing UI episode'):
        pipeline.active_plan(cfg, state, 'ui_kobe_like')


@pytest.mark.parametrize('verified', [False, True])
def test_reused_ports_require_a_prior_verified_immutable_cleanup_receipt(declared, monkeypatch, verified):
    import docker
    root, cfg = declared
    stage = paused_stage(root, cfg)
    (stage / 'paused.json').unlink()
    write(stage / 'manifest.json', {'unit': 'owned-ui.service', 'run_id': 'owned-ui', 'runtime_paths': [],
                                  'generation_profile': {'name': cfg['generation_profile']}})
    write(stage / 'audit.json', {'valid_score': True, 'source_unchanged': True, 'cleanup_ok': True,
                               'score': 0.0, 'counters': {'decisions': 50}, 'evaluation_milestones': []})
    write(stage / 'checkpoint-vm.json', {'ports': {'vnc': 8006}})
    if verified:
        state = pipeline.load(root / 'state.json')
        state['ui_kobe_like_completed'] = {'audit': str(stage / 'audit.json'),
            'audit_sha256': digest(stage / 'audit.json'), 'cleanup_verified': True}
        write(root / 'state.json', state)
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '0', 'ActiveState': 'inactive'})
    monkeypatch.setattr(pipeline, 'settled_requests', lambda *_: ({'original'}, {'original'}))
    monkeypatch.setattr(docker, 'from_env', lambda **_: SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_: []), close=lambda: None))
    class BoundSocket:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def settimeout(self, _):
            pass
        def connect_ex(self, _):
            return 0
    monkeypatch.setattr(pipeline.socket, 'socket', BoundSocket)
    monkeypatch.setattr(pipeline, 'frozen_check', lambda *_: None)
    monkeypatch.setattr(pipeline, 'launch', lambda *_: None)
    if not verified:
        with pytest.raises(RuntimeError, match='port still bound'):
            pipeline.advance(root)
    else:
        assert pipeline.advance(root)['phase'] == 'taskviews_launch_submitted'
        write(stage / 'audit.json', {'valid_score': True, 'source_unchanged': True, 'cleanup_ok': True,
                                   'score': 1.0, 'counters': {'decisions': 50}})
        with pytest.raises(RuntimeError, match='cleanup receipt changed'):
            pipeline.advance(root)


def test_initial_checkpoint_resume_uses_actual_manifest_repair_proof(declared, monkeypatch):
    from scripts import taskviews_recovery
    root, cfg = declared
    stage = paused_stage(root, cfg, 'StartupRecoveryProbe')
    repair = stage / 'repair-plans/new-source'
    write(repair / 'validation.json', {'actual_source': True})
    write(stage / 'manifest.json', {'unit': 'offline-owned.service', 'plan_root': str(repair),
                                  'generation_profile': {'name': cfg['generation_profile']}})
    monkeypatch.setattr(pipeline, 'unit_state', lambda *_: {'ControlPID': '0', 'MainPID': '0', 'ActiveState': 'inactive'})
    monkeypatch.setattr(pipeline, 'settled_requests', lambda *_: (set(), set()))
    calls = []
    monkeypatch.setattr(taskviews_recovery, 'resume', lambda s, v, r: calls.append(v) or {'status': 'resuming'})
    pipeline.advance(root)
    assert calls == [repair / 'validation.json']
