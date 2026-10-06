"""UI-KOBE utilities."""

from __future__ import annotations

import os
import re
from typing import Any

from openai import OpenAI


def resolve_env(value: str | None) -> str | None:
    """Resolve ``${ENV_VAR}`` references in a string."""
    if value is None:
        return None
    m = re.fullmatch(r"\$\{(\w+)\}", str(value).strip())
    if m:
        return os.environ.get(m.group(1))
    return str(value)


def make_client(cfg: dict | None) -> tuple[Any, str]:
    """Create an OpenAI client from a per-call config block.

    Args:
        cfg: Dict with keys ``model``, ``base_url``, ``api_key`` (all optional).

    Returns:
        (client, model_name)
    """
    cfg = cfg or {}
    if cfg.get("provider", "openai") in {"glm", "qwen"}:
        if cfg["provider"] == "glm":
            from ui_kobe.api.glm import GLMClient as Client, GLMConfig as Config
        else:
            from ui_kobe.api.qwen import QwenClient as Client, QwenConfig as Config
        options = {k: resolve_env(cfg[k]) if isinstance(cfg[k], str) else cfg[k]
                   for k in Config.__dataclass_fields__ if k in cfg}
        config = Config(**options)
        # An explicitly named secret must resolve; never fall back to another provider's key.
        key = resolve_env(cfg.get("api_key"))
        if "api_key" in cfg and not key:
            raise ValueError(f"The configured {cfg['provider'].upper()} api_key environment variable is empty")
        return Client(config, api_key=key), config.model
    if cfg.get("provider", "openai") != "openai":
        raise ValueError("Unsupported API provider")
    api_key = resolve_env(cfg.get("api_key")) or os.environ.get("OPENAI_API_KEY")
    base_url = resolve_env(cfg.get("base_url"))
    model = resolve_env(cfg.get("model")) or "gpt-4o"

    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs), model
