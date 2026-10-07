"""Passive, credential-safe trace hooks for the official OSWorld Qwen runner.

Hooks return original values without execution gates. Full audit evidence stays
separate from the minimal native tool reply. Only opted-in experimental arms
create transition journals. Each process writes JSONL; images use SHA-256.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import functools
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import sys

_root: Path | None = None
_context = threading.local()
_lock = threading.RLock()
_installed = False
_api_installed = False


def record_transition(agent, operation, *args, **kwargs):
    """Observer failures are durable warnings, never action/termination gates."""
    journal = getattr(agent, 'execution_journal', None)
    if journal is None and not getattr(agent, 'transition_recording', False):
        return None
    try:
        args = list(args)
        if operation in ('begin', 'decide', 'result') and args:
            args[0] = safe(args[0])
        if operation == 'begin':
            args[1] = {**args[1], 'user_response': safe(args[1].get('user_response'))}
        elif operation == 'decide':
            args[1] = safe(args[1])
        kwargs = {key: value if key == 'observation' else safe(value) for key, value in kwargs.items()}
        if operation == 'begin' and journal is None and _root is not None:
            from .cua_contract import CUAContract
            from .transitions import TransitionJournal
            contract = getattr(agent, 'contract', None)
            if contract is None:
                declared = os.environ.get('UI_KOBE_CUA_CONTRACT_JSON')
                if declared is None:
                    return None  # Other legacy runners did not declare this contract.
                contract = CUAContract(**json.loads(declared))
            journal = agent.execution_journal = TransitionJournal(_root / 'transitions',
                task_id=os.environ.get('UI_KOBE_TASK_ID', 'unknown'),
                run_id=os.environ.get('OSWORLD_FULL_RUN_ID', 'offline'), contract=contract)
        if journal is not None and not journal.closed:
            result = getattr(journal, operation)(*args, **kwargs)
            if result:
                emit('execution_journal_event', ref=journal.reference(result), journal_kind=result['kind'])
            return result
    except Exception as exc:
        emit('transition_recording_warning', operation=operation, error_type=type(exc).__name__, error=str(exc))
    return None


def safe(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if any(s in str(k).lower() for s in
                ("api_key", "authorization", "password", "cookie", "extra_headers")) else safe(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, str):
        if value.startswith("data:image/") and ";base64," in value:
            mime, encoded = value.split(";base64,", 1)
            data = base64.b64decode(encoded)
            return save_image(data, "jpg" if "jpeg" in mime else "png")
        for name in ("QWEN_API_KEY", "KIMI_API_KEY", "OPENAI_API_KEY", "GLM_API_KEY", "ANTHROPIC_API_KEY"):
            secret = os.environ.get(name)
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return safe(str(value))


def save_image(data: bytes, extension="png"):
    digest = hashlib.sha256(data).hexdigest()
    relative = f"images/{digest}.{extension}"
    result = {"image": relative, "bytes": len(data), "sha256": digest}
    try:
        if _root is not None:
            target = _root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(data)
    except OSError as exc:
        result["recording_error"] = str(exc)
        _recording_warning(exc)
    return result


def emit(kind, **fields):
    if _root is None:
        return
    try:
        record = {"time_utc": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                  "step": getattr(_context, "step", 0), "phase": getattr(_context, "phase", "harness"),
                  "event": kind, **safe(fields)}
        with _lock:
            with (_root / f"events-{os.getpid()}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError) as exc:
        _recording_warning(exc)


def _recording_warning(exc):
    try:
        print("Telemetry recording warning: " + str(exc), file=sys.stderr)
    except OSError:
        pass


def set_context(step: int, phase: str) -> None:
    _context.step, _context.phase = step, phase


def in_agent_action() -> bool:
    return getattr(_context, "phase", "harness") == "action"


def exception_causes(exc):
    """Bounded, redacted transport evidence without changing SDK retry behavior."""
    causes, seen = [], {id(exc)}
    cause = exc.__cause__
    while cause is not None and id(cause) not in seen and len(causes) < 4:
        seen.add(id(cause))
        causes.append({"type": type(cause).__name__, "error": safe(str(cause))[:1000]})
        cause = cause.__cause__
    return causes


def install_api(root: Path) -> None:
    """API-only hooks also work in the isolated TaskViews SDK interpreter."""
    global _root, _api_installed
    _root = root.resolve()
    _root.mkdir(parents=True, exist_ok=True)
    if _api_installed:
        return
    _api_installed = True
    import openai

    original_init = openai.OpenAI.__init__

    @functools.wraps(original_init)
    def client_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        original_create = self.chat.completions.create
        last_status = threading.local()

        def http_status(response):
            last_status.value = response.status_code
            emit("http_response", status_code=response.status_code,
                 method=response.request.method, url=str(response.request.url).split("?")[0])

        # The pinned SDK exposes its httpx client. No headers/body are captured.
        self._client.event_hooks.setdefault("response", []).append(http_status)

        @functools.wraps(original_create)
        def create(*call_args, **call_kwargs):
            request_id = f"{os.getpid()}-{time.time_ns()}"
            started = time.monotonic()
            last_status.value = None
            emit("api_request", request_id=request_id, endpoint=str(self.base_url), payload=call_kwargs)
            try:
                response = original_create(*call_args, **call_kwargs)
                emit("api_response", request_id=request_id, duration_s=round(time.monotonic()-started, 3),
                     status_code=last_status.value, response=response)
                return response
            except Exception as exc:
                emit("api_error", request_id=request_id, duration_s=round(time.monotonic()-started, 3),
                     status_code=getattr(exc, "status_code", last_status.value),
                     error_type=type(exc).__name__, error=str(exc), error_causes=exception_causes(exc))
                raise
        self.chat.completions.create = create

    openai.OpenAI.__init__ = client_init


def install(root: Path) -> None:
    global _installed
    install_api(root)
    if _installed:
        return
    _installed = True
    from mm_agents.qwen import QwenAgent
    from desktop_env.desktop_env import DesktopEnv
    from desktop_env.controllers.python import PythonController
    original_predict = QwenAgent.predict

    @functools.wraps(original_predict)
    def predict(self, instruction, obs):
        self._ui_kobe_trace_step = getattr(self, "_ui_kobe_trace_step", 0) + 1
        _context.step, _context.phase = self._ui_kobe_trace_step, "agent"
        _context.agent = self
        record_transition(self, 'begin', instruction, obs, step=self._ui_kobe_trace_step)
        emit("observation", instruction=instruction,
             screenshot=save_image(obs["screenshot"]) if obs.get("screenshot") else None)
        started = time.monotonic()
        try:
            response, actions = original_predict(self, instruction, obs)
            try:
                from .transitions import decision_tools
                tools = decision_tools(self)
            except Exception as exc:
                tools = []
                emit('transition_recording_warning', operation='tool_alignment', error=str(exc))
            record_transition(self, 'decide', response, actions, step=self._ui_kobe_trace_step, tools=tools)
            trace = getattr(self, 'last_trace', None)
            if trace is None:
                terminal = next((t['arguments'] for t in tools if t.get('arguments', {}).get('action') == 'terminate'), None)
                trace = {'protocol': 'official_qwen_xml', 'terminal_origin': 'explicit_model_tool' if terminal else None,
                         'native_action': terminal, 'compiled_commands': actions, 'tools': tools}
            emit("decision", duration_s=round(time.monotonic()-started, 3),
                 response=response, parsed_actions=actions,
                 framework_trace=trace)
            return response, actions
        except Exception as exc:
            record_transition(self, 'phase', 'decision_error', error=str(exc))
            emit("decision_error", error_type=type(exc).__name__, error=str(exc))
            raise
    QwenAgent.predict = predict
    original_execute = PythonController.execute_python_command

    @functools.wraps(original_execute)
    def execute(self, command):
        started = time.monotonic()
        result = original_execute(self, command)
        emit("controller_result", command=command, result=result,
             duration_s=round(time.monotonic()-started, 3))
        if in_agent_action():
            try:
                getattr(_context, 'receipts', []).append({"command": command, "result": safe(result)})
            except Exception as exc:
                emit('feedback_recording_warning', error=str(exc))
        return result
    PythonController.execute_python_command = execute
    original_step = DesktopEnv.step

    @functools.wraps(original_step)
    def step(self, action, *args, **kwargs):
        _context.phase = "action"
        _context.receipts = []
        emit("action_start", action=action)
        started = time.monotonic()
        try:
            obs, reward, done, info = original_step(self, action, *args, **kwargs)
            record_transition(getattr(_context, 'agent', None), 'result', action,
                step=getattr(_context, 'step', 0), observation=obs, receipts=_context.receipts, info=info)
            emit("action_result", action=action, reward=reward, done=done, info=info,
                 duration_s=round(time.monotonic()-started, 3),
                 screenshot=save_image(obs["screenshot"]) if obs.get("screenshot") else None)
            recorder = getattr(getattr(_context, "agent", None), "record_execution", None)
            if recorder:
                try:
                    recorder(action, info=safe(info), receipts=_context.receipts)
                except Exception as record_error:
                    emit('feedback_recording_warning', error=str(record_error))
            return obs, reward, done, info
        except Exception as exc:
            record_transition(getattr(_context, 'agent', None), 'result', action,
                step=getattr(_context, 'step', 0), receipts=_context.receipts, error=str(exc))
            emit("action_error", action=action, error_type=type(exc).__name__, error=str(exc))
            recorder = getattr(getattr(_context, "agent", None), "record_execution", None)
            if recorder:
                try:
                    recorder(action, receipts=_context.receipts, error=safe(str(exc)))
                except Exception as record_error:
                    emit('feedback_recording_warning', error=str(record_error))
            raise
    DesktopEnv.step = step
    original_evaluate = DesktopEnv.evaluate

    @functools.wraps(original_evaluate)
    def evaluate(self, *args, **kwargs):
        _context.phase = "judge"
        from .lifecycle import write_phase
        if _root is not None:
            write_phase(_root.parent, "evaluating")
        emit("evaluation_start")
        record_transition(getattr(_context, 'agent', None), 'phase', 'evaluation_start')
        started = time.monotonic()
        try:
            score = original_evaluate(self, *args, **kwargs)
            emit("evaluation_result", score=score, duration_s=round(time.monotonic()-started, 3))
            record_transition(getattr(_context, 'agent', None), 'phase', 'evaluation_result', score=score)
            if _root is not None:
                write_phase(_root.parent, "evaluation_returned", evaluation_returned=True, raw_official_score=safe(score))
            return score
        except Exception as exc:
            emit("evaluation_error", error_type=type(exc).__name__, error=str(exc))
            record_transition(getattr(_context, 'agent', None), 'phase', 'evaluation_error', error=str(exc))
            raise
    DesktopEnv.evaluate = evaluate
    original_close = DesktopEnv.close

    @functools.wraps(original_close)
    def close(self, *args, **kwargs):
        from .lifecycle import write_phase
        if _root is not None:
            write_phase(_root.parent, "closing")
        try:
            result = original_close(self, *args, **kwargs)
        except BaseException as exc:
            emit("environment_close_error", error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            agent = getattr(_context, 'agent', None)
            recorder = getattr(agent, 'flush_execution', None)
            if recorder:
                try:
                    recorder()
                except Exception as exc:
                    emit('feedback_recording_warning', error=safe(str(exc)))
            record_transition(agent, 'close')
            closer = getattr(agent, 'close', None)
            if closer:
                try:
                    closer()
                except Exception as exc:
                    emit('agent_close_warning', error=safe(str(exc)))
        if _root is not None:
            write_phase(_root.parent, "closed")
        return result

    DesktopEnv.close = close
    emit("telemetry_installed", notes="Passive official execution/evaluation/close hooks; native K3 reasoning preserved")
