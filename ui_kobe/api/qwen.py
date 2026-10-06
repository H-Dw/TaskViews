"""Qwen chat/vision provider; configure the exact OpenAI-compatible endpoint."""
from dataclasses import dataclass, field

from .compatible import APIConfig, APIRequestError, CompatibleClient


@dataclass(frozen=True)
class QwenConfig(APIConfig):
    model: str = "qwen3.6-35b-a3b"
    api_key_env: str = "QWEN_API_KEY"
    extra_body: dict = field(default_factory=lambda: {"enable_thinking": False})


class QwenRequestError(APIRequestError):
    provider = "QWEN"


class QwenClient(CompatibleClient):
    config_type = QwenConfig
    error_type = QwenRequestError
