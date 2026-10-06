"""Prepare, inspect and run Task059/046 through the existing OSWorld adapter.

Preparation is offline: no model, VM, task import, website mutation or evaluator.
Run this module in Linux/WSL for executable bundles. Each bundle is one trial.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from ui_kobe.osworld.task_examples import TASK_EXAMPLES, task_example


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def official_identity(repo: Path, task_id: str, release: str) -> dict:
    """Read only literal public task fields; never execute/import evaluator code."""
    if not re.fullmatch(r"osworld-v[0-9]+(?:\.[0-9]+)*", release):
        raise ValueError("Invalid benchmark release")
    source = repo / "evaluation_examples/task_class" / f"task_{task_id}.py"
    release_file = repo / "benchmark_releases" / f"{release}.json"
    release_data = json.loads(release_file.read_text(encoding="utf-8"))
    if release_data["release"] != release:
        raise ValueError("Benchmark release identity differs")
    hashes = repo / release_data["task_hash_manifest"]["path"]
    if not hashes.resolve().is_relative_to(repo.resolve()):
        raise ValueError("Task hash manifest must be inside the OSWorld checkout")
    if sha256(hashes) != release_data["task_hash_manifest"]["sha256"].removeprefix("sha256:"):
        raise ValueError("Official task hash manifest differs from the selected release")
    expected = json.loads(hashes.read_text(encoding="utf-8"))["files"][source.name]["sha256"]
    if sha256(source) != expected:
        raise ValueError(f"Task{task_id} source differs from the selected release")
    fields = {}
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name == f"Task{task_id}":
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, ast.Name) and target.id in {"id", "instruction", "related_apps"}:
                            fields[target.id] = ast.literal_eval(statement.value)
    if fields.get("id") != task_id or not isinstance(fields.get("instruction"), str) or not fields["instruction"]:
        raise ValueError("Official task must expose a literal ID and instruction")
    return {"task_id": task_id, "release": release, "source": str(source), "source_sha256": expected,
            "release_sha256": sha256(release_file), "task_hash_manifest_sha256": sha256(hashes),
            "instruction_sha256": hashlib.sha256(fields["instruction"].encode()).hexdigest(),
            "instruction": fields["instruction"], "related_apps": fields.get("related_apps", []),
            "task_revision": release_data["tasks"]["commit"],
            "asset_revision": release_data["assets"]["commit"],
            "website_revision": release_data["website_code"]["commit"]}


def prepare(case_id: str, *, osworld_root: Path, assets_root: Path, config: Path,
            agent_python: Path, vm_path: Path, output: Path, osworld_python: Path | None = None,
            release: str = "osworld-v2.1", website_host_suffix: str = "127.0.0.1.nip.io:21280",
            max_steps: int = 500, max_seconds: int = 3600) -> dict:
    spec = task_example(case_id)
    if type(max_steps) is not int or type(max_seconds) is not int or min(max_steps, max_seconds) < 1:
        raise ValueError("Step/time budgets must be positive integers")
    # Interpreters must retain their virtualenv symlink, unlike data paths.
    repo, assets, output = (Path(p).expanduser().resolve() for p in (osworld_root, assets_root, output))
    agent_python = Path(os.path.abspath(Path(agent_python).expanduser()))
    osworld_python = Path(os.path.abspath(Path(osworld_python or repo / ".venv/bin/python").expanduser()))
    vm_path = Path(vm_path).expanduser().resolve()
    if output.is_relative_to(repo) or output.is_relative_to(assets):
        raise ValueError("Keep example output outside official source and assets")
    if output.exists():
        raise FileExistsError(f"Use a new trial directory: {output}")
    origin = urlsplit("http://" + website_host_suffix)
    if not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
        raise ValueError("website_host_suffix must be a hostname with optional port")
    identity = official_identity(repo, case_id, release)
    data = json.loads(Path(config).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"api", "agent"}:
        raise ValueError("Agent config accepts only api and agent sections")
    # Bundles are inspectable artifacts, not credential stores.
    if any(key.lower() in {"api_key", "token", "password", "authorization"} for key in data.get("api", {})):
        raise ValueError("Use api_key_env, not an inline credential, in the example config")
    data = deepcopy(data)
    control = data.setdefault("agent", {}).setdefault("task_control", {})
    control.update(enabled=True, task_id=f"osworld2-{release}-{case_id}", memory_dir=str(output / "evaluation/memory"))
    # Public requirements arrive in the official instruction. Do not inherit old
    # Task035 answers/contracts or pre-annotated replay claims into this trial.
    for field in ("constraints", "delivery_files", "key_semantics"):
        control[field] = []
    config_file = output / "agent-config.json"
    common = [str(osworld_python), "-m", "ui_kobe.osworld.runner", "--osworld-root", str(repo),
              "--agent-python", str(agent_python), "--config", str(config_file), "--vm-path", str(vm_path),
              "--task", case_id, "--max-steps", str(max_steps), "--max-seconds", str(max_seconds)]
    plan = {"schema_version": 1, "kind": "osworld2_taskviews_evaluation_example", "task_id": case_id,
            "prepared_at": datetime.now(timezone.utc).isoformat(), "official": identity,
            "project_root": str(Path(__file__).resolve().parents[1]), "osworld_root": str(repo),
            "assets_root": str(assets), "vm_path": str(vm_path), "agent_python": str(agent_python),
            "osworld_python": str(osworld_python), "config": str(config_file),
            "required_assets": [str(assets / f"task_{case_id}" / name) for name in spec.assets],
            "required_websites": list(spec.websites), "view_focus": list(spec.view_focus),
            "environment": {"OSWORLD_BENCHMARK_RELEASE": release, "OSWORLD_FILE_BASE_URL": str(assets),
                            "WEBSITE_HOST_SUFFIX": website_host_suffix, "OSWORLD_LOCAL_WEB": "0"},
            "commands": {"setup": common + ["--setup-only", "--output", str(output / "setup")],
                         "evaluate": common + ["--evaluate", "--output", str(output / "evaluation")]},
            "evaluation": {"source": "env.evaluate() from the selected official task",
                           "partial_score": "raw official score; no synthetic intermediate reward",
                           "full_success": "official scalar score equals 1.0",
                           "policy": "UI-KOBE screenshot and single GUI action policy; task control enabled"}}
    output.mkdir(parents=True, exist_ok=False)
    write_json(config_file, data)
    plan["config_sha256"] = sha256(config_file)
    write_json(output / "plan.json", plan)
    write_json(output / "preflight.json", check(plan))
    return plan


def check(plan: dict, *, websites: bool = False) -> dict:
    """Filesystem checks; optionally read website roots. Does not allocate a VM."""
    missing = [p for p in [*plan["required_assets"], plan["vm_path"], plan["agent_python"],
                           plan["osworld_python"], str(Path(plan["osworld_root"]) / "desktop_env/desktop_env.py")]
               if not Path(p).is_file() or Path(p).stat().st_size == 0]
    failures = []
    try:
        actual = official_identity(Path(plan["osworld_root"]), plan["task_id"], plan["official"]["release"])
        if actual != plan["official"] or sha256(Path(plan["config"])) != plan["config_sha256"]:
            failures.append("Task/release/config changed after preparation; create a fresh bundle")
    except (OSError, ValueError, KeyError) as exc:
        failures.append(str(exc))
    website_checks = {}
    if websites:
        opener = build_opener(ProxyHandler({}))
        for app in plan["required_websites"]:
            url = f"http://{app}.{plan['environment']['WEBSITE_HOST_SUFFIX']}/"
            try:
                with opener.open(url, timeout=10) as response:
                    website_checks[app] = {"url": url, "reachable": response.status == 200}
            except OSError as exc:
                website_checks[app] = {"url": url, "reachable": False, "error": str(exc)}
    return {"files_ready": not missing, "missing_files": missing, "identity_errors": failures,
            "website_checks": website_checks, "websites_checked": websites,
            "ready_for_setup": not missing and not failures and (not plan["required_websites"] or
                                websites and all(item["reachable"] for item in website_checks.values())),
            "scope": "Local files and optional host HTTP roots only; VM, backend state and evaluator untested"}


def run_prepared(bundle: Path, mode: str) -> int:
    if mode not in {"setup", "evaluate"}:
        raise ValueError("Mode must be setup or evaluate")
    if sys.platform != "linux":
        raise ValueError("Run the evaluation bundle in Linux/WSL")
    bundle = Path(bundle).expanduser().resolve()
    plan = json.loads((bundle / "plan.json").read_text(encoding="utf-8"))
    report = check(plan, websites=True)
    write_json(bundle / "preflight.json", report)
    if not report["ready_for_setup"]:
        raise ValueError(f"Preflight blocked; inspect {bundle / 'preflight.json'}")
    if (bundle / ("evaluation" if mode == "evaluate" else "setup")).exists():
        raise FileExistsError("This mode already has output; prepare a fresh trial bundle")
    env = {**os.environ, **plan["environment"], "PYTHONDONTWRITEBYTECODE": "1"}
    env["PYTHONPATH"] = os.pathsep.join([plan["project_root"], plan["osworld_root"], env.get("PYTHONPATH", "")])
    env["UI_KOBE_TELEMETRY_DIR"] = str(bundle / f"{mode}-telemetry")
    # Do not silently inherit Task035's substituted judge into these tasks.
    for key in list(env):
        if key.startswith("OSWORLD_EVAL_MODEL_") or key.startswith("OSWORLD_USER_SIM_"):
            env.pop(key)
    return subprocess.run(plan["commands"][mode], env=env, cwd=plan["project_root"], check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Build one isolated trial bundle without starting services")
    prep.add_argument("--case", choices=tuple(TASK_EXAMPLES), required=True)
    for name in ("osworld-root", "assets-root", "config", "agent-python", "vm-path", "output"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--osworld-python", type=Path)
    prep.add_argument("--release", default="osworld-v2.1")
    prep.add_argument("--website-host-suffix", default="127.0.0.1.nip.io:21280")
    prep.add_argument("--max-steps", type=int, default=500)
    prep.add_argument("--max-seconds", type=int, default=3600)
    inspect = commands.add_parser("check")
    inspect.add_argument("--bundle", type=Path, required=True)
    inspect.add_argument("--websites", action="store_true")
    run = commands.add_parser("run")
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--mode", choices=("setup", "evaluate"), required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "prepare":
            args["case_id"] = args.pop("case")
            plan = prepare(**args)
            print(f"Task{plan['task_id']} bundle: {args['output']}; inspect preflight.json before running")
        elif command == "check":
            plan = json.loads((args["bundle"] / "plan.json").read_text(encoding="utf-8"))
            report = check(plan, websites=args["websites"])
            write_json(args["bundle"] / "preflight.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready_for_setup"] else 1
        else:
            return run_prepared(**args)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
