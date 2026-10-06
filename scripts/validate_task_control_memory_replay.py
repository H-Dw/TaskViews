"""Replay only saved observations; no API, GUI, evaluator or runner calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kobe_views.task_memory import TaskMemory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    telemetry = args.run_dir / "telemetry"
    observations, evidence = {}, {}
    for path in sorted(telemetry.glob("events-*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                # Never decode/retain inline requests or their history payloads.
                if '"event": "api_request"' in line:
                    continue
                event = json.loads(line)
                step = event.get("step", 0)
                if not 1 <= step <= 11:
                    continue
                if event.get("event") == "observation":
                    observations[step] = {k: event[k] for k in ("instruction", "screenshot")}
                if event.get("event") == "api_response" and event.get("phase") == "perception":
                    evidence[step] = json.loads(event["response"]["choices"][0]["message"]["content"])
    assert set(observations) == set(evidence) == set(range(1, 12)), "Missing original first 11 observations"
    rows = []
    with TemporaryDirectory(prefix="task-memory-replay-") as temp:
        memory = TaskMemory("saved-r04-memory-replay", temp)
        memory.initialize(observations[1]["instruction"])
        for step in range(1, 12):
            image = observations[step]["screenshot"]
            screenshot = (telemetry / image["image"]).read_bytes()
            assert hashlib.sha256(screenshot).hexdigest() == image["sha256"]
            metadata = memory.observe(f"saved-frame-{step:04d}", screenshot, evidence[step])
            core = memory.core_packet(32000)
            urls = [fact["value"] for fact in core["facts"] if fact["category"] == "url"]
            ports = [fact["value"] for fact in core["facts"] if fact["category"] == "port"]
            rows.append({"step": step, "source_screenshot": image, "revision": metadata["revision"],
                         "url_values": urls, "port_values": ports, "core_bytes": core["used_bytes"],
                         "gaps": core["gaps"]})
        assert all(any("teamchat.127.0.0.1.nip.io:21280" in url for url in row["url_values"])
                   and 21280 in row["port_values"] for row in rows)
        memory.close()
    result = {"checked_utc": datetime.now(timezone.utc).isoformat(), "source_run": str(args.run_dir),
              "mode": "offline_original_observation_replay", "frames": rows, "api_calls": 0,
              "gui_actions": 0, "score_claim": None,
              "conclusion": "Original resource URL and port remain in mandatory core through frame 11; "
                            "this does not predict a new Agent trajectory or task success."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("11 original frames replayed; URL/port retained; 0 API/GUI calls")


if __name__ == "__main__":
    main()
