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
from .agent import bounded_visual_evidence
from .actions import json_object
from .kimi_native import KimiNativeAgent
from .task_control import PersistentTaskControl, TaskControlBlocked, SEMANTIC_PERCEPTION, CONTROLLER, ADVISER, VERIFIER
from ui_kobe.api.kimi_stream import StreamProtocolError, StreamDeadlineError
from ui_kobe.api.kimi_budget import StepTokenBudgetError


PROTOCOL = "kimi-k3-native-tools-taskviews-official-cua-v5"


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
            except (ValueError, KeyError, TypeError, TaskControlBlocked, StepTokenBudgetError, StreamDeadlineError) as exc:
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
        self.last_timing = self.transport.last_timing
        self.last_request_id = getattr(self.transport, 'last_request_id', None)
        return response

    def close(self):
        self.transport.close()


class KimiTaskViewsNativeAgent(KimiNativeAgent):
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

    def role(self, name, prompt, context, image, deadline, validator):
        telemetry.set_context(self.view_step, name)
        def validate(response):
            value = response.model_dump()["choices"][0]
            if value["finish_reason"] != "stop" or value["message"].get("tool_calls"):
                raise StreamProtocolError("Adviser must return complete JSON without executable tools",
                                          code='invalid_adviser_response', retryable=True)
            try:
                parsed = json_object(value["message"]["content"])
                validator(parsed)
                return parsed
            except (ValueError, TypeError, KeyError) as exc:
                raise StreamProtocolError("Invalid " + name + " JSON/schema: " + str(exc),
                                          code='invalid_adviser_json', retryable=True) from exc
        _, value = self.generate_candidate(self.transport, name, deadline,
            {'model': 'kimi-k3', 'messages': [{"role": "system", "content": prompt}, {"role": "user", "content": [
                {"type": "text", "text": dumps(context)}, image]}], 'response_format': {"type": "json_object"}}, validate)
        return value

    def build_views(self, deadline):
        control = self.control
        control.initialize(self.instruction)
        core = control._core()
        frame = self.frame.metadata["frame_id"]
        import base64
        image = self.frame.image
        screenshot = self.frame.screenshot
        width, height = screenshot.model_width, screenshot.model_height
        model_bytes = base64.b64decode(screenshot.data_url.split(",", 1)[1])
        inventory = control.inventory()
        request = control._context(core, extra={"frame": self.frame.metadata, "image_size": [width, height],
            "semantic_schema": inventory["schema"], "entity_ids": [e["id"] for e in inventory["entities"]],
            "omitted_entity_ids": inventory["omitted_entities"]})
        def validate_perception(raw):
            if set(raw) != {"summary", "elements", "semantics"}:
                raise ValueError("Perception requires summary, elements, semantics")
            bounded_visual_evidence({k: raw[k] for k in ("summary", "elements")}, width, height)
            semantics = raw["semantics"]
            if (not isinstance(semantics, dict) or set(semantics) != {"entities", "claims"} or
                    not isinstance(semantics["entities"], list) or len(semantics["entities"]) > 32 or
                    not isinstance(semantics["claims"], list) or len(semantics["claims"]) > 64):
                raise ValueError("Semantics requires <=32 entities and <=64 claims")
            control.memory.validate_proposal_structure(semantics)
        prompt = SEMANTIC_PERCEPTION + "\nBounding boxes are in the supplied MODEL IMAGE pixels. " + self.frame.instruction
        raw = self.role("perception", prompt, request, image, deadline, validate_perception)
        evidence, normalization = bounded_visual_evidence({k: raw[k] for k in ("summary", "elements")}, width, height)
        core = control.observe(self.instruction, frame, model_bytes, raw, evidence)
        snapshot = control.memory.read()
        def validate_controller(proposed):
            if set(proposed) != {"stage", "needs"} or not isinstance(proposed["stage"], str):
                raise ValueError("View controller requires stage and needs")
            if not isinstance(proposed["needs"], list) or not any(n.get("consumer") == "executor"
                    for n in proposed["needs"] if isinstance(n, dict)):
                raise ValueError("View controller must assign the executor")
            fields = {"id", "consumer", "purpose", "anchors", "focus_predicates", "max_hops"}
            if any(not isinstance(need, dict) or set(need) != fields for need in proposed["needs"]):
                raise ValueError("Every need requires the six documented fields")
            needs, _ = control._resolve_core_anchors(snapshot, core, proposed["needs"])
            control.views.validate_needs(snapshot, needs)
        proposed = self.role("view_controller", CONTROLLER,
            control._context(core, extra={"graph_inventory": control.inventory(),
                "consumer_allowed_anchors": control.views.allowed_anchor_inventory(snapshot),
                "frame": self.frame.metadata}), image, deadline, validate_controller)
        needs, resolutions = control._resolve_core_anchors(snapshot, core, proposed["needs"])
        compiled = control.views.compile(snapshot, needs, control.budget - len(dumps(core).encode()) - 1024)
        control.views.dispatch(compiled)
        advisers = {}
        for role, prompt in (("planner", ADVISER), ("verifier", VERIFIER)):
            packet = control.views.packet_for(role)
            if not packet["needs"]:
                continue
            context = control._context(core, packet, extra={"stage": proposed["stage"]})
            def validate_report(report):
                if role == "planner":
                    valid = set(report) == {"advice", "needed_evidence"} and isinstance(report["advice"], str)
                    valid = valid and control._strings(report["needed_evidence"])
                else:
                    valid = (set(report) == {"assessment", "quotes", "gaps"}
                             and report["assessment"] in {"verified", "unknown", "failed"}
                             and control._strings(report["quotes"]) and control._strings(report["gaps"]))
                if not valid or len(dumps(report).encode()) > 6000:
                    raise ValueError("Invalid bounded " + role + " report (maximum 6000 bytes)")
            report = self.role(role, prompt, context, image, deadline, validate_report)
            advisers[role] = {"report": report, "grade": "model_proposal", "graph_revision": snapshot.revision}
            if "assigned_views" in context:
                control.views.acknowledge(role, compiled["dispatch_id"], snapshot.revision)
        executor = control._context(core, control.views.packet_for("executor"), extra={"advisers": advisers})
        self.view_trace = {"frame": self.frame.metadata, "stage": proposed["stage"], "normalization": normalization,
                           "controller": proposed, "anchor_resolutions": resolutions,
                           "dispatch": compiled, "executor_context": executor, "advisers": advisers}
        return dumps(executor)

    def close(self):
        try:
            super().close()
        finally:
            if self.control:
                self.control.close()
