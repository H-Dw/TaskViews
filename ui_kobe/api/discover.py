"""Read an endpoint's advertised model IDs, or probe explicitly named candidates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


def discover(base_url, key_env="QWEN_API_KEY", *, probe_models=()):
    url = urlsplit(base_url)
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError("Provide an HTTPS base URL without credentials, query or fragment")
    key = os.environ.get(key_env)
    if not key:
        raise ValueError(f"Set {key_env} in this terminal")
    root = base_url.rstrip("/")
    candidates = [root] if url.path.rstrip("/").endswith("/v1") else [root, root + "/v1"]
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "requested_url": root, "probes": []}
    with httpx.Client(timeout=60, follow_redirects=False,
                      headers={"Authorization": f"Bearer {key}"}) as client:
        for base in candidates:
            response = client.get(base + "/models")
            result = {"url": base + "/models", "status": response.status_code,
                      "content_type": response.headers.get("content-type", "")}
            report["probes"].append(result)
            if response.status_code in (401, 403):
                break
            if response.status_code != 200:
                continue
            try:
                body = response.json()
            except ValueError:
                continue
            models = body.get("data") if isinstance(body, dict) else None
            if not isinstance(models, list):
                continue
            ids = sorted({entry["id"] for entry in models if isinstance(entry, dict)
                          and isinstance(entry.get("id"), str)})
            report.update(api_base_url=base, model_ids=ids,
                          qwen_model_ids=[mid for mid in ids if "qwen" in mid.lower()])
            break
        if probe_models:
            tested = []
            for model in dict.fromkeys(probe_models):
                started = time.monotonic()
                base = report.get("api_base_url", root)
                response = client.post(base + "/chat/completions", json={
                    "model": model, "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                    "max_tokens": 256, "enable_thinking": False, "stream": False})
                item = {"requested_model": model, "http_status": response.status_code,
                        "seconds": round(time.monotonic() - started, 2), "verified": False}
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if isinstance(body, dict) and response.status_code == 200 and body.get("choices"):
                    choice = body["choices"][0]
                    content = choice.get("message", {}).get("content")
                    item.update(returned_model=body.get("model"), finish_reason=choice.get("finish_reason"),
                                usage=body.get("usage"),
                                verified=choice.get("finish_reason") == "stop" and bool(content))
                elif isinstance(body, dict):
                    message = body.get("message", body.get("response", body.get("error", "")))
                    item["error"] = str(message).replace(key, "[redacted]")[:1500]
                tested.append(item)
            report["model_tests"] = tested
            report["verified_models"] = [entry["requested_model"] for entry in tested if entry["verified"]]
            report["catalog_complete"] = "model_ids" in report
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--key-env", default="QWEN_API_KEY")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe-model", action="append", default=[],
                        help="Make one short text request for this model; may be specified multiple times")
    args = parser.parse_args()
    try:
        result = discover(args.base_url, args.key_env, probe_models=args.probe_model)
    except httpx.HTTPError as exc:
        raise SystemExit(f"Model discovery failed: {type(exc).__name__}") from None
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    if "api_base_url" not in result and not result.get("verified_models"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
