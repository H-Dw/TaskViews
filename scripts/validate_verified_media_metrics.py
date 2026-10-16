"""Exercise unchanged media evaluators/getters with synthetic files and fake GUI.

No benchmark input/gold pixels, model, VM, or real GUI are used. Calls to the
official evaluate method below are synthetic integration cases, never scores.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.verified_invoice import project_identity, sources, verify_task, write  # noqa: E402
from ui_kobe.osworld.verified_runtime import load_runtime  # noqa: E402
from ui_kobe.osworld.verified_tasks import TASKS  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=('gimp', 'vlc'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home()/'osworld-verified/OSWorld')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home()/'osworld2/OSWorld-V2')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    before = sources(args.benchmark_repo, args.compiler_repo, args.task)
    task = verify_task(args.benchmark_repo, args.task)
    env_module, _, _ = load_runtime(args.benchmark_repo, args.compiler_repo, args.task)
    from desktop_env.evaluators import metrics, getters
    from PIL import Image
    metric = getattr(metrics, TASKS[args.task]['metric'])
    assert Path(sys.modules[metric.__module__].__file__).resolve().is_relative_to(args.benchmark_repo.resolve())
    assert metric.__name__ == task['evaluator']['func']
    env = env_module.DesktopEnv.__new__(env_module.DesktopEnv)
    env.evaluator, env.metric, env.metric_options = task['evaluator'], metric, {}
    env.result_getter, env.expected_getter = getters.get_vm_file, getters.get_cloud_file
    env.enable_proxy, env.action_history = False, ['DONE']
    setup_calls = []
    env.setup_controller = SimpleNamespace(setup=lambda config, proxy: setup_calls.append(config))
    cases = []
    for name, color, size in [('identical', 'white', (16,16)), ('different', 'black', (16,16)),
                              ('missing', None, (16,16)), ('size_changed', 'white', (24,24))]:
        cache = args.output/name
        cache.mkdir()
        env.cache_dir = str(cache)
        Image.new('RGB', (16,16), 'white').save(cache/task['evaluator']['expected']['dest'])
        payload = None
        if color:
            buffer = BytesIO()
            Image.new('RGB', size, color).save(buffer, format='PNG')
            payload = buffer.getvalue()
        paths = []
        def get_file(path):
            paths.append(path)
            return payload
        env.controller = SimpleNamespace(get_file=get_file)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Live network forbidden')), \
             patch.object(env_module.DesktopEnv, '__init__', side_effect=AssertionError('VM forbidden')):
            value = env.evaluate()
        expected = 0.0 if name in ('different','missing') or (name == 'size_changed' and args.task == 'gimp') else 1.0
        assert (0 <= value < 0.01 if args.task == 'vlc' and name == 'different'
                else value == expected), (args.task, name, value)
        assert paths == [task['evaluator']['result']['path']]
        assert setup_calls[-1] == task['evaluator'].get('postconfig', [])
        cases.append({'case':name, 'synthetic_value':float(value), 'passed':True})
    assert sources(args.benchmark_repo, args.compiler_repo, args.task) == before
    write(args.output/'validation.json', {'passed':True, 'task_key':args.task, 'cases':cases,
        'official_metric_module':metric.__module__, 'original_evaluate_method_used':True,
        'official_postconfig_preserved_but_mocked':True, 'source_unchanged':True,
        'live_api_called':False, 'vm_started':False, 'gui_actions':0, 'benchmark_score':None,
        'official_task_assets_opened':False, 'project_source':project_identity()})
    print(args.task + ': four synthetic evaluator/getter cases passed; no benchmark score')


if __name__ == '__main__':
    main()
