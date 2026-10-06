"""External OSWorld harness. Run with OSWorld's interpreter, not the agent's SDK."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .actions import compile_action, json_object
from .process import AgentProcess


def source_snapshot(repo: Path):
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=repo).decode().split("\0")
    paths += [str(p.relative_to(repo)) for p in (repo / "evaluation_examples/task_class").glob("*.py")]
    result = {}
    for name in sorted(set(paths)):
        path = repo / name
        if name and path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            result[name] = digest.hexdigest()
    return result


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def official_score(value):
    """Task059 returns a float; Task046 returns a dict with score and safety."""
    score = value.get("score") if isinstance(value, dict) else value
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Official evaluator did not return a finite score in [0, 1]")
    return float(score)


def checked_execution_result(result):
    """Require affirmative execution evidence; a timeout/None is unconfirmed."""
    if (not isinstance(result, dict) or type(result.get("returncode")) is not int
            or result.get("returncode") != 0 or result.get("status") != "success"):
        raise RuntimeError("Guest GUI action failed or unconfirmed; inspect controller_result before retrying")
    return result


class CheckedController:
    """Expose failures that DesktopEnv.step otherwise discards, without source edits."""
    def __init__(self, controller):
        self._controller = controller
        self.last_result = None

    def __getattr__(self, name):
        return getattr(self._controller, name)

    def execute_python_command(self, command):
        result = self._controller.execute_python_command(command)
        self.last_result = result
        return checked_execution_result(result)


class AdapterSmokeAgent:
    """A deterministic transport check, explicitly NOT a model or benchmark result."""
    last_trace = {"usage": {}, "model_api_called": False, "mode": "adapter_smoke"}

    def predict(self, instruction, obs, *, seconds):
        action = {"type": "move", "x": 320, "y": 240}
        return json.dumps({"reason": "Deterministic adapter smoke, no model call", "action": action}), [
            compile_action(action, 1920, 1080)]

    def reset(self):
        pass

    def close(self):
        pass


def wait_for_visible_desktop(env, obs, timeout=45):
    """The guest HTTP server may answer while GNOME still shows a black boot frame."""
    from PIL import Image
    end = time.monotonic() + timeout
    while True:
        screenshot = obs.get("screenshot")
        if isinstance(screenshot, bytes):
            with Image.open(BytesIO(screenshot)) as image:
                gray = image.convert("L")
                gray.thumbnail((160, 100))
                histogram = gray.histogram()
                count = sum(histogram)
                mean = sum(level * count_at_level for level, count_at_level in enumerate(histogram)) / count
                # A mouse cursor on black OR uniform dark-gray GNOME startup is not ready.
                if mean >= 80 or max(histogram) < count * 0.98:
                    return obs
        if time.monotonic() >= end:
            raise TimeoutError("Guest screenshot stayed black during desktop startup")
        time.sleep(2)
        obs = {**obs, "screenshot": env.controller.get_screenshot()}


def run_episode(env, agent, instruction, output, *, max_steps, max_seconds,
                desktop_smoke=False, evaluate=False, task=None, readiness_check=None, feedback_verifier=None):
    """Independent of task loading; injectable env/agent for offline integration tests."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "initializing", "steps": 0, "evaluation_requested": evaluate,
              "evaluated": False, "score": None, "partial_score": None, "full_success": None,
              "evaluation_status": "pending" if evaluate else "not_requested", "agent_done": False}
    started = time.monotonic()
    try:
        obs = env.reset(task)
        obs = wait_for_visible_desktop(env, obs)
        (output / "frame-0001.png").write_bytes(obs["screenshot"])
        if readiness_check is not None:
            report["readiness"] = readiness_check(env)
        env.controller = CheckedController(env.controller)
        report["setup_seconds"] = round(time.monotonic() - started, 3)
        deadline = time.monotonic() + max_seconds
        for step in range(1, max_steps + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                report["status"] = "time_limit"
                break
            response, actions = agent.predict(instruction, obs, seconds=min(480, remaining))
            if time.monotonic() >= deadline:
                report["status"] = "time_limit"
                break
            decision = json_object(response)
            if desktop_smoke and decision["action"] != {"type": "move", "x": 320, "y": 240}:
                raise ValueError("Desktop smoke permits only move(320,240); no other action was executed")
            from PIL import Image
            with Image.open(BytesIO(obs["screenshot"])) as image:
                expected_command = compile_action(decision["action"], *image.size)
            if actions != [expected_command]:
                raise ValueError("Agent actions must match the validated structured decision")
            record = {"step": step, "before": f"frame-{step:04d}.png", "decision": decision,
                      "command": actions[0], "trace": agent.last_trace}
            write_json(output / f"step-{step:04d}.json", record)
            env.controller.last_result = None
            try:
                obs, _, done, info = env.step(actions[0], pause=1)
            except Exception:
                if callable(getattr(agent, "feedback", None)):
                    agent.feedback({"controller_result": env.controller.last_result,
                                    "error": "execution_failed_or_unconfirmed"})
                raise
            if callable(getattr(agent, "feedback", None)):
                from .feedback import effect_feedback
                payload = effect_feedback(feedback_verifier, agent.last_trace, obs, env.controller.last_result)
                agent.feedback({**payload, "done": done})
            (output / f"frame-{step+1:04d}.png").write_bytes(obs["screenshot"])
            report["steps"] = step
            report["usage"] = agent.last_trace.get("usage", {})
            record.update(executed=True, info=info, after=f"frame-{step+1:04d}.png")
            write_json(output / f"step-{step:04d}.json", record)
            print(f"Step {step}: {decision['action']['type']}", flush=True)
            if done:
                report["agent_done"] = actions[0] == "DONE"
                report["status"] = "agent_done" if report["agent_done"] else "agent_failed"
                break
        else:
            report["status"] = "step_limit"
        if desktop_smoke and report["steps"] == 1:
            result = env.controller.execute_python_command(
                "import json; print(json.dumps(list(pyautogui.position())))")
            position = json.loads(result["output"].strip())
            if position != [320, 240]:
                raise RuntimeError("Guest cursor did not reach the model-requested position")
            report.update(status="desktop_smoke_passed", cursor=position)
        if evaluate:
            report["evaluation_status"] = "running"
            report["score"] = env.evaluate()  # Preserve the complete official return, including safety details.
            report["partial_score"] = official_score(report["score"])
            report["full_success"] = report["partial_score"] == 1.0
            report["evaluated"] = True
            report["evaluation_status"] = "scored"
    except BaseException as exc:
        if report["evaluation_status"] == "running":
            report["evaluation_status"] = "error"
        elif report["evaluation_status"] == "pending":
            report["evaluation_status"] = "not_run"
        report.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "error",
                      error=f"{type(exc).__name__}: {exc}")
        write_json(output / "error-trace.json", agent.last_trace)
        raise
    finally:
        report["total_seconds"] = round(time.monotonic() - started, 3)
        write_json(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osworld-root", type=Path, required=True)
    parser.add_argument("--agent-python", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", help="Override the model in the selected API configuration")
    parser.add_argument("--vm-path", type=Path,
                        default=Path.home() / "osworld2/images/osworld-v2-ubuntu-x86.qcow2")
    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Official v2 task ID, e.g. 035")
    task_group.add_argument("--desktop-smoke", action="store_true")
    task_group.add_argument("--adapter-smoke", action="store_true", help="Check VM/GUI adapter without a model API")
    parser.add_argument("--setup-only", action="store_true", help="Initialize --task and check GUI transport without a model")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--evaluate", action="store_true", help="Run the unchanged official evaluator; may call a judge API")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.max_steps < 1 or args.max_seconds < 1:
        parser.error("Step/time budgets must be positive")
    if args.task and not re.fullmatch(r"\d{3}", args.task):
        parser.error("Task IDs contain exactly three digits")
    if (args.desktop_smoke or args.adapter_smoke or args.setup_only) and args.evaluate:
        parser.error("Smoke/setup checks are not scored benchmarks")
    if args.setup_only and not args.task:
        parser.error("--setup-only requires --task")
    offline = args.adapter_smoke or args.setup_only
    smoke = args.desktop_smoke or offline
    repo, config = args.osworld_root.resolve(), args.config.resolve()
    # venv/bin/python is a symlink on Linux. Resolving it would silently bypass
    # pyvenv.cfg and start the base interpreter without the agent dependencies.
    args.agent_python = Path(os.path.abspath(args.agent_python.expanduser()))
    args.vm_path = args.vm_path.expanduser().resolve()
    # Resolve paths in the launch directory BEFORE switching to OSWorld for task imports.
    output = (args.output or Path.home() / "osworld2/results/ui-kobe" /
              datetime.now().strftime("%Y%m%d-%H%M%S-%f")).expanduser().resolve()
    if output.is_relative_to(repo):
        parser.error("Keep result/cache directories outside the OSWorld source checkout")
    if not (repo / "desktop_env/desktop_env.py").is_file() or not args.vm_path.is_file():
        parser.error("OSWorld repository or VM image is missing")
    if not args.agent_python.is_file() or not config.is_file():
        parser.error("Run scripts/setup_osworld_glm.sh first, or specify --agent-python and --config")
    config_data = json.loads(config.read_text(encoding="utf-8"))
    if args.model:
        config_data.setdefault("api", {})["model"] = args.model
    default_key = {"qwen": "QWEN_API_KEY", "kimi": "KIMI_API_KEY"}.get(config_data.get("api", {}).get("provider"), "GLM_API_KEY")
    key_name = config_data.get("api", {}).get("api_key_env", default_key)
    if not offline and not os.environ.get(key_name):
        parser.error(f"{key_name} is not set in this terminal")
    # Imports resolve from the pinned checkout; only outputs/cache go outside it.
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from desktop_env.desktop_env import DesktopEnv
    from task_loader import load_task_config
    local_profile = os.environ.get("WEBSITE_HOST_SUFFIX") == "127.0.0.1.nip.io:21280"
    local_teamchat = args.task == "035" and local_profile
    from .task_examples import TASK_EXAMPLES
    example = TASK_EXAMPLES.get(args.task)
    local_sites = example.websites if local_profile and example else ()
    if local_teamchat or example:
        # Bypass an older local helper that assumes passwordless sudo. Implement the
        # compatibility here; Task059 needs no TeamChat deployment at all.
        os.environ["OSWORLD_LOCAL_WEB"] = "0"
    task = load_task_config(None, task_id=args.task, base_dir=str(repo / "evaluation_examples"),
                            domain="tasks", eval_version="v2") if args.task else None
    instruction = task.instruction if task is not None else (
        "Move the mouse pointer to original screenshot pixel (320,240). "
        "Your only GUI operation must be this pointer movement. "
        "Do not click, type, finish, or open anything. Use the normal decision response schema.")
    output.mkdir(parents=True, exist_ok=False)
    before = source_snapshot(repo)
    write_json(output / "osworld-source-before.json", before)
    manifest = {"started_at": datetime.now(timezone.utc).isoformat(), "task": args.task,
                "model": None if offline else config_data.get("api", {}).get("model", "glm-5.3-flash"),
                "model_api_enabled": not offline,
                "osworld_root": str(repo), "agent_python": str(args.agent_python),
                "osworld_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                "osworld_status_before": subprocess.check_output(["git", "status", "--short"], cwd=repo, text=True),
                "max_steps": 1 if smoke else args.max_steps, "max_seconds": args.max_seconds}
    write_json(output / "manifest.json", manifest)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(output / "osworld.log"), logging.StreamHandler()])
    print(f"Results: {output}", flush=True)
    env, agent = None, None
    try:
        with (output / "agent-stderr.log").open("w", encoding="utf-8") as stderr:
            agent = AdapterSmokeAgent() if offline else AgentProcess(args.agent_python, config, stderr=stderr, model=args.model)
            try:
                agent.reset()  # Fail before allocating the VM if the agent cannot start.
                manifest["agent_runtime"] = getattr(agent, "metadata", {"mode": "adapter_smoke"})
                write_json(output / "manifest.json", manifest)
                env = DesktopEnv(provider_name="docker", path_to_vm=str(args.vm_path.resolve()), os_type="Ubuntu",
                                 action_space="pyautogui", require_a11y_tree=False, require_terminal=False,
                                 headless=True, cache_dir=str(output / "cache"),
                                 client_password=os.environ.get("OSWORLD_CLIENT_PASSWORD", ""))
                readiness_check = None
                if local_teamchat:
                    from .local_web import configure_local_teamchat, verify_teamchat_browser
                    configure_local_teamchat(env)
                    readiness_check = verify_teamchat_browser
                elif local_sites:
                    from .local_web import configure_local_websites, verify_local_websites
                    configure_local_websites(env, local_sites)
                    def readiness_check(active_env):
                        return verify_local_websites(active_env, local_sites)
                report = run_episode(env, agent, instruction, output, task=task,
                                     max_steps=1 if smoke else args.max_steps,
                                     max_seconds=args.max_seconds, desktop_smoke=smoke,
                                     evaluate=args.evaluate, readiness_check=readiness_check)
                if offline:
                    report.update(status="task_setup_and_adapter_passed" if args.task else "adapter_smoke_passed",
                                  model_api_called=False)
                    write_json(output / "result.json", report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
            finally:
                try:
                    agent.close()
                finally:
                    if env is not None:
                        env.close()
    except BaseException as exc:
        if not (output / "result.json").exists():
            write_json(output / "result.json", {"status": "initialization_error",
                                               "error": f"{type(exc).__name__}: {exc}",
                                               "evaluated": False, "score": None,
                                               "partial_score": None, "full_success": None,
                                               "evaluation_status": "not_run" if args.evaluate else "not_requested"})
        raise
    finally:
        after = source_snapshot(repo)
        changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
        write_json(output / "source-audit.json", {"unchanged": not changed, "changed_paths": changed})
        print(f"OSWorld source unchanged: {not changed}. Results: {output}", flush=True)
        if changed:
            raise RuntimeError("OSWorld source changes detected; inspect source-audit.json")


if __name__ == "__main__":
    main()
