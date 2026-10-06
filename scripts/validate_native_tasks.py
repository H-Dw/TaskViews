"""Run focused protocol/interface validation inside a 128 MiB auxiliary scope."""
import argparse
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.osworld_native_experiment import require_scope, project_snapshot, write, now  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_scope(128 * 1024**2)
    sys.path.insert(0, str(Path.home() / "osworld2/OSWorld-V2"))
    sys.path.append(str(PROJECT / ".venv/lib/python3.12/site-packages"))
    import pytest
    code = pytest.main(["-q", str(PROJECT / "tests/test_kimi_stream.py"),
                       str(PROJECT / "tests/test_native_task_experiment.py"),
                       str(PROJECT / "tests/test_native_generation_budget.py"),
                       str(PROJECT / "tests/test_native_resource_accounting.py")])
    write(args.output, {"time_utc": now(), "exit_code": code, "project_source": project_snapshot(),
                        "scope_limit": 128 * 1024**2, "memory_swap_max": 0})
    raise SystemExit(code)
