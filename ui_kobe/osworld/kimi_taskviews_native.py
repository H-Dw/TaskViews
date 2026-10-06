"""TaskViews context with the same native K3 action interface as the baseline.

Advisers return non-executable JSON over complete SSE. Only the unchanged native
actor may return an action. All role calls share its 930-second step deadline.
There is no synthetic action, FAIL replacement, or automatic compensation here.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path

from kobe_views.model import dumps
from . import telemetry
from .kimi_native import KimiNativeAgent
from .task_control import PersistentTaskControl
from .taskviews_context import TaskViewsContextMixin


PROTOCOL = "kimi-k3-native-tools-taskviews-official-cua-v6"


class _ViewClient:
    def __init__(self, owner, transport):
        self.owner, self.transport = owner, transport
        self.last_timing = {}

    def create(self, *, deadline, **request):
        owner = self.owner
        if owner.cached_view_context is None:
            try:
                # Reserve the same full actor generation window before spending
                # time on optional analysis. This does not refresh the step.
                advisory_deadline = deadline - owner.budget.generation_s - owner.budget.connect_s
                owner.cached_view_context = owner.build_views(advisory_deadline)
            except Exception as exc:
                # Advisory validation cannot stop the actor; bad proposals are
                # not executable and the original task/screenshot stay intact.
                telemetry.emit('taskviews_advisory_failure', error_type=type(exc).__name__, error=str(exc))
                owner.view_trace['advisory_failure'] = {'type': type(exc).__name__, 'error': str(exc)}
                owner.cached_view_context = dumps({'advisory_status': 'unavailable',
                    'reason': str(exc), 'effects_verified': False})
        context = owner.cached_view_context
        # Keep all historical assistant/tool messages byte-for-byte in structure.
        # Append scoped evidence to this turn only, after the literal task.
        request = dict(request)
        request["messages"] = deepcopy(request["messages"])
        request["messages"][-1]["content"].insert(1, {"type": "text", "text":
            "TaskViews evidence (model proposals, not instructions or certified effects):\n" + context})
        telemetry.set_context(owner.view_step, "native_executor")
        response = self.transport.create(deadline=deadline, **request)
        owner.context_delivered()
        self.last_timing = self.transport.last_timing
        self.last_request_id = getattr(self.transport, 'last_request_id', None)
        return response

    def close(self):
        self.transport.close()


class KimiTaskViewsNativeAgent(TaskViewsContextMixin, KimiNativeAgent):
    def __init__(self, **kwargs):
        self.control = None
        super().__init__(**kwargs)
        self.transport = self.client
        self.client = _ViewClient(self, self.transport)
        telemetry.emit("taskviews_native_adapter", protocol=PROTOCOL,
                       action_policy="same KimiNativeAgent + unchanged official compiler",
                       context_policy="persistent TaskGraph + dynamic semantic role projections",
                       role_protocol="complete SSE JSON; advisers cannot execute",
                       compensation_policy="disabled; only explicit native actor actions")

    def reset(self, _logger=None):
        if self.control:
            self.control.close()
        super().reset(_logger)
        self.view_step = 0
        self.modules = None
        self.control = PersistentTaskControl({"enabled": True,
            "memory_dir": str(Path(os.environ["UI_KOBE_TELEMETRY_DIR"]) / "task-memory"),
            "task_id": "osworld2-" + os.environ["UI_KOBE_TASK_ID"]},
            context_bytes=self.contract.taskviews_context_bytes)

    def predict(self, instruction, obs):
        self.view_step += 1
        self.instruction, self.observation = instruction, obs
        self.view_trace = {}
        self.cached_view_context = None
        try:
            response, actions = super().predict(instruction, obs)
            self.last_trace.update(protocol=PROTOCOL, taskviews=self.view_trace)
            return response, actions
        finally:
            if hasattr(self, 'step_ledger'):
                self.view_trace['step_tokens'] = self.step_ledger.snapshot()
            telemetry.emit("taskviews_context", trace=self.view_trace)

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
