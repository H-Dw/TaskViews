"""Probe OSWorld's official Qwen screenshot-to-XML path without starting a VM."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> None:
    key = os.environ.get("QWEN_API_KEY")
    if not key:
        raise SystemExit("QWEN_API_KEY is missing")
    os.environ["OPENAI_API_KEY"] = key
    root = Path.home() / "osworld2/OSWorld-V2"
    sys.path.insert(0, str(root))
    from mm_agents.qwen import QwenAgent

    screenshot = Path.home() / "osworld2/results/ui-kobe/20260930-140835-327798/frame-0001.png"
    if not screenshot.is_file():
        raise SystemExit("Saved OSWorld desktop screenshot is missing")
    agent = QwenAgent(
        model="qwen3.6-35b-a3b",
        base_url="https://pjfdspqowq.a.pinggy.link",
        enable_thinking=False,
        stream=False,
        enable_batch_actions=False,
        terminal_status_judge=False,
        max_api_retries=1,
        request_timeout=120,
        generation_timeout=90,
        max_tokens=2048,
    )
    response, actions = agent.predict(
        "Move the mouse pointer to screen pixel coordinates (320, 240), then stop.",
        {"screenshot": screenshot.read_bytes()},
    )
    print(json.dumps({"response": response[:2000], "actions": actions}, ensure_ascii=False))


if __name__ == "__main__":
    main()
