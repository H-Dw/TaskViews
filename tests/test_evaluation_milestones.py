import ast
from copy import deepcopy
import datetime
import json
import logging
import os
from pathlib import Path
import shutil
from types import ModuleType, SimpleNamespace
import time

import pytest

from scripts.osworld_native_experiment import trial_max_steps
from ui_kobe.api.qwen_native import generation_profile
from ui_kobe.osworld import evaluation_milestones as milestones, telemetry
from ui_kobe.osworld.checkpoints import resume_loop


def plan():
    return {'task_id': '059', 'purpose': 'checkpoint_evaluation', 'agent_interface': 'qwen-native',
            'taskviews_profile': 'mini_fixed_v1', 'max_steps': 50,
            'evaluation_policy': milestones.evaluation_policy(50, [15, 30, 50]),
            'official_arguments': ['--max_steps', '50']}


@pytest.mark.parametrize('steps', [None, [], [0, 50], [True, 50], [30, 15, 50], [15, 15, 50], [15, 30], [51]])
def test_invalid_milestones_are_rejected_before_preparation(steps):
    with pytest.raises(ValueError):
        milestones.evaluation_policy(50, steps)


def test_explicit_short_evaluation_and_unknown_profiles_are_not_silent_defaults():
    assert trial_max_steps('evaluation') == 500
    assert trial_max_steps('checkpoint_evaluation', 50) == 50
    with pytest.raises(ValueError):
        trial_max_steps('evaluation', 50)
    for bad in (None, True, 0, 501):
        with pytest.raises(ValueError):
            trial_max_steps('checkpoint_evaluation', bad)
    with pytest.raises(ValueError):
        generation_profile('qwen-sse-high-total16k')
    p = plan()
    assert milestones.validate_evaluation_policy(p, p) == p['evaluation_policy']
    for field, value in [('max_steps', 500), ('evaluation_policy', None), ('official_arguments', ['--max_steps', '500'])]:
        with pytest.raises(ValueError):
            milestones.validate_evaluation_policy(p, {**p, field: value})
    missing = deepcopy(p)
    del missing['evaluation_policy']
    with pytest.raises(ValueError):
        milestones.validate_evaluation_policy(missing)


def official_loop_module(monkeypatch):
    """Compile the actual pinned functions; replace only offline I/O fixtures."""
    source = Path(os.environ['UI_KOBE_OFFICIAL_REPO']) / 'lib_run_single.py'
    names = {'run_single_example', '_parse_checkpoint_steps', '_run_inline_checkpoint_eval',
             '_persist_evaluation_result', '_prepare_checkpoint_cache_dir',
             '_write_checkpoint_record', '_read_checkpoint_records'}
    tree = ast.parse(source.read_text())
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in tree.body} == names
    module = ModuleType('offline_official_loop')
    module.__dict__.update(json=json, datetime=datetime, os=os, shutil=shutil, logging=logging,
        time=SimpleNamespace(sleep=lambda *_: None, perf_counter=time.perf_counter),
        logger=logging.getLogger('offline-loop'), DEFAULT_USER_RESPONSE='original default',
        setup_logger=lambda *a: logging.getLogger('offline-runtime'), _get_task_phases=lambda *_: [],
        _configure_agent_for_task=lambda *_: None, log_task_completion=lambda *a: None,
        GuestMemoryTracer=lambda *a: SimpleNamespace(capture=lambda *a, **k: None),
        _task_allows_intermediate_eval=lambda *_: True)
    exec(compile(tree, str(source), 'exec'), module.__dict__)
    return module


