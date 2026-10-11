"""Offline regression and source audit in one registered 128 MiB zero-swap scope.

Fresh interpreters replace this process with exec, avoiding a resident Python
reporter alongside SDK-heavy tests. The PID and resource scope remain the same.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def restore_cwd():
    # Re-enter through the filesystem root rather than retain an inherited
    # DrvFS cwd reference across exec. Tests and config discovery need PROJECT.
    os.chdir(PROJECT.anchor)
    os.chdir(PROJECT)


def _next(state_path, *, worker=False):
    # Tests may enter temporary runner directories. Restore a durable cwd
    # before exec; otherwise the next pytest cannot initialize after removal.
    restore_cwd()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "UI_KOBE_OFFICIAL_REPO": state["official_repo"],
           "PYTHONPATH": os.pathsep.join([str(PROJECT), state["official_repo"],
                                         *([state["dev_site_packages"]] if state["dev_site_packages"] else [])])}
    command = [sys.executable, str(Path(__file__).resolve()), "--state", str(state_path)]
    if worker:
        command.append("--worker")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(sys.executable, command, env)


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def __getattr__(self, name):
        return getattr(self.streams[0], name)

    def write(self, value):
        for stream in self.streams:
            stream.write(value)
        return len(value)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-repo", type=Path, default=Path.home() / "osworld2/OSWorld-V2")
    parser.add_argument("--dev-site-packages", type=Path)
    parser.add_argument("--ruff", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT / "validation/offline.json")
    parser.add_argument("--tests", nargs="*")
    parser.add_argument("--state", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from scripts.osworld_native_experiment import require_scope, project_snapshot, now, write
    group = require_scope(128 * 1024**2)
    restore_cwd()  # Initialize each fresh interpreter, not only its predecessor.
    if not args.state:
        if args.ruff is None:
            parser.error("--ruff is required")
        sys.path.insert(1, str(args.official_repo))
        if args.dev_site_packages:
            sys.path.append(str(args.dev_site_packages))
        from ui_kobe.osworld.official_base import verify_official_base
        from ui_kobe.osworld.runner import source_snapshot
        before = source_snapshot(args.official_repo)
        official = verify_official_base(args.official_repo)
        lint = subprocess.run([str(args.ruff), "check", "ui_kobe", "kobe_views", "scripts", "tests"],
                              cwd=PROJECT, capture_output=True, text=True)
        print(lint.stdout + lint.stderr, end="", flush=True)
        files = [str(PROJECT / "tests" / p) for p in args.tests] if args.tests else [
            str(p) for p in sorted((PROJECT / "tests").glob("test_*.py"))]
        logs = args.output.parent / (args.output.stem + "-suites")
        logs.mkdir(parents=True, exist_ok=True)
        args.state = logs / "state.json"
        write(args.state, {"official_repo": str(args.official_repo), "dev_site_packages":
            str(args.dev_site_packages) if args.dev_site_packages else None, "output": str(args.output),
            "official_before": before, "official_base": official, "ruff_exit_code": lint.returncode,
            "ruff_output": lint.stdout + lint.stderr, "test_files": files, "suites": [],
            "project_before": project_snapshot(), "started_utc": now()})
        _next(args.state, worker=bool(files))
    state = json.loads(args.state.read_text(encoding="utf-8"))
    if args.worker:
        import pytest
        restore_cwd()
        path = Path(state["test_files"][len(state["suites"])])
        xml = args.state.parent / (path.stem + ".xml")
        with (args.state.parent / (path.stem + ".log")).open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(_Tee(sys.stdout, log)), contextlib.redirect_stderr(_Tee(sys.stderr, log)):
                test_code = pytest.main(["-q", str(path), "--junitxml", str(xml)])
        counts = dict(passed=0, failed=0, skipped=0)
        if xml.exists():
            for suite in ET.parse(xml).getroot().findall("testsuite"):
                failures = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
                skips, total = int(suite.get("skipped", 0)), int(suite.get("tests", 0))
                counts["failed"] += failures
                counts["skipped"] += skips
                counts["passed"] += total - failures - skips
        state["suites"].append({"file": str(path.relative_to(PROJECT)), "exit_code": int(test_code), "tests": counts})
        write(args.state, state)
        _next(args.state, worker=len(state["suites"]) < len(state["test_files"]))
    sys.path.insert(1, state["official_repo"])
    from ui_kobe.osworld.runner import source_snapshot
    after = source_snapshot(Path(state["official_repo"]))
    before = state["official_before"]
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    project_after = project_snapshot()
    outcomes = {key: sum(suite["tests"][key] for suite in state["suites"]) for key in ("passed", "failed", "skipped")}
    test_code = max((suite["exit_code"] for suite in state["suites"]), default=0)
    code = 0 if not state["ruff_exit_code"] and not test_code and not changed and project_after == state["project_before"] else 1
    report = {"started_utc": state["started_utc"], "time_utc": now(), "exit_code": code, "pytest_exit_code": test_code,
              "tests": outcomes, "suites": state["suites"], "ruff_exit_code": state["ruff_exit_code"],
              "ruff_output": state["ruff_output"], "official_base": state["official_base"],
              "official_source_unchanged": not changed, "changed_official_paths": changed,
              "project_source": project_after, "project_source_unchanged": project_after == state["project_before"],
              "scope_limit": 128 * 1024**2, "memory_swap_max": 0,
              "memory_peak": int((group / "memory.peak").read_text()),
              "memory_events": (group / "memory.events").read_text(),
              "worker_policy": "one PID exec chain; sequential fresh interpreters; one registered scope",
              "live_api_called": False, "gui_operated": False}
    write(Path(state["output"]), report)
    print(json.dumps({k: report[k] for k in ("exit_code", "tests", "ruff_exit_code", "official_source_unchanged", "memory_peak")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
