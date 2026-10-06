"""Keep the agent SDK and OSWorld dependencies in separate interpreters."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import queue
import subprocess
import threading

from .actions import compile_action, json_object


class AgentProcess:
    def __init__(self, python, config, *, stderr, model=None):
        command = [str(python), "-m", "ui_kobe.osworld.worker", "--config", str(Path(config).resolve())]
        if model is not None:
            command.extend(["--model", model])
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True,
            encoding="utf-8", bufsize=1)
        self._replies = queue.Queue()
        self.last_trace = {}

        def read():
            try:
                for line in self._process.stdout:
                    self._replies.put(line)
            finally:
                self._replies.put(None)

        self._reader = threading.Thread(target=read, daemon=True)
        self._reader.start()

    def _call(self, request, timeout):
        self._process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self._process.stdin.flush()
        try:
            line = self._replies.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError("Agent response deadline exceeded") from None
        if line is None:
            raise RuntimeError("Agent worker exited; see agent-stderr.log")
        reply = json_object(line, max_chars=1_000_000)
        if not reply.get("ok"):
            self.last_trace = reply.get("trace", {})
            raise RuntimeError(reply.get("error", "Agent worker failed"))
        return reply

    def reset(self):
        self.metadata = self._call({"method": "reset"}, 30)

    def predict(self, instruction, obs, *, seconds):
        # Pillow is already an OSWorld dependency; the API SDK is not imported here.
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(obs["screenshot"])) as image:
            width, height = image.size
        reply = self._call({"method": "predict", "instruction": instruction, "seconds": seconds,
                            "screenshot": base64.b64encode(obs["screenshot"]).decode("ascii")}, seconds + 5)
        decision = json_object(reply["response"])
        # Compile again at the execution boundary. Never trust arbitrary generated Python.
        action = compile_action(decision["action"], width, height)
        self.last_trace = reply["trace"]
        return reply["response"], [action]

    def feedback(self, feedback):
        payload = dict(feedback)
        screenshot = payload.pop("screenshot", None)
        if screenshot is not None:
            payload["screenshot_b64"] = base64.b64encode(screenshot).decode("ascii")
        return self._call({"method": "feedback", "feedback": payload}, 30)

    def close(self):
        if self._process.poll() is None:
            try:
                self._process.stdin.write('{"method":"close"}\n')
                self._process.stdin.flush()
                self._process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=3)
        for pipe in (self._process.stdin, self._process.stdout):
            pipe.close()
