"""Opt-in official intermediate scores, with separately archived guest inputs.

The official loop already evaluates at completed decision boundaries. Its Qwen
CLI does not expose those optional Namespace fields, so this adapter declares
them without editing the official runner, task, compiler or evaluator. Scores
and analysis files never enter actor history or the execution graph.
"""
from __future__ import annotations

from copy import deepcopy
import functools
import hashlib
import math
from pathlib import Path
import time

import requests


def evaluation_policy(max_steps, steps):
    if type(max_steps) is not int or not 1 <= max_steps <= 500:
        raise ValueError('Milestone evaluation requires an explicit 1..500 decision limit')
    if (not isinstance(steps, list) or not steps
            or any(type(s) is not int or not 1 <= s <= max_steps for s in steps)
            or steps != sorted(set(steps)) or steps[-1] != max_steps):
        raise ValueError('Evaluation steps must be ordered unique positive decisions ending at max_steps')
    return {'version': 'official-inline-milestones-v1', 'completed_decisions': list(steps),
            'max_steps': max_steps, 'mode': 'inline', 'final_step_uses_original_final_evaluation': True,
            'capture_task059_inputs': True, 'scores_in_actor_context': False,
            'native_termination_preserved': True}


def validate_evaluation_policy(plan, manifest=None):
    policy = plan.get('evaluation_policy')
    if manifest is not None and manifest.get('evaluation_policy') != policy:
        raise ValueError('Manifest evaluation policy differs from frozen plan')
    if policy is None:
        if plan.get('purpose') == 'checkpoint_evaluation':
            raise ValueError('Checkpoint evaluation requires its frozen milestone policy')
        return None
    expected = evaluation_policy(plan.get('max_steps'), policy.get('completed_decisions'))
    if (policy != expected or plan.get('task_id') != '059'
            or plan.get('purpose') != 'checkpoint_evaluation'
            or plan.get('agent_interface') != 'qwen-native'
            or plan.get('taskviews_profile') != 'mini_fixed_v1'):
        raise ValueError('Invalid frozen Task059 milestone evaluation policy')
    if manifest is not None:
        args = manifest['official_arguments']
        if (manifest.get('max_steps') != expected['max_steps'] or args.count('--max_steps') != 1
                or args[args.index('--max_steps') + 1] != str(expected['max_steps'])):
            raise ValueError('Official decision limit differs from milestone policy')
    return deepcopy(policy)


def capture_file(env, guest_path, destination):
    """Read the existing guest file; a failed transfer is never called absence."""
    destination = Path(destination)
    result = {'guest_path': guest_path, 'path': str(destination), 'time': time.time()}
    try:
        with requests.post(env.controller.http_server + '/file', data={'file_path': guest_path},
                           stream=True, timeout=(5, 30)) as response:
            result['http_status'] = response.status_code
            if response.status_code == 404:
                return {**result, 'status': 'absent_http404', 'sha256': None}
            response.raise_for_status()
            h = hashlib.sha256()
            size = 0
            with destination.open('xb') as f:
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 16 * 1024**2:
                        raise ValueError('Evaluation artifact exceeds 16 MiB audit bound')
                    h.update(chunk)
                    f.write(chunk)
            return {**result, 'status': 'saved', 'sha256': h.hexdigest(), 'bytes': size}
    except Exception as exc:
        return {**result, 'status': 'read_error', 'error_type': type(exc).__name__, 'error': str(exc)[:500]}


def install(stage, manifest, official_module, env_type=None):
    """Install before copying official loop globals; return its outer wrapper."""
    from . import telemetry
    from .checkpoints import atomic
    policy = validate_evaluation_policy(manifest, manifest)
    if policy is None:
        return lambda function: function
    if env_type is None:
        from desktop_env.desktop_env import DesktopEnv
        env_type = DesktopEnv
    root = Path(stage) / 'evaluation-milestones'
    root.mkdir(parents=True, exist_ok=True)
    old_inline = official_module._run_inline_checkpoint_eval

    @functools.wraps(old_inline)
    def inline(env, example, args, example_result_dir, step_num):
        previous = getattr(telemetry._context, 'intermediate_evaluation', False)
        previous_phase = getattr(telemetry._context, 'phase', None)
        telemetry._context.intermediate_evaluation = True
        try:
            return old_inline(env, example, args, example_result_dir, step_num)
        finally:
            telemetry._context.intermediate_evaluation = previous
            telemetry._context.phase = previous_phase
    official_module._run_inline_checkpoint_eval = inline
    old_evaluate = env_type.evaluate

    @functools.wraps(old_evaluate)
    def evaluate(env, *args, **kwargs):
        agent = getattr(telemetry._context, 'agent', None)
        completed = getattr(agent, 'total_steps', None)
        if type(completed) is not int or completed < 1:
            raise RuntimeError('Evaluation is missing its original actor decision boundary')
        intermediate = getattr(telemetry._context, 'intermediate_evaluation', False)
        if intermediate and completed not in policy['completed_decisions'][:-1]:
            raise RuntimeError('Unexpected intermediate evaluation boundary')
        folder = root / (f'step-{completed:03d}' if completed in policy['completed_decisions'] else f'terminal-step-{completed:03d}')
        folder.mkdir(exist_ok=False)
        record = {'completed_decisions': completed, 'intermediate': intermediate,
                  'original_evaluator_called': False, 'score': None, 'started_time': time.time(),
                  'policy': policy, 'guest_input': capture_file(env, '/home/user/Desktop/GeoGebra/vase.ggb', folder / 'vase.ggb')}
        journal = getattr(agent, 'execution_journal', None)
        if journal is not None:
            record['journal'] = {'path': str(journal.path), 'episode_id': journal.episode_id,
                                 'seq': journal.db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]}
        atomic(folder / 'started.json', record)
        previous_audit_only = getattr(telemetry._context, 'evaluation_audit_only', False)
        telemetry._context.evaluation_audit_only = True
        try:
            record['original_evaluator_called'] = True
            result = old_evaluate(env, *args, **kwargs)
            score = result.get('score') if isinstance(result, dict) else result
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError('Original evaluator returned a nonnumeric or invalid score')
            record.update(score=score, original_result=result, status='returned')
            return result
        except Exception as exc:
            record.update(status='error', error_type=type(exc).__name__, error=str(exc)[:1000])
            raise
        finally:
            telemetry._context.evaluation_audit_only = previous_audit_only
            record['official_analysis_output'] = capture_file(env,
                '/home/user/.local/share/task059data/task059_result.json', folder / 'task059_result.json')
            record['ended_time'] = time.time()
            atomic(folder / 'result.json', record)
            telemetry.emit('evaluation_milestone_archived', completed_decisions=completed, intermediate=intermediate,
                           score=record['score'], status=record['status'], path=str(folder / 'result.json'))
    env_type.evaluate = evaluate

    def wrap_loop(function):
        @functools.wraps(function)
        def loop(agent, env, example, max_steps, instruction, args, example_result_dir, scores):
            if max_steps != policy['max_steps']:
                raise ValueError('Loop limit differs from frozen milestone evaluation')
            args.checkpoint_eval_mode = 'inline'
            args.checkpoint_steps = ','.join(map(str, policy['completed_decisions'][:-1]))
            return function(agent, env, example, max_steps, instruction, args, example_result_dir, scores)
        return loop
    return wrap_loop
