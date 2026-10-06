"""Private line-delimited JSON transport, running in the AGENT's Python environment."""
from __future__ import annotations

import argparse
import base64
import json
from importlib.metadata import version
import os
from pathlib import Path
import sys
import time

from .agent import OSWorldAgent, load_config
from .task_control import TaskControlBlocked
from ui_kobe.api.compatible import APIRequestError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--model")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.model:
        config.setdefault("api", {})["model"] = args.model
    telemetry_dir = os.environ.get("UI_KOBE_TELEMETRY_DIR")
    if telemetry_dir:
        from . import telemetry
        telemetry.install_api(Path(telemetry_dir))
    agent = OSWorldAgent(config)
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                method = request["method"]
                if method == "close":
                    break
                if method == "reset":
                    agent.reset()
                    result = {"ok": True, "openai_version": version("openai"), "python": sys.version.split()[0],
                              "model": agent.client.config.model, "base_url": agent.client.config.base_url,
                              "task_control": agent.control is not None}
                elif method == "feedback":
                    feedback = dict(request["feedback"])
                    image = feedback.pop("screenshot_b64", None)
                    if image is not None:
                        feedback["screenshot"] = base64.b64decode(image, validate=True)
                    agent.feedback(feedback)
                    result = {"ok": True}
                elif method == "predict":
                    if telemetry_dir:
                        telemetry.set_context(agent.sequence + 1, "taskviews")
                    screenshot = base64.b64decode(request["screenshot"], validate=True)
                    response, _ = agent.predict(request["instruction"], {"screenshot": screenshot},
                                                deadline=time.monotonic() + request["seconds"])
                    result = {"ok": True, "response": response, "trace": agent.last_trace}
                    if telemetry_dir:
                        telemetry.emit("framework_trace", trace=agent.last_trace)
                else:
                    raise ValueError("Unknown worker method")
            except (ValueError, APIRequestError, TaskControlBlocked) as exc:
                result = {"ok": False, "error": str(exc), "trace": agent.last_trace}
                if telemetry_dir:
                    telemetry.emit("framework_error", error_type=type(exc).__name__, error=str(exc),
                                   trace=agent.last_trace)
            except Exception as exc:
                # Do not propagate SDK headers, environment values or raw model responses.
                result = {"ok": False, "error": f"Agent worker failed: {type(exc).__name__}"}
            print(json.dumps(result, ensure_ascii=True), flush=True)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
