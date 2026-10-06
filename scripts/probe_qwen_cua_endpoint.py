"""Bounded, credential-safe model/parameter probes; never execute GUI actions."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import struct
import zlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import openai


CASES = {
    "availability_text": ("qwen3.6-35b-a3b", None),
    "cua_text": ("qwen-cua", None),
    "cua_canonical_text": ("xlangai/Qwen-CUA", None),
    "control_text": ("qwen3.6-35b-a3b", {"enable_thinking": False}),
    "control_nested_false": ("qwen3.6-35b-a3b", {"chat_template_kwargs": {"enable_thinking": False}}),
    "control_top_true": ("qwen3.6-35b-a3b", {"enable_thinking": True}),
    "control_nested_true": ("qwen3.6-35b-a3b", {"chat_template_kwargs": {"enable_thinking": True}}),
    "control_top_false_vision": ("qwen3.6-35b-a3b", {"enable_thinking": False}),
    "control_nested_false_vision": ("qwen3.6-35b-a3b", {"chat_template_kwargs": {"enable_thinking": False}}),
}


def vision_probe_image() -> bytes:
    """Two simple color rectangles, using only standard-library PNG encoding."""
    width, height = 320, 200
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            color = (255, 255, 255)
            if 50 <= y < 150 and 20 <= x < 140:
                color = (255, 0, 0)
            elif 50 <= y < 150 and 180 <= x < 300:
                color = (0, 0, 255)
            rows.extend(color)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="https://pjfdspqowq.a.pinggy.link")
    parser.add_argument("--model", help="Override the model for all selected cases.")
    parser.add_argument("--provider", choices=["qwen", "kimi"], default="qwen")
    parser.add_argument("--cases", nargs="+", required=True, choices=CASES)
    args = parser.parse_args()
    key_env = "KIMI_API_KEY" if args.provider == "kimi" else "QWEN_API_KEY"
    key = os.environ.get(key_env)
    if not key:
        raise SystemExit(f"{key_env} is missing; its value was not printed.")

    def safe(value):
        if isinstance(value, str):
            return value.replace(key, "[REDACTED]")
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [safe(v) for v in value]
        return value

    args.run_dir.mkdir(parents=True, exist_ok=True)
    record = args.run_dir / "probe.json"
    report = json.loads(record.read_text()) if record.exists() else {"models_checks": [], "probes": []}
    report.update(base_url=args.base_url, key_env=key_env, provider=args.provider, openai_version=openai.__version__,
                  scope="API capability probes only; no VM, GUI actions or model deployment.")
    with openai.OpenAI(api_key=key, base_url=args.base_url, max_retries=0,
                       timeout=httpx.Timeout(55, connect=10)) as client:
        for name in args.cases:
            model, extra = CASES[name]
            model = args.model or model
            payload = {"model": model, "messages": [{"role": "user", "content":
                       "Compute 17 times 19. Return only the numeric answer."}],
                       "temperature": 0, "top_p": 0.9, "max_tokens": 2048, "stream": False}
            if extra is not None:
                payload["extra_body"] = extra
            if args.provider == "kimi":
                from ui_kobe.api.kimi import K3Requests
                payload.update(temperature=1, top_p=0.95)
                payload = K3Requests().prepare(payload)
            saved_payload = payload
            if name.endswith("_vision"):
                image_bytes = vision_probe_image()
                (args.run_dir / "vision-probe.png").write_bytes(image_bytes)
                payload["messages"] = [{"role": "user", "content": [
                    {"type": "text", "text": "Name the colors of the two rectangles from left to right. Return only the two English color names."},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")}},
                ]}]
                saved_payload = json.loads(json.dumps(payload))
                saved_payload["messages"][0]["content"][1]["image_url"]["url"] = "[saved as vision-probe.png]"
            probe = {"case": name, "started_utc": datetime.now(timezone.utc).isoformat(), "request": saved_payload}
            started = time.monotonic()
            print(json.dumps({"case": name, "status": "started"}), flush=True)
            try:
                raw = client.chat.completions.with_raw_response.create(**payload)
                probe.update(status_code=raw.status_code,
                             server_headers={k: v for k, v in raw.headers.items() if k.lower() in
                                             ("server", "x-powered-by", "x-request-id", "x-dashscope-request-id")})
                response = raw.http_response.json()
                probe["response"] = response
                choices = response.get("choices") if isinstance(response, dict) else None
                if not isinstance(choices, list) or not choices or not isinstance(choices[0].get("message"), dict):
                    probe["valid_chat_completion"] = False
                    raise ValueError("HTTP response is not a valid Chat Completions result; see saved response body.")
                message = choices[0]["message"]
                reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
                probe.update(valid_chat_completion=True,
                             response_model=response.get("model"), content_chars=len(message.get("content") or ""),
                             reasoning_chars=len(reasoning), finish_reason=response["choices"][0].get("finish_reason"))
            except Exception as exc:
                probe.update(error_type=type(exc).__name__, status_code=getattr(exc, "status_code", None) or probe.get("status_code"),
                             error=str(exc).replace(key, "[REDACTED]")[:2000])
                causes = []
                cause = exc.__cause__
                while cause is not None and len(causes) < 4:
                    causes.append({"type": type(cause).__name__, "error": safe(str(cause))[:1000]})
                    cause = cause.__cause__
                if causes:
                    probe["error_causes"] = causes
            probe["duration_s"] = round(time.monotonic() - started, 3)
            report["probes"].append(safe(probe))
            report["updated_utc"] = datetime.now(timezone.utc).isoformat()
            record.write_text(json.dumps(safe(report), ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(safe({k: v for k, v in probe.items() if k not in ("request", "response")}),
                             ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
