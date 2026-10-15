"""Task-scoped OSWorld-Verified imports, without changing upstream source.

The benchmark's environment, setup, runner, getters and PDF metric come from
OSWorld-1. Only the common actor's Qwen compiler/prompt helpers come from V2.
Unrelated OCR/model evaluators are not imported by this single-task registry.
"""
from __future__ import annotations

import importlib
import importlib.machinery
import sys
import types
from pathlib import Path


def namespace(name, path):
    if name in sys.modules:
        raise RuntimeError('Use a fresh process; module already loaded: ' + name)
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    module.__spec__.submodule_search_locations = module.__path__
    sys.modules[name] = module
    return module


def load_runtime(benchmark_repo, compiler_repo):
    benchmark_repo, compiler_repo = Path(benchmark_repo).resolve(), Path(compiler_repo).resolve()
    if any(name in sys.modules for name in ('desktop_env', 'mm_agents', 'lib_run_single')):
        raise RuntimeError('OSWorld-Verified requires an isolated interpreter')
    sys.path.insert(0, str(benchmark_repo))
    namespace('mm_agents', compiler_repo / 'mm_agents').__path__.append(str(benchmark_repo / 'mm_agents'))
    # Register only the exact unchanged functions referenced by this task.
    metrics = namespace('desktop_env.evaluators.metrics', benchmark_repo / 'desktop_env/evaluators/metrics')
    getters = namespace('desktop_env.evaluators.getters', benchmark_repo / 'desktop_env/evaluators/getters')
    chrome = importlib.import_module('desktop_env.evaluators.metrics.chrome')
    files = importlib.import_module('desktop_env.evaluators.getters.file')
    metrics.compare_pdfs = chrome.compare_pdfs
    getters.get_vm_file = files.get_vm_file
    getters.get_cloud_file = files.get_cloud_file
    env = importlib.import_module('desktop_env.desktop_env')
    runner = importlib.import_module('lib_run_single')
    qwen = importlib.import_module('mm_agents.qwen')
    return env, runner, qwen


def reset_compatible(actor_class):
    """OSWorld-1 passes vm_ip to reset; this screenshot actor does not use it."""
    class VerifiedActor(actor_class):
        def reset(self, _logger=None, *, vm_ip=None):
            return super().reset(_logger)
    VerifiedActor.__name__ = 'Verified' + actor_class.__name__
    return VerifiedActor
