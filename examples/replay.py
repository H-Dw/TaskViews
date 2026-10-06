"""python -m examples.replay --output outputs/replay.json"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from kobe_views import Budget, Request, RuntimeBridge, ViewKind, control_id, page_id


def run():
    root = Path(__file__).parent / "graphs"
    graph = json.loads((root / "settings.json").read_text(encoding="utf-8"))
    observations = json.loads((root / "observations.json").read_text(encoding="utf-8"))
    bridge = RuntimeBridge({"enabled": True})
    bridge.prepare(graph, app="demo", current_page="home")
    plan = bridge.service.project(Request(
        "Enable notifications 通知设置", capabilities=("navigate",), current_page=page_id("demo", "home"),
        seed_ids=(page_id("demo", "settings"),), budget=Budget(max_tokens=30000)))
    for obs in observations:
        bridge.prepare(graph, app="demo", current_page=obs["page"], observation=obs)
    bridge.recent_action = {"action": "tap", "target": "toggle"}
    views = bridge.service.project(Request(
        "Notifications 通知开关", consumer="one_agent_with_multiple_functions", action="type",
        capabilities=("verify",), current_page=bridge.current_page, observation_id=bridge.observation_id,
        seed_ids=(control_id(bridge.current_page, "toggle"),),
        target_fields=("state.notifications", "state.checked"), recent_action=bridge.recent_action,
        budget=Budget(max_tokens=30000)))
    return {"fixture": "synthetic, not an Android benchmark result",
            "planning": plan[ViewKind.PLANNING].data,
            "runtime": {kind.value: view.data for kind, view in views.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/replay.json"))
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved four task views to {args.output}")


if __name__ == "__main__":
    main()
