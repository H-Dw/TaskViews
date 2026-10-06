"""One predeclared frame, coordinate, history and recovery contract for both arms."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from ui_kobe.api.kimi_stream import StreamBudget


@dataclass(frozen=True)
class CUAContract:
    # Official absolute mode avoids an extra model-side normalization. The size
    # is selected before the run; never inferred from returned coordinates.
    coordinate_type: str = "absolute"
    model_screen_width: int | None = 1920
    model_screen_height: int | None = 1080
    history_n: int = 500
    image_max: int = 20
    fold_size: int = 10
    context_max_payload_chars: int = 10_000_000
    context_max_text_chars: int = 120_000
    context_rough_text_token_budget: int = 100_000
    context_reserve_chars: int = 32_000
    tool_repair_retries: int = 2
    advisory_repair_retries: int = 2
    taskviews_context_bytes: int = 32_000
    enable_context_rescue: bool = True

    def __post_init__(self):
        if self.coordinate_type not in {"relative", "absolute"}:
            raise ValueError("coordinate_type must be declared as relative or absolute")
        if (self.model_screen_width is None) != (self.model_screen_height is None):
            raise ValueError("Declare both model dimensions or neither")
        if self.model_screen_width is not None:
            if self.coordinate_type != "absolute":
                raise ValueError("Official fixed model dimensions require absolute coordinates")
            if any(type(n) is not int or n < 1 for n in (self.model_screen_width, self.model_screen_height)):
                raise ValueError("Model dimensions must be positive integers")
        for name in ("history_n", "image_max", "fold_size", "context_max_payload_chars",
                     "context_max_text_chars", "context_rough_text_token_budget", "taskviews_context_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + " must be a positive integer")
        if type(self.context_reserve_chars) is not int or not 0 <= self.context_reserve_chars < self.context_max_text_chars:
            raise ValueError("Context reserve must leave space for acting history")
        if self.taskviews_context_bytes > self.context_reserve_chars:
            raise ValueError("Both arms must reserve the full TaskViews context envelope")
        for name in ("tool_repair_retries", "advisory_repair_retries"):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 2:
                raise ValueError(name + " must be in 0..2")
        if type(self.enable_context_rescue) is not bool:
            raise ValueError("enable_context_rescue must be boolean")

    def snapshot(self):
        return asdict(self)

    def process(self, image_bytes, step):
        from mm_agents.qwen.images import process_screenshot
        processed = process_screenshot(image_bytes, coordinate_type=self.coordinate_type,
            model_screen_width=self.model_screen_width, model_screen_height=self.model_screen_height)
        return CUAFrame(processed, hashlib.sha256(image_bytes).hexdigest(), step)


@dataclass(frozen=True)
class CUAFrame:
    screenshot: object  # The unchanged official ProcessedScreenshot.
    original_sha256: str
    step: int

    @property
    def image(self):
        return {"type": "image_url", "image_url": {"url": self.screenshot.data_url}}

    @property
    def metadata(self):
        s = self.screenshot
        return {"frame_id": f"native-frame-{self.step:04d}", "coordinate_type": s.coordinate_type,
                "original_size": [s.original_width, s.original_height],
                "model_size": [s.model_width, s.model_height], "original_sha256": self.original_sha256,
                "coordinate_bounds": [1000, 1000] if s.coordinate_type == "relative" else [s.model_width, s.model_height],
                "evidence_bbox_units": "model_image_pixels", "projection": "official images.project_point"}

    @property
    def instruction(self):
        s = self.screenshot
        rules = ("Actions use normalized 0..1000 on EACH axis. From model-image pixels use "
                 f"x*1000/{s.model_width}, y*1000/{s.model_height}. Do not send pixel coordinates."
                 if s.coordinate_type == "relative" else
                 f"Actions use model-image pixels: x in 0..{s.model_width}, y in 0..{s.model_height}.")
        return ("Trusted screenshot/coordinate contract: " + json.dumps(self.metadata) + "\n" + rules +
                " Observation boxes always use model-image pixels; they are evidence, not actions. "
                "The declared unit never changes in response to a candidate. Old geometry must be re-grounded.")


def options_contract(options):
    """Honor official runner options; reject features that lack a native implementation."""
    values = dict(options)
    contract_fields = CUAContract.__dataclass_fields__
    selected = {name: values.pop(name) for name in contract_fields if name in values}
    if selected.get("coordinate_type") == "relative":
        selected.setdefault("model_screen_width", None)
        selected.setdefault("model_screen_height", None)
    required = {"stream": True, "enable_batch_actions": True, "enable_zoom": False,
                "summary_folding": False, "terminal_status_judge": False, "enable_endless_retry": False,
                "enable_thinking": True, "action_space": "pyautogui", "observation_type": "screenshot",
                "top_p": 0.95, "top_k": None}
    for name, expected in required.items():
        if name in values and values.pop(name) != expected:
            raise ValueError(f"Unsupported native option {name}; use {expected!r}")
    platform = values.pop("platform", "Ubuntu")
    if platform not in {"Ubuntu", "Windows", "ubuntu", "windows"}:
        raise ValueError("Unsupported OSWorld platform")
    # These official options only configure explicitly disabled features. Record
    # them as inactive instead of pretending that K3 implements XML recovery.
    inactive_names = ("summary_max_tokens", "summary_retries", "context_summary_chunk_steps",
                      "terminal_status_recovery_retries", "terminal_status_judge_max_tokens",
                      "endless_min_chars", "endless_retry_limit")
    inactive = {name: values.pop(name) for name in inactive_names if name in values}
    api_key = values.pop("api_key", None)
    budget = StreamBudget(attempts=values.pop("max_api_retries", 2),
                          generation_s=values.pop("generation_timeout", 600),
                          total_s=values.pop("request_timeout", 900))
    retry_base, retry_cap = values.pop("retry_sleep_base", 3.0), values.pop("retry_sleep_cap", 15.0)
    if (retry_base, retry_cap) != (3.0, 15.0):
        raise ValueError("Native transport currently supports retry_sleep_base=3 / cap=15")
    if values:
        raise ValueError("Unknown native options: " + ", ".join(sorted(values)))
    return CUAContract(**selected), budget, api_key, inactive
