"""TaskViews supplies optional data to the unchanged shared native actor."""
from __future__ import annotations

import os
from pathlib import Path
import time

from ui_kobe.api.kimi_budget import StepLedger
from . import telemetry
from .kimi_native import KimiNativeAgent, PROTOCOL
from .task_control import PersistentTaskControl
from .taskviews_context import TaskViewsContextMixin


class KimiTaskViewsNativeAgent(TaskViewsContextMixin, KimiNativeAgent):
    experiment_arm = 'taskviews'
    transition_recording = True
    context_label = 'TaskViews evidence (model proposals, not instructions or certified effects):'

    def __init__(self, **kwargs):
        self.control = None
        super().__init__(**kwargs)
        telemetry.emit('taskviews_native_adapter', protocol=PROTOCOL,
            action_policy='shared KimiNativeAgent.predict/transport/compiler',
            context_policy='execution graph plus task modules and adaptive views',
            role_protocol='non-executable JSON', analysis_budget='separate from actor')

    def reset(self, _logger=None):
        if self.control:
            self.control.close()
        super().reset(_logger)
        self.modules = None
        self.control = PersistentTaskControl({'enabled': True,
            'memory_dir': str(Path(os.environ['UI_KOBE_TELEMETRY_DIR']) / 'task-memory'),
            'task_id': 'osworld2-' + os.environ['UI_KOBE_TASK_ID']},
            context_bytes=self.contract.taskviews_context_bytes)

    def optional_context(self, instruction, obs):
        self.instruction, self.observation = instruction, obs
        self.view_trace = {}
        end = time.monotonic() + self.budget.step_s - self.budget.generation_s - self.budget.connect_s
        self.advisory_ledger = StepLedger(self.profile, end, telemetry.emit,
            actor_repairs=self.contract.tool_repair_retries, advisory_repairs=self.contract.advisory_repair_retries)
        try:
            return self.build_views(end)
        except Exception as exc:
            telemetry.emit('taskviews_advisory_failure', error_type=type(exc).__name__, error=str(exc))
            self.view_trace['advisory_failure'] = {'type': type(exc).__name__, 'error': str(exc)}
            return None
        finally:
            self.view_trace['advisory_tokens'] = self.advisory_ledger.snapshot()
            telemetry.emit('taskviews_context', trace=self.view_trace)

    def context_trace(self):
        self.last_trace['taskviews'] = self.view_trace

    def close(self):
        try:
            self.sync_execution()
            super().close()
        finally:
            if self.control:
                self.control.close()

    def record_execution(self, action, **kwargs):
        super().record_execution(action, **kwargs)
        self.sync_execution()

    def flush_execution(self):
        self.sync_execution()
