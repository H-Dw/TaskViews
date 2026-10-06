"""Replay synthetic OSWorld2-inspired task observations without a model or device."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kobe_views import AdaptiveTaskViews, Budget, RoleContract, TaskGraph, task_view_delta
from kobe_views.model import plain


CASES = Path(__file__).parent / "osworld2"


def replay(case: dict, *, journal: str | Path | None = None) -> dict:
    """Annotated extraction is the fixture input, never a generated model prediction.

    evaluation_notes/provenance/instruction are not graph evidence. The runtime
    caller should supply the user instruction separately from role-scoped memory.
    """
    graph = TaskGraph(case["task_id"], journal=journal)
    projector = AdaptiveTaskViews()
    roles = [RoleContract(**role) for role in case["roles"]]
    previous = {}
    steps = []
    try:
        for event in case["events"]:
            delta = graph.ingest(event)
            if delta["duplicate"]:
                continue  # A resumed journal does not pretend to replay historical states.
            snapshot = graph.read()
            contexts, updates = {}, {}
            for role in roles:
                view = projector.project(snapshot, role, Budget(max_tokens=50000, max_nodes=80, max_edges=120))
                contexts[role.id] = view.data
                updates[role.id] = task_view_delta(previous.get(role.id), view)
                previous[role.id] = view  # In a live integration advance only after consumer acknowledgement.
            steps.append({"event_id": event["id"], "graph_delta": delta,
                          "role_contexts": contexts, "role_updates": updates})
        snapshot = graph.read()
        return {"kind": "synthetic_mechanism_replay_not_benchmark_score", "task_id": case["task_id"],
                "steps": steps, "final_revision": snapshot.revision, "final_sequence": snapshot.sequence,
                "discovered_schema": plain(snapshot.schema), "statuses": plain(snapshot.statuses)}
    finally:
        graph.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("069", "008", "035", "059", "046"), default="069")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--journal", type=Path, help="Optional local SQLite observation journal")
    args = parser.parse_args()
    source = CASES / f"task{args.case}.json"
    output = args.output or Path("outputs") / f"task{args.case}_replay.json"
    if args.journal:
        args.journal.parent.mkdir(parents=True, exist_ok=True)
    result = replay(json.loads(source.read_text(encoding="utf-8")), journal=args.journal)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Task{args.case}: {len(result['steps'])} new events, revision {result['final_revision']} -> {output}")


if __name__ == "__main__":
    main()
