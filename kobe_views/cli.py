"""Project an original UI-KOBE JSON graph without installing Android or a VLM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from .adapters import page_id
from .model import Budget, Request, ViewKind
from .runtime import RuntimeBridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("--app", default="app")
    parser.add_argument("--current", required=True, help="Original UI-KOBE page id")
    parser.add_argument("--task", required=True)
    parser.add_argument("--view", action="append", choices=[v.value for v in ViewKind])
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--action", default="")
    parser.add_argument("--field", action="append", default=[])
    parser.add_argument("--observations", type=Path, help="JSON list of at most two aligned observations")
    parser.add_argument("--max-tokens", type=int, default=12000, help="Per view; default counter uses UTF-8 bytes")
    parser.add_argument("--max-nodes", type=int, default=40)
    parser.add_argument("--max-edges", type=int, default=60)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    bridge = RuntimeBridge({"enabled": True})
    observations = json.loads(args.observations.read_text(encoding="utf-8")) if args.observations else []
    if len(observations) > 2:
        parser.error("Use a replay loop for more than two observations")
    if observations and str(observations[-1]["page"]) != args.current:
        parser.error("Last observation page must match --current")
    for obs in observations:
        bridge.prepare(graph, app=args.app, current_page=obs["page"], observation=obs)
    if not observations:
        bridge.prepare(graph, app=args.app, current_page=args.current)
    request = Request(args.task, "cli", tuple(args.capability), args.action,
                      page_id(args.app, args.current), bridge.observation_id,
                      target_fields=tuple(args.field), kinds=tuple(args.view or ()),
                      budget=Budget(args.max_tokens, args.max_nodes, args.max_edges))
    views = bridge.service.project(request)
    output = json.dumps({kind.value: view.data for kind, view in views.items()}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