@pytest.mark.parametrize('terminate_at', [None, 22])
def test_real_official_loop_scores_completed_decisions_and_never_advances_past50(tmp_path, monkeypatch, terminate_at):
    module = official_loop_module(monkeypatch)
    events, calls, captures, observations = [], [], [], []
    agent = SimpleNamespace(total_steps=0, reset=lambda *a: None)
    def predict(*_):
        agent.total_steps += 1
        return 'public candidate', ['WAIT']
    agent.predict = predict
    monkeypatch.setattr(telemetry._context, 'agent', agent, raising=False)
    monkeypatch.setattr(telemetry._context, 'phase', 'action', raising=False)
    monkeypatch.setattr(telemetry._context, 'intermediate_evaluation', False, raising=False)
    monkeypatch.setattr(telemetry, 'emit', lambda kind, **v: events.append((kind, v)))
    class Env:
        action_count = 0
        cache_dir = str(tmp_path / 'cache')
        setup_controller = SimpleNamespace(cache_dir=str(tmp_path / 'cache'), reset_cache_dir=lambda *_: None)
        controller = SimpleNamespace(start_recording=lambda: None, end_recording=lambda *_: None)
        def reset(self, **kwargs):
            pass
        def _get_obs(self):
            return {'screenshot': b'offline-original-image'}
        def step(self, action, sleep):
            self.action_count += 1
            observations.append((agent.total_steps, action))
            return self._get_obs(), 0, self.action_count == terminate_at, {}
        def evaluate(self):
            calls.append((agent.total_steps, telemetry._context.intermediate_evaluation))
            return agent.total_steps / 100
    original_evaluate = Env.evaluate
    def capture(env, guest, dest):
        captures.append((agent.total_steps, guest))
        Path(dest).write_bytes(f'original artifact {agent.total_steps}'.encode())
        return {'status': 'saved', 'step': agent.total_steps}
    monkeypatch.setattr(milestones, 'capture_file', capture)
    wrap = milestones.install(tmp_path, plan(), module, Env)
    loop = wrap(resume_loop(module.run_single_example))
    args = SimpleNamespace(sleep_after_execution=3)
    out = tmp_path / 'official-results'
    out.mkdir()
    scores = []
    try:
        loop(agent, Env(), {'id': '059'}, 50, 'unchanged task instruction', args, str(out), scores)
        expected = [(15, True), (22, False)] if terminate_at else [(15, True), (30, True), (50, False)]
        assert calls == expected
        assert len(observations) == (terminate_at or 50)
        assert scores == [(terminate_at or 50) / 100]
        assert args.checkpoint_steps == '15,30' and args.checkpoint_eval_mode == 'inline'
        assert float((out / 'result_step_15.txt').read_text()) == .15
        if terminate_at is None:
            assert float((out / 'result_step_30.txt').read_text()) == .3
        assert not (out / 'result_step_50.txt').exists()
        assert float((out / 'result.txt').read_text()) == (terminate_at or 50) / 100
        for step, intermediate in calls:
            folder = f'step-{step:03d}' if step in (15, 30, 50) else f'terminal-step-{step:03d}'
            record = json.loads((tmp_path / 'evaluation-milestones' / folder / 'result.json').read_text())
            assert record['score'] == step / 100 and record['original_evaluator_called']
            assert record['intermediate'] == intermediate
        assert len(captures) == len(calls) * 2
        assert telemetry._context.phase == 'action' and not telemetry._context.intermediate_evaluation
    finally:
        Env.evaluate = original_evaluate


def test_intermediate_telemetry_does_not_enter_terminal_lifecycle_or_journal(tmp_path, monkeypatch):
    source = Path(telemetry.__file__)
    tree = ast.parse(source.read_text())
    install = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'install')
    evaluate = next(n for n in install.body if isinstance(n, ast.FunctionDef) and n.name == 'evaluate')
    events, graph = [], []
    namespace = {**telemetry.__dict__, '_root': tmp_path / 'telemetry',
                 'original_evaluate': lambda *_: .2,
                 'emit': lambda kind, **v: events.append(kind),
                 'record_transition': lambda *a, **k: graph.append(a)}
    exec(compile(ast.Module(body=[evaluate], type_ignores=[]), str(source), 'exec'), namespace)
    monkeypatch.setattr(telemetry._context, 'intermediate_evaluation', True, raising=False)
    assert namespace['evaluate'](object()) == .2
    assert events == ['milestone_evaluation_start', 'milestone_evaluation_result'] and not graph
    assert not list(tmp_path.glob('*.json'))
