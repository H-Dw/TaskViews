"""Passive runner phase evidence; official runner alone decides task endings."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def write_phase(stage, phase, **evidence):
    if phase not in {"running", "evaluating", "evaluation_returned", "closing", "closed", "runner_exited"}:
        raise ValueError("Unknown official runner phase")
    path = Path(stage) / "runner-lifecycle.json"
    previous = read_phase(stage)
    value = {**previous, "phase": phase, "time_utc": datetime.now(timezone.utc).isoformat(), **evidence}
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        # Recording cannot replace an official close/evaluate return or error.
        _warning(exc)
        value["recording_error"] = str(exc)
    return value


def read_phase(stage):
    try:
        value = json.loads((Path(stage) / "runner-lifecycle.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        # Missing/invalid evidence grants no teardown exemption.
        _warning(exc)
        return {}


def _warning(exc):
    try:
        print("Lifecycle recording warning: " + str(exc), file=sys.stderr)
    except OSError:
        pass


def is_teardown(stage):
    return read_phase(stage).get("phase") in {"closing", "closed", "runner_exited"}
