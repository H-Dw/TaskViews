"""Offline integration: real OSWorld-1 runner/common actor; mock HTTP and GUI.

Run each arm in a fresh interpreter. Synthetic fixture results are not benchmark
scores. The real invoice PDFs are never opened or scored by this validator.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.verified_invoice import (ALL_ARMS, EXPERIMENTS, project_identity, specification, sources, verify_task, write)  # noqa: E402
from ui_kobe.osworld.verified_tasks import TASKS  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', choices=ALL_ARMS, required=True)
    parser.add_argument('--case', choices=('limit', 'terminate', 'empty'), default='limit')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provider', choices=('qwen', 'tinker', 'openrouter', 'sx'), default='qwen')
    parser.add_argument('--sx-url-env', choices=('SX_URL', 'SX_URL_SB'), default='SX_URL')
    parser.add_argument('--coordinate-type', choices=('absolute', 'relative'), default='absolute')
    parser.add_argument('--experiment', choices=EXPERIMENTS, default='legacy-low35')
    parser.add_argument('--task', choices=tuple(TASKS), default='invoice')
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home() / 'osworld-verified/OSWorld')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home() / 'osworld2/OSWorld-V2')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep prior validation evidence; use a new directory')
    args.output.mkdir(parents=True)
    before = sources(args.benchmark_repo, args.compiler_repo, args.task)
    plan = specification(args.provider, args.sx_url_env, args.coordinate_type, args.experiment, args.task)
    actor_scope = None
    if args.task != 'invoice':
        from scripts.osworld_native_experiment import require_scope
        # This fixture loads the actual actor plus the full official runtime,
        # so use the already frozen actor-service cap, with zero swap.
        actor_scope = require_scope(plan['service_memory_bytes'])
    if args.arm not in plan['arms']:
        raise ValueError('Arm absent from the declared experiment')
    task = verify_task(args.benchmark_repo, args.task)
    from ui_kobe.osworld.verified_runtime import load_runtime, reset_compatible
    env_module, runner, qwen = load_runtime(args.benchmark_repo, args.compiler_repo, args.task)
    from scripts.run_official_native_tasks import agent_class
    from ui_kobe.osworld import telemetry
    if args.provider == 'sx':
        from ui_kobe.osworld.sx_native import SXNativeProvider as Provider
        from ui_kobe.api.sx_native import SXNativeClient as Client
        os.environ['UI_KOBE_SX_URL_ENV'] = args.sx_url_env
    elif args.provider == 'openrouter':
        from ui_kobe.osworld.openrouter_native import OpenRouterNativeProvider as Provider
        from ui_kobe.api.openrouter_native import OpenRouterNativeClient as Client
    elif args.provider == 'tinker':
        from ui_kobe.osworld.tinker_native import TinkerNativeProvider as Provider
        from ui_kobe.api.tinker_native import TinkerNativeClient as Client
    else:
        from ui_kobe.osworld.qwen_native_base import QwenNativeProvider as Provider
        from ui_kobe.api.qwen_native import QwenNativeClient as Client
    from desktop_env.controllers.python import PythonController
    from PIL import Image
    import httpx

    os.environ[plan['api_key_env']] = 'offline-fixture-only'
    os.environ.update(UI_KOBE_GENERATION_PROFILE=plan['generation_profile']['name'],
        UI_KOBE_CUA_CONTRACT_JSON=json.dumps(plan['cua_contract']), UI_KOBE_TASKVIEWS_PROFILE='mini_fixed_v1',
        UI_KOBE_MINI_CONTROLS_VIEW='disabled', UI_KOBE_TASKVIEWS_FEEDBACK_V10='0',
        UI_KOBE_TELEMETRY_DIR=str(args.output / 'telemetry'), UI_KOBE_TASK_ID='synthetic-offline-fixture',
        OSWORLD_FULL_RUN_ID='synthetic-' + args.arm)
    selected = reset_compatible(agent_class(plan['interface'], args.arm, 'mini_fixed_v1'))
    qwen.QwenAgent = selected
    image = BytesIO()
    Image.new('RGB', (1920, 1080), 'white').save(image, format='PNG')
    observation = {'screenshot': image.getvalue()}
    initial_observation = observation
    large_frame_fixture = args.provider == 'sx' and args.case == 'terminate'
    if large_frame_fixture:
        import random
        noise = bytes(value & 31 for value in random.Random(0).randbytes(1920 * 1080 * 3))
        initial_image = BytesIO()
        Image.frombytes('RGB', (1920, 1080), noise).save(initial_image, format='PNG')
        initial_observation = {'screenshot': initial_image.getvalue()}
    counts = {'requests': 0, 'commands': 0, 'evaluations': 0, 'resets': 0}
    view_sets = []

    def stream_frame(delta=None, finish=None, usage=None):
        value = {'id': 'fixture-response', 'model': plan['model'], 'created': 1,
                 'choices': [] if usage else [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
        if usage:
            value['usage'] = usage
        return ('data: ' + json.dumps(value) + '\n\n').encode()

    def handler(request):
        body = json.loads(request.content)
        counts['requests'] += 1
        assert str(request.url) == plan['base_url'] + '/chat/completions'
        assert body['model'] == plan['model'] and body['stream']
        if large_frame_fixture and counts['requests'] == 1:
            from ui_kobe.osworld.native_history import context_size
            payload_chars, _ = context_size(body['messages'])
            assert 2_000_000 < payload_chars < plan['cua_contract']['context_max_payload_chars']
        assert all(body.get(k) == v for k, v in plan['generation_fields'].items())
        cap = plan['request_policy']['output_field']
        assert body[cap] == 16000
        assert ('max_tokens' if cap == 'max_completion_tokens' else 'max_completion_tokens') not in body
        if args.provider in ('tinker', 'openrouter') or (args.provider == 'sx' and args.experiment=='legacy-low35'):
            assert 'enable_thinking' not in body and 'preserve_thinking' not in body
        if args.provider == 'openrouter':
            for message in body['messages']:
                if message.get('role') == 'assistant':
                    assert message['reasoning_details'] == [{'type': 'reasoning.text', 'text': 'fixture', 'index': 0}]
        assert json.dumps(task['evaluator']) not in json.dumps(body)
        text = json.dumps(body['messages'])
        assert task['evaluator']['expected']['dest'] not in text
        mini_packet = None
        for part in body['messages'][-1]['content']:
            if part.get('type') == 'text' and part.get('text', '').startswith('TaskViews:'):
                packet = json.loads(part['text'].split('\n', 1)[1])
                mini_packet = packet
                view_sets.append(sorted(packet['views']))
        step = counts['requests']
        terminal = args.case == 'terminate' and step == 7
        actions = ([] if args.case == 'empty' else [{'action': 'terminate', 'status': 'success'}]
                   if terminal else [{'action': 'mouse_move', 'coordinate': [1, 1]},
                                     {'action': 'mouse_move', 'coordinate': [2, 2]}])
        calls = [{'index': i, 'id': f'fixture-{step}-{i}', 'type': 'function', 'function': {
                  'name': 'computer_use', 'arguments': json.dumps(action)}} for i, action in enumerate(actions)]
        delta = {'role': 'assistant', 'content': 'Synthetic fixture action', 'tool_calls': calls}
        if terminal and args.arm == 'taskviews':
            from kobe_views.artifact_view import CHECKS
            assert mini_packet is not None
            ref = mini_packet['views']['current']['records'][0]['ref']
            review = {'applicable': True, 'candidate': '/synthetic/artifact.bin', 'checks': {
                key: {'ref': ref, 'observed': 'Synthetic observation for ' + key} for key in CHECKS}}
            # A mock process-contract fixture, never semantic artifact proof.
            delta['content'] += '<artifact_review>' + json.dumps(review) + '</artifact_review>'
        if args.provider == 'openrouter':
            delta['reasoning_details'] = [{'type': 'reasoning.text', 'text': 'fixture', 'index': 0}]
        raw = stream_frame(delta)
        raw += stream_frame(finish='tool_calls' if calls else 'stop')
        raw += stream_frame(usage={'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              content=raw + b'data: [DONE]\n\n')

    def transport(owner, key, trace):
        return Client(api_key=key, profile=owner.profile, budget=owner.budget,
            emit=telemetry.emit, response_dir=trace / 'responses',
            client=httpx.Client(transport=httpx.MockTransport(handler)))

    def reset(env, task_config):
        counts['resets'] += 1
        assert task_config == task
        env._step_no, env._traj_no, env.action_history = 0, 0, []
        env.action_space, env.vm_ip = 'pyautogui', 'offline-fixture'
        env.controller = PythonController.__new__(PythonController)
        return initial_observation

    def command(controller, text):
        counts['commands'] += 1
        assert text.startswith('pyautogui.moveTo(')
        return {'status': 'success', 'returncode': 0, 'stdout': '', 'stderr': '', 'error': ''}

    def evaluate(env):
        counts['evaluations'] += 1
        return 0.125  # Explicit mock sentinel; never a real task score.

    # Block accidental networking, VM initialization and real GUI execution.
    with patch.object(Provider, 'provider_transport', transport), \
         patch.object(socket.socket, 'connect', side_effect=AssertionError('Live network forbidden')), \
         patch.object(env_module.DesktopEnv, '__init__', side_effect=AssertionError('VM forbidden')), \
         patch.object(env_module.DesktopEnv, 'reset', reset), \
         patch.object(env_module.DesktopEnv, '_get_obs', lambda env:
                      initial_observation if counts['requests'] == 0 else observation), \
         patch.object(env_module.DesktopEnv, 'evaluate', evaluate), \
         patch.object(env_module.DesktopEnv, 'close', lambda env: None), \
         patch.object(PythonController, 'execute_python_command', command), \
         patch.object(PythonController, 'execute_action', lambda *a: None), \
         patch.object(PythonController, 'start_recording', lambda *a: None), \
         patch.object(PythonController, 'end_recording', lambda *a: None), \
         patch.object(runner.time, 'sleep', lambda _: None):
        telemetry.install(args.output / 'telemetry')
        actor = selected(model=plan['model'], base_url=plan['base_url'], temperature=0,
                         max_tokens=16000, api_key='offline-fixture-only')
        env = env_module.DesktopEnv.__new__(env_module.DesktopEnv)
        scores = []
        runner.run_single_example(actor, env, task, plan['max_steps'], task['instruction'],
            SimpleNamespace(sleep_after_execution=0, result_dir=str(args.output)), str(args.output), scores)
        expected = 7 if args.case == 'terminate' else plan['max_steps']
        assert actor.total_steps == expected == counts['requests']
        assert counts['resets'] == counts['evaluations'] == 1 and scores == [0.125]
        assert counts['commands'] == (0 if args.case == 'empty' else 12 if args.case == 'terminate' else 2*plan['max_steps'])
        assert bool(view_sets) == (args.arm == 'taskviews')
        assert all(views == ['attempts', 'current', 'keyboard', 'lessons'] for views in view_sets)
        if args.arm=='baseline':
            from ui_kobe.osworld.kimi_native import KimiNativeAgent
            assert actor.optional_context.__func__ is KimiNativeAgent.optional_context
            assert actor.cached_context is None and not hasattr(actor,'mini_context') and not hasattr(actor,'context_provider')
        journal = actor.execution_journal
        assert journal and not journal.closed
        transitions = journal.db.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='transition'").fetchone()[0]
        assert transitions == counts['commands'] + (1 if args.case == 'terminate' else 0)
        env.close()
    assert sources(args.benchmark_repo, args.compiler_repo, args.task) == before
    write(args.output / 'validation.json', {'passed': True, 'arm': args.arm, 'case': args.case, 'provider': args.provider,
        'base_url': plan['base_url'], 'cua_contract': plan['cua_contract'], 'large_frame_fixture': large_frame_fixture,
        'counts': counts, 'round_limit': plan['max_steps'], 'view_sets': sorted(set(tuple(v) for v in view_sets)),
        'model':plan['model'], 'generation_fields':plan['generation_fields'], 'max_steps':plan['max_steps'],
        'experiment':plan['experiment'], 'task_key':plan['task_key'], 'task_id':plan['task_id'], 'domain':plan['domain'],
        'media_metric_tested_separately':args.task != 'invoice',
        'scope_limit_bytes':int((actor_scope/'memory.max').read_text()) if actor_scope else None,
        'scope_peak_bytes':int((actor_scope/'memory.peak').read_text()) if actor_scope else None,
        'memory_swap_max':int((actor_scope/'memory.swap.max').read_text()) if actor_scope else None,
        'mock_wire_reasoning_verified': plan['generation_profile']['reasoning_effort'], 'live_reasoning_verified': False,
        'source_unchanged': True, 'live_api_called': False,
        'vm_started': False, 'benchmark_score': None, 'mock_evaluator_sentinel': 0.125,
        'project_source': project_identity()})
    print(json.dumps(read_report(args.output)))


def read_report(output):
    return {key: value for key, value in json.loads((output / 'validation.json').read_text()).items()
            if key != 'project_source'}


if __name__ == '__main__':
    main()
