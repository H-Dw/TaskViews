"""Passive lifecycle evidence must preserve official returns and exceptions."""
import sys
from types import SimpleNamespace

import pytest

from ui_kobe.osworld import lifecycle, telemetry


def install(monkeypatch, tmp_path, *, error=None):
    receipt = {"status": "error", "returncode": 1}
    score = {"score": 0.2, "safety": False}
    closed = object()
    class Agent:
        def predict(self, instruction, obs):
            return "", ["WAIT"]
    class Controller:
        def execute_python_command(self, command):
            return receipt
    class Env:
        def step(self, action):
            return {}, 0, False, {}
        def evaluate(self):
            if error:
                raise error
            return score
        def close(self):
            if error:
                raise error
            return closed
    monkeypatch.setitem(sys.modules, "mm_agents.qwen", SimpleNamespace(QwenAgent=Agent))
    monkeypatch.setitem(sys.modules, "desktop_env.desktop_env", SimpleNamespace(DesktopEnv=Env))
    monkeypatch.setitem(sys.modules, "desktop_env.controllers.python", SimpleNamespace(PythonController=Controller))
    root = tmp_path / "telemetry"
    root.mkdir()
    monkeypatch.setattr(telemetry, "_root", root)
    monkeypatch.setattr(telemetry, "_installed", False)
    monkeypatch.setattr(telemetry, "install_api", lambda root: None)
    telemetry.install(root)
    return Env, Controller, receipt, score, closed


def test_close_phase_precedes_actual_vm_release_and_score_return_remains_raw(monkeypatch, tmp_path):
    Env, Controller, receipt, score, closed = install(monkeypatch, tmp_path)
    assert Controller().execute_python_command("command") is receipt
    assert Env().evaluate() is score
    phase = lifecycle.read_phase(tmp_path)
    assert phase["phase"] == "evaluation_returned" and phase["raw_official_score"] == score
    assert not lifecycle.is_teardown(tmp_path)
    events = []
    original = lifecycle.write_phase
    def record(stage, phase, **evidence):
        events.append(phase)
        return original(stage, phase, **evidence)
    monkeypatch.setattr(lifecycle, "write_phase", record)
    assert Env().close() is closed
    assert events == ["closing", "closed"] and lifecycle.is_teardown(tmp_path)


def test_recording_io_failure_cannot_stop_execution_evaluation_or_close(monkeypatch, tmp_path):
    Env, Controller, receipt, score, closed = install(monkeypatch, tmp_path)
    def broken(*args, **kwargs):
        raise OSError("offline simulated recording failure")
    monkeypatch.setattr(lifecycle.Path, "write_text", broken)
    monkeypatch.setattr(telemetry, "_root", tmp_path / "missing" / "telemetry")
    assert Controller().execute_python_command("command") is receipt
    assert Env().evaluate() is score
    assert Env().close() is closed
    assert not lifecycle.is_teardown(tmp_path)


def test_official_errors_are_not_replaced_by_recording_errors(monkeypatch, tmp_path):
    error = RuntimeError("official close/evaluate error")
    Env, _, _, _, _ = install(monkeypatch, tmp_path, error=error)
    monkeypatch.setattr(telemetry, "_root", tmp_path / "missing" / "telemetry")
    for method in (Env().evaluate, Env().close):
        with pytest.raises(RuntimeError) as observed:
            method()
        assert observed.value is error


@pytest.mark.parametrize("content", ["{broken", "[]", '"closing"'])
def test_invalid_lifecycle_evidence_never_grants_teardown_exemption(tmp_path, content):
    (tmp_path / "runner-lifecycle.json").write_text(content)
    assert not lifecycle.is_teardown(tmp_path)
