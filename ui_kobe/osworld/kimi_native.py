"""Thin K3 native protocol bridge to the unchanged OSWorld action compiler."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import time

from ui_kobe.api.kimi import BASE_URL, generation_profile
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import KimiStreamClient, StreamProtocolError
from . import telemetry
from .cua_contract import CUAContract, options_contract
from .native_history import compact
from .actor_context import ContextClient, protocol_feedback, repair_messages

PROTOCOL = "kimi-k3-native-tools-official-cua-v7"


def native_schema(frame):
    from mm_agents.qwen.prompts import build_tool_schema
    s = frame.screenshot
    return build_tool_schema(coordinate_type=s.coordinate_type, model_width=s.model_width,
                             model_height=s.model_height, enable_zoom=False)


def native_system(frame, task_current_date=None):
    from mm_agents.qwen.history import COLLAPSED_SCREENSHOT_TEXT
    from mm_agents.qwen.prompts import build_system_prompt
    prompt = build_system_prompt(native_schema(frame), collapsed_screenshot_text=COLLAPSED_SCREENSHOT_TEXT,
        task_current_date=task_current_date, enable_batch_actions=True)
    # Only replace XML wire-format instructions. Keep the pinned official
    # operating/date/batching rules and the exact official action schema.
    start, end = prompt.index("When using the tool,"), prompt.index("Rules:\n")
    prompt = prompt[:start] + "Use native computer_use function calls with JSON parameters.\n\n" + prompt[end:]
    prompt = prompt.replace("- Return each action as a separate complete <tool_call>...</tool_call> block; do not return an actions array.",
                            "- Return each action as a separate complete native function call; do not return an actions array.")
    return prompt


def official_compile(arguments, frame):
    from mm_agents.qwen.actions import translate_tool_calls
    from mm_agents.qwen.parser import ToolCall
    return translate_tool_calls([ToolCall(value, 0, 0) for value in arguments],
        screenshot=frame.screenshot, coordinate_type=frame.screenshot.coordinate_type, enable_zoom=False)


def validate_native(response, frame):
    """Validate native identities, then compile the entire official batch atomically."""
    from mm_agents.qwen.actions import ActionValidationError
    data = response.model_dump()
    try:
        choice = data["choices"][0]
        if choice["finish_reason"] not in ("stop", "tool_calls"):
            raise StreamProtocolError("Incomplete native candidate", retryable=True)
        arguments, identities = [], set()
        calls = choice["message"].get("tool_calls") or []
        if not isinstance(calls, list):
            raise StreamProtocolError("Native calls must be a list", code="native_tool_identity", retryable=True)
        for call in calls:
            if (not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]
                    or call["id"] in identities or call.get("type") != "function"
                    or not isinstance(call.get("function"), dict)
                    or call["function"].get("name") != "computer_use"):
                raise StreamProtocolError("Unexpected or duplicate native tool identity",
                                          code="native_tool_identity", retryable=True)
            identities.add(call["id"])
            value = json.loads(call["function"]["arguments"])
            if not isinstance(value, dict):
                raise ValueError("Native parameters must be a JSON object")
            arguments.append(value)
        return arguments, official_compile(arguments, frame)
    except StreamProtocolError:
        raise
    except ActionValidationError as exc:
        # Preserve the original coordinate/error category and offending value.
        # No clamping, unit inference or partial execution occurs.
        raise StreamProtocolError(str(exc), code=exc.code, observed_response=data, retryable=True) from exc
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise StreamProtocolError("Invalid native parameters: " + str(exc),
            code="native_parameters", observed_response=data, retryable=True) from exc


class KimiNativeAgent:
    experiment_arm = 'baseline'
    transition_recording = False
    context_label = ''

    def __init__(self, *, model, base_url, temperature, max_tokens, **options):
        self.profile = generation_profile(os.environ.get("UI_KOBE_GENERATION_PROFILE", "low-16k"))
        if (model != "kimi-k3" or base_url != BASE_URL or temperature != 1 or
                max_tokens != self.profile.max_completion_tokens):
            raise ValueError("K3 requires the declared model and generation profile")
        declared = os.environ.get("UI_KOBE_CUA_CONTRACT_JSON")
        if declared:
            expected = CUAContract(**json.loads(declared)).snapshot()
            for name, value in expected.items():
                if name in options and options[name] != value:
                    raise ValueError("Official runner option differs from frozen CUA contract: " + name)
            options = {**expected, **options}
        self.contract, self.budget, api_key, inactive = options_contract(options)
        self.tool_repair_retries = self.contract.tool_repair_retries
        trace = Path(os.environ["UI_KOBE_TELEMETRY_DIR"])
        self.transport = KimiStreamClient(api_key=api_key, budget=self.budget, profile=self.profile,
                                         emit=telemetry.emit, stream_dir=trace / "streams")
        self.client = ContextClient(self, self.transport)
        self.reset()
        telemetry.emit("native_adapter", protocol=PROTOCOL, cua_contract=self.contract.snapshot(),
            budget=self.budget.__dict__, generation_profile=self.profile.__dict__, inactive_options=inactive,
            compiler="unchanged mm_agents.qwen.actions.translate_tool_calls", terminal_status_judge=False)

    def reset(self, _logger=None):
        journal = getattr(self, 'execution_journal', None)
        if journal and not journal.closed:
            telemetry.record_transition(self, 'close')
        self.execution_journal = None
        self.turns, self.pending = [], None
        self.last_trace, self.executions, self.command_call_indices = {}, [], []
        self.action_descriptions = []
        self.cached_context = None
        self.total_steps = self.folded_prefix_count = self._ui_kobe_trace_step = 0
        self.frame = None

    def predict(self, instruction, obs):
        self.total_steps += 1
        self.view_step = self.total_steps
        self.frame = self.contract.process(obs["screenshot"], self.total_steps)
        telemetry.emit("cua_frame", **self.frame.metadata)
        self.cached_context = self.optional_context(instruction, obs)
        # Optional analysis owns a separate ledger/deadline. It cannot consume
        # actor repair/output admission or shorten this common actor window.
        deadline = time.monotonic() + self.budget.step_s
        self.step_ledger = StepLedger(self.profile, deadline, telemetry.emit,
            actor_repairs=self.contract.tool_repair_retries, advisory_repairs=self.contract.advisory_repair_retries)
        if self.pending:
            ids = [self.pending] if isinstance(self.pending, str) else self.pending
            for index, identifier in enumerate(ids):
                executions = [e for e in self.executions if e["call_index"] == index]
                self.turns[-1].append({"role": "tool", "tool_call_id": identifier,
                    "content": protocol_feedback(executions, obs.get('user_response'))})
        elif self.turns and obs.get("user_response") is not None:
            self.turns[-1].append({"role": "user", "content": str(obs["user_response"])})
        self.pending = None
        self.executions = []
        user = {"role": "user", "content": [self.frame.image]}
        system = {"role": "system", "content": native_system(self.frame, getattr(self, "task_current_date", None))}
        self.folded_prefix_count, removed, text_chars = compact(self.turns, step=self.total_steps,
            folded=self.folded_prefix_count, contract=self.contract, system=system, current=user,
            instruction=instruction, actions=self.action_descriptions)
        telemetry.emit("history_trim", history_turns_omitted=removed, retained_history_turns=len(self.turns),
                       retained_history_text_chars=text_chars, folded_prefix=self.folded_prefix_count)
        messages = [system, *(message for turn in self.turns for message in turn), user]
        telemetry.set_context(self.view_step, 'native_executor')
        response, (arguments, batch) = self.generate_candidate(self.client, "executor", deadline,
            {"model": "kimi-k3", "messages": messages, "tools": [native_schema(self.frame)], "tool_choice": "auto"},
            lambda response: validate_native(response, self.frame))
        original = response.model_dump()["choices"][0]["message"]
        ids = [call["id"] for call in original.get("tool_calls") or []]
        self.pending = ids[0] if len(ids) == 1 else (ids or None)
        self.command_call_indices = []
        for index, value in enumerate(arguments):
            self.command_call_indices.extend([index] * len(official_compile([value], self.frame).commands))
        self.turns.append([user, original])
        self.action_descriptions.append(batch.description)
        self.last_trace = {"protocol": PROTOCOL, "native_actions": arguments,
            "native_action": arguments[0] if len(arguments) == 1 else None, "native_tool_call_count": len(arguments),
            "frame": self.frame.metadata, "cua_contract": self.contract.snapshot(), "timings": self.client.last_timing,
            "history_turns_omitted": removed, "retained_history_text_chars": text_chars,
            "usage": response.model_dump().get("usage"), "step_tokens": self.step_ledger.snapshot(),
            "generation_profile": self.profile.__dict__,
            "terminal_origin": "explicit_model_tool" if batch.terminal_status else None}
        self.context_trace()
        return batch.question or original.get("content") or json.dumps(original, ensure_ascii=False), batch.commands

    def optional_context(self, instruction, obs):
        return None

    def context_delivered(self):
        pass

    def context_trace(self):
        pass

    def record_execution(self, action, *, info=None, receipts=None, error=None):
        position = len(self.executions)
        index = self.command_call_indices[position] if position < len(self.command_call_indices) else None
        self.executions.append({"call_index": index, "action": action, "info": info,
                                "controller_receipts": receipts, "error": error})

    def generate_candidate(self, transport, role, deadline, request, validator):
        """Official-style bounded validation repair with one unchanged deadline/ledger."""
        candidate, parent = 1, None
        limit = self.contract.tool_repair_retries if role == "executor" else self.contract.advisory_repair_retries
        while True:
            ledger = self.step_ledger if role == 'executor' else (getattr(self, 'advisory_ledger', None) or self.step_ledger)
            payload = deepcopy(request)
            payload.update(reasoning_effort=self.profile.reasoning_effort,
                           max_completion_tokens=ledger.allowance(role))
            observed = None
            try:
                response = transport.create(deadline=deadline, step_ledger=ledger, budget_role=role,
                    generation_attempt=candidate, parent_request_id=parent, **payload)
                observed = response.model_dump()
                return response, validator(response)
            except StreamProtocolError as exc:
                parent = getattr(exc, "request_id", getattr(transport, "last_request_id", None))
                telemetry.emit("candidate_rejected", role=role, generation_attempt=candidate,
                    request_id=parent, error_code=exc.code, error=str(exc), action_executed=False)
                if (not exc.retryable or candidate > limit or
                        not ledger.regenerate(role, self.budget.connect_s)):
                    exc.retryable = False
                    raise
                candidate += 1
                telemetry.emit("semantic_regeneration", role=role, generation_attempt=candidate,
                    parent_request_id=parent, reason=exc.code, action_executed=False,
                    step_tokens=ledger.snapshot())
                request = repair_messages(request, observed, exc, role=role)

    def close(self):
        telemetry.record_transition(self, 'close')
        self.client.close()
