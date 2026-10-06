"""Validate model JSON and compile a small desktop action language to PyAutoGUI."""
from __future__ import annotations

import json
import math
import re


class InvalidAction(ValueError):
    pass


def json_object(text: str, *, max_chars=100_000) -> dict:
    if not isinstance(text, str) or len(text) > max_chars:
        raise ValueError("Expected a bounded JSON response")
    text = text.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if not match:
            raise ValueError("Invalid fenced JSON")
        text = match.group(1)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON value")))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "enter", "tab", "esc", "space", "backspace", "delete", "insert", "home", "end",
    "pageup", "pagedown", "up", "down", "left", "right", "ctrl", "alt", "shift", "win",
    "capslock", "printscreen", "+", "-", "=", ",", ".", "/", ";", "'", "[", "]", "\\", "`",
} | {f"f{i}" for i in range(1, 13)}


def compile_action(action: dict, width: int, height: int) -> str:
    """Coordinates are pixels in the ORIGINAL screenshot; there is no resize/scale."""
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        raise InvalidAction("Action needs a type")
    kind = action["type"]
    fields = {
        "move": {"x", "y"}, "click": {"x", "y", "button", "clicks"},
        "drag": {"x", "y", "to_x", "to_y"}, "scroll": {"x", "y", "amount"},
        "type": {"text"}, "press": {"key"}, "hotkey": {"keys"},
        "wait": {"seconds"}, "done": set(), "fail": set(),
    }
    if kind not in fields or set(action) - (fields[kind] | {"type"}):
        raise InvalidAction("Unsupported action or action fields")

    def integer(name, low, high, default=None):
        value = action.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise InvalidAction(f"{name} must be an integer in [{low}, {high}]")
        return value

    def point(x="x", y="y"):
        return integer(x, 0, width - 1), integer(y, 0, height - 1)

    def key(value):
        if not isinstance(value, str) or value not in KEYS:
            raise InvalidAction("Unsupported key")
        return repr(value)

    if kind in {"move", "click", "drag", "scroll"}:
        x, y = point()
        if kind == "move":
            return f"pyautogui.moveTo({x}, {y}, duration=0.2)"
        if kind == "click":
            button = action.get("button", "left")
            if button not in ("left", "middle", "right"):
                raise InvalidAction("Unsupported mouse button")
            clicks = integer("clicks", 1, 2, 1)
            return f"pyautogui.click({x}, {y}, clicks={clicks}, interval=0.15, button={button!r})"
        if kind == "drag":
            tx, ty = point("to_x", "to_y")
            return f"pyautogui.moveTo({x}, {y}); pyautogui.dragTo({tx}, {ty}, duration=0.6, button='left')"
        amount = integer("amount", -20, 20)
        if not amount:
            raise InvalidAction("Scroll amount cannot be zero")
        return f"pyautogui.moveTo({x}, {y}); pyautogui.scroll({amount})"
    if kind == "type":
        text = action.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= 5000 or "\x00" in text:
            raise InvalidAction("Text must contain 1–5000 characters without NUL")
        # Clipboard owners can outlive copy(). Isolate their stdio from the guest
        # server's captured command pipes, keep text as stdin data, and bound copy.
        helper = "import sys, pyperclip; pyperclip.copy(sys.stdin.read())"
        return (f"import subprocess, sys; subprocess.run([sys.executable, '-c', {helper!r}], "
                f"input={text!r}, text=True, encoding='utf-8', stdout=subprocess.DEVNULL, "
                "stderr=subprocess.DEVNULL, timeout=10, check=True); pyautogui.hotkey('ctrl', 'v')")
    if kind == "press":
        return f"pyautogui.press({key(action.get('key'))})"
    if kind == "hotkey":
        keys = action.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
            raise InvalidAction("Hotkey requires 1–4 keys")
        return f"pyautogui.hotkey({', '.join(key(k) for k in keys)})"
    if kind == "wait":
        seconds = action.get("seconds")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 30:
            raise InvalidAction("Wait requires 0 < seconds <= 30")
        return f"import time; time.sleep({seconds!r})"
    return {"done": "DONE", "fail": "FAIL"}[kind]
