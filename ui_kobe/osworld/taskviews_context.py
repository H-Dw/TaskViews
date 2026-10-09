"""Non-executable TaskViews context shared by official XML and native pairs."""
from __future__ import annotations

from kobe_views.model import dumps
from . import telemetry
from .agent import bounded_visual_evidence
from .actions import json_object
from .task_control import SEMANTIC_PERCEPTION, CONTROLLER, ADVISER, VERIFIER
from ui_kobe.api.kimi_stream import StreamProtocolError


class TaskViewsContextMixin:
    def context_delivered(self):
        if getattr(self, 'modules', None):
            context = self.view_trace.get('executor_context', {})
            self.modules.delivered(views='assigned_views' in context,
                events=bool(context.get('role_evidence', {}).get('execution_modules')))

    def sync_execution(self):
        journal = getattr(self, 'execution_journal', None)
        if journal is None or journal.closed or self.control.memory is None:
            return
        from kobe_views.execution_modules import ExecutionModules
        if getattr(self, 'modules', None) is None:
            self.modules = ExecutionModules(self.control.memory, journal)
        self.modules.sync()

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
        journal = getattr(self, 'execution_journal', None)
        if journal is not None and control.memory is None:
            # Episode reset creates independent memories; no previous-run goals
            # or effects leak into a fresh official reset.
            control.directory = journal.directory / 'task-memory' / journal.episode_id
        control.initialize(self.instruction)
        self.sync_execution()
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
            "omitted_entity_ids": inventory["omitted_entities"],
            "execution_modules": self.modules.packet() if getattr(self, 'modules', None) else None})
        def validate_perception(raw):
            if not {"summary", "elements", "semantics"} <= set(raw) or set(raw) - {"summary", "elements", "semantics", "ui_state"}:
                raise ValueError("Perception requires summary, elements, semantics")
            if 'ui_state' in raw:
                state = raw['ui_state']
                if (not isinstance(state, dict) or set(state) != {'page_id', 'fields'}
                        or state['page_id'] is not None and (not isinstance(state['page_id'], str) or len(state['page_id']) > 256)
                        or not isinstance(state['fields'], dict) or len(state['fields']) > 32 or len(dumps(state)) > 6000):
                    raise ValueError('Optional ui_state requires bounded page_id and fields')
                from kobe_views.task_memory import _credential_safe, _contains_geometry
                _credential_safe(state)
                if _contains_geometry(state):
                    raise ValueError('UI state fields cannot contain pointer geometry')
            bounded_visual_evidence({k: raw[k] for k in ("summary", "elements")}, width, height)
            semantics = raw["semantics"]
            if (not isinstance(semantics, dict) or set(semantics) != {"entities", "claims"} or
                    not isinstance(semantics["entities"], list) or len(semantics["entities"]) > 32 or
                    not isinstance(semantics["claims"], list) or len(semantics["claims"]) > 64):
                raise ValueError("Semantics requires <=32 entities and <=64 claims")
            control.memory.validate_proposal_structure(semantics)
        prompt = (SEMANTIC_PERCEPTION + '\nKeep this read concise: prefer <=8 entities and <=12 claims; '
            'report only new task-relevant evidence. Empty lists are valid. Do not enumerate old history. '
            'All limits count reasoning plus JSON output.\nOptionally add ui_state={page_id:str|null,fields:object}. '
            'Use a page identity only when supported by this screenshot; preserve visible state fields. '
            'These are model proposals, not verified effects. Never put pointer coordinates in fields.\n'
            'Bounding boxes are in the supplied MODEL IMAGE pixels. ' + self.frame.instruction)
        raw = self.role("perception", prompt, request, image, deadline, validate_perception)
        evidence, normalization = bounded_visual_evidence({k: raw[k] for k in ("summary", "elements")}, width, height)
        core = control.observe(self.instruction, frame, model_bytes, raw, evidence)
        if getattr(self, 'checkpoint_reads', False):
            admitted = control.observation_meta.get('semantic_proposals', {})
            if not admitted.get('accepted') or admitted.get('rejected'):
                raise ValueError('Current-frame semantic evidence rejected: ' + dumps(admitted.get('rejected', [])))
        journal = getattr(self, 'execution_journal', None)
        if journal and journal.current and raw.get('ui_state'):
            import hashlib
            sha = hashlib.sha256(model_bytes).hexdigest()
            # The preceding action output and next input can share exact pixels,
            # while remaining separate observations. No visual page matching.
            candidates = []
            cursor = 0
            while rows := journal.read(cursor):
                candidates.extend(r for r in rows if r['kind'] == 'observation')
                candidates = candidates[-2:]
                cursor = rows[-1]['seq']
            for observation in candidates:
                if observation['images']['model']['sha256'] == sha:
                    state = raw['ui_state']
                    journal.annotate(observation['id'], logical_page=state['page_id'], state_schema=state['fields'],
                                     evidence_ref=str(control.observation_meta['semantic_evidence_ref']))
            self.sync_execution()
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
        # Put the selector table in the mandatory controller input. Optional
        # module/history packets must never evict the IDs required for validation.
        selectors = control.views.allowed_anchor_inventory(snapshot, limit=16)
        controller_input = {'mandatory_core': core, 'role_evidence': {'consumer_allowed_anchors': selectors,
                            'frame': self.frame.metadata, 'semantic_schema': inventory['schema']}}
        if len(dumps(controller_input).encode()) > control.budget:
            raise ValueError('Mandatory controller input exceeds context budget')
        proposed = self.role("view_controller", CONTROLLER + '\nPrefer one executor need. '
            'Add planner/verifier only when needed. Copy exact entity IDs from the selector table; '
            'claim IDs, module IDs and labels are not entity selectors.',
            controller_input, image, deadline, validate_controller)
        needs, resolutions = control._resolve_core_anchors(snapshot, core, proposed["needs"])
        # Leave room for the module packet (<=6k), two reports (<=12k),
        # and omission/change metadata. They should not lose to page history.
        residual = control.budget - len(dumps({'mandatory_core': core}).encode()) - 1024
        if residual <= 0:
            raise ValueError('Mandatory core leaves no positive view budget')
        # Reserve is proportional to the actual core, not a second fixed 20k
        # subtraction. Whole optional reports still pass _context admission.
        compiled = control.views.compile(snapshot, needs, min(16000, residual))
        control.views.dispatch(compiled)
        if getattr(self, 'modules', None):
            module = self.modules.select(proposed['stage'], needs, frame=frame,
                                         ref=control.observation_meta['screenshot_ref'])
            changes = self.modules.view_changes(compiled)
        else:
            module, changes = None, {}
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
            if getattr(self, 'modules', None):
                self.modules.report(role, report, frame=frame)
            if "assigned_views" in context:
                control.views.acknowledge(role, compiled["dispatch_id"], snapshot.revision)
        executor = control._context(core, control.views.packet_for("executor"), extra={"advisers": advisers,
            'execution_modules': self.modules.packet() if getattr(self, 'modules', None) else None,
            'view_change': {k: changes.get('executor', {}).get(k) for k in ('reset', 'base_revision', 'revision', 'changed')}})
        self.view_trace = {"frame": self.frame.metadata, "stage": proposed["stage"], "normalization": normalization,
                           "controller": proposed, "anchor_resolutions": resolutions,
                           "dispatch": compiled, "executor_context": executor, "advisers": advisers,
                           'module_id': module, 'view_changes': changes}
        return dumps(executor)
