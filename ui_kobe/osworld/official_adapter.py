"""TaskViews reset/predict adapter for OSWorld's unchanged official runner."""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from multiprocessing.util import Finalize

from .process import AgentProcess
from . import telemetry


def install_taskviews_execution_guard(controller_type=None):
    """Check TaskViews GUI execution after the passive hook has saved its result.

    This runtime wrapper leaves setup, judging and the baseline runner unchanged.
    """
    from .runner import checked_execution_result
    if controller_type is None:
        from desktop_env.controllers.python import PythonController
        controller_type = PythonController
    if getattr(controller_type, "_ui_kobe_checked_actions", False):
        return
    original = controller_type.execute_python_command

    @functools.wraps(original)
    def execute(self, command):
        result = original(self, command)
        if telemetry.in_agent_action():
            try:
                return checked_execution_result(result)
            except RuntimeError:
                telemetry.emit("execution_unconfirmed", command=command, result=result)
                raise
        return result

    controller_type.execute_python_command = execute
    controller_type._ui_kobe_checked_actions = True


class TaskViewsOfficialAgent:
    def __init__(self, *, model, base_url, temperature, max_tokens, feedback_verifier=None, **runner_options):
        if feedback_verifier is not None and not callable(feedback_verifier):
            raise ValueError("feedback_verifier must be a trusted callable")
        self.feedback_verifier = feedback_verifier
        project = Path(__file__).resolve().parents[2]
        config = Path(os.environ["UI_KOBE_TASKVIEWS_CONFIG"])
        data = json.loads(config.read_text(encoding="utf-8"))
        if (data["api"]["model"] != model or data["api"]["base_url"] != base_url
                or data["agent"]["temperature"] != temperature
                or data["agent"]["max_output_tokens"] != max_tokens
                or data["agent"].get("top_p", 0.9) != runner_options.get("top_p", 0.9)):
            raise ValueError("TaskViews and official runner model/generation settings differ")
        if runner_options.get("enable_thinking") or runner_options.get("stream") or runner_options.get("enable_batch_actions"):
            raise ValueError("TaskViews comparison requires thinking, streaming and batch actions disabled")
        install_taskviews_execution_guard()
        self._task_control_enabled = data["agent"].get("task_control", {}).get("enabled", False)
        if self._task_control_enabled:
            from .feedback import install_feedback_hooks
            install_feedback_hooks()
        os.environ["PYTHONPATH"] = str(project) + os.pathsep + os.environ.get("PYTHONPATH", "")
        trace_dir = Path(os.environ["UI_KOBE_TELEMETRY_DIR"])
        trace_dir.mkdir(parents=True, exist_ok=True)
        self._stderr = (trace_dir / f"agent-stderr-{os.getpid()}.log").open("a", encoding="utf-8")
        self.worker = AgentProcess(os.environ["UI_KOBE_AGENT_PYTHON"], config, stderr=self._stderr, model=model)
        self.last_trace = {}
        self._finalizer = Finalize(None, self.close, exitpriority=10)
        telemetry.emit("framework_adapter", config=str(config), model=model, base_url=base_url,
                       differences="TaskViews perception + graph projections + JSON actions replace the Qwen XML policy")

    def reset(self, _logger=None):
        self.worker.reset()
        self.last_trace = {}
        self._ui_kobe_trace_step = 0
        telemetry.emit("framework_reset", runtime=self.worker.metadata)

    def predict(self, instruction, obs):
        if self._task_control_enabled:
            from .feedback import action_owner
            self._execution_result = None
            action_owner.set(self)
        try:
            response, actions = self.worker.predict(instruction, obs, seconds=480)
        except Exception:
            if self._task_control_enabled:
                action_owner.set(None)
            raise
        finally:
            self.last_trace = self.worker.last_trace
        return response, actions

    def close(self):
        try:
            self.worker.close()
        finally:
            self._stderr.close()
