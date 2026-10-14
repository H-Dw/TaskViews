from pathlib import Path

import pytest

from scripts import task059_reasoning_matrix as matrix
from scripts.osworld_native_experiment import digest, load, write
from scripts.task059_low50_pipeline import completion_hook


@pytest.fixture
def declared(tmp_path):
    pairs = {effort: str(tmp_path / effort) for effort in ('high', 'xhigh')}
    cfg = {'version': 'qwen-task059-reasoning-matrix-v1', 'order': ['high', 'xhigh'],
           'max_steps': 50, 'evaluation_steps': [15, 30, 50], 'pairs': pairs}
    write(tmp_path / 'pipeline.json', cfg)
    write(tmp_path / 'state.json', {'phase': 'prepared', 'config_sha256': digest(tmp_path / 'pipeline.json'),
                                  'formal_actor_resume_authorized': True})
    for effort, value in pairs.items():
        pair = Path(value)
        write(pair / 'pipeline.json', {'generation_profile': f'qwen-sse-{effort}-total16k'})
        write(pair / 'state.json', {'phase': 'prepared', 'config_sha256': digest(pair / 'pipeline.json')})
    return tmp_path, cfg


def test_one_running_high_arm_prevents_xhigh_dispatch(declared, monkeypatch):
    root, cfg = declared
    calls = []
    monkeypatch.setattr(matrix, 'advance_pair', lambda pair: calls.append(pair) or {
        'phase': 'ui_kobe_like_launch_submitted', 'current_arm': 'ui_kobe_like'})
    state = matrix.advance(root)
    assert calls == [Path(cfg['pairs']['high'])]
    assert state['current_effort'] == 'high' and state['current_arm'] == 'ui_kobe_like'


def test_complete_high_pair_allows_xhigh_and_both_complete_stop(declared, monkeypatch):
    root, cfg = declared
    completed = {'phase': 'complete', 'current_arm': None,
                 'ui_kobe_like_completed': {'score': 0}, 'taskviews_completed': {'score': 0}}
    calls = []
    def dispatch(pair):
        calls.append(pair)
        return completed if pair.name == 'high' else {'phase': 'ui_kobe_like_launch_submitted', 'current_arm': 'ui_kobe_like'}
    monkeypatch.setattr(matrix, 'advance_pair', dispatch)
    assert matrix.advance(root)['current_effort'] == 'xhigh'
    assert calls == [Path(cfg['pairs'][k]) for k in ('high', 'xhigh')]
    monkeypatch.setattr(matrix, 'advance_pair', lambda *_: completed)
    assert matrix.advance(root)['phase'] == 'complete'
    monkeypatch.setattr(matrix, 'advance_pair', lambda *_: pytest.fail('Completed matrix must not rerun'))
    assert matrix.advance(root)['no_remaining_owned_vm']


def test_provider_pause_and_resource_wait_do_not_start_another_pair(declared, monkeypatch):
    root, _ = declared
    monkeypatch.setattr(matrix, 'advance_pair', lambda *_: {'phase': 'taskviews_paused', 'current_arm': 'taskviews'})
    assert matrix.advance(root)['phase'] == 'high_taskviews_paused'
    def wait(*_):
        raise RuntimeError('Windows startup reserve excluding experiment memory is below 5/45/12 GiB')
    monkeypatch.setattr(matrix, 'advance_pair', wait)
    assert matrix.advance(root)['phase'] == 'high_waiting_startup_resources'
    monkeypatch.setattr(matrix, 'advance_pair', lambda *_: (_ for _ in ()).throw(RuntimeError('real checkpoint corruption')))
    with pytest.raises(RuntimeError, match='checkpoint corruption'):
        matrix.advance(root)


def test_pair_profile_tampering_rejected_and_callback_targets_matrix(declared, tmp_path):
    root, cfg = declared
    units = tmp_path / 'units'
    units.mkdir()
    name = completion_hook(root, 'high-ui', units)
    assert 'task059_reasoning_matrix.py advance --root' in (units / name).read_text()
    pair = Path(cfg['pairs']['high'])
    write(pair / 'pipeline.json', {'generation_profile': 'qwen-sse-low-total16k'})
    child = load(pair / 'state.json')
    child['config_sha256'] = digest(pair / 'pipeline.json')
    write(pair / 'state.json', child)
    with pytest.raises(RuntimeError, match='profile or configuration'):
        matrix.advance(root)
