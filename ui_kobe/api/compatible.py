"""Shared, bounded chat transport for OpenAI-compatible providers."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
import random
import re
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


@dataclass(frozen=True)
class APIConfig:
    base_url: str
    model: str
    api_key_env: str
    timeout: float = 180.0
    max_attempts: int = 3
    backoff_initial: float = 2.0
    backoff_max: float = 20.0
    total_timeout: float = 240.0
    extra_body: dict = field(default_factory=dict)

    def __post_init__(self):
        url = urlsplit(self.base_url) if isinstance(self.base_url, str) else None
        if (not url or url.scheme != "https" or not url.netloc or url.username or url.password
                or url.query or url.fragment or not isinstance(self.model, str) or not self.model.strip()):
            raise ValueError("Configure an HTTPS base_url without credentials/query and a nonempty model")
        if not isinstance(self.api_key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env):
            raise ValueError("Invalid API key environment variable name")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 6:
            raise ValueError("max_attempts must be an integer between 1 and 6")
        for name in ("timeout", "total_timeout", "backoff_initial", "backoff_max"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.extra_body, dict):
            raise ValueError("extra_body must be a JSON object")
        json.dumps(self.extra_body, allow_nan=False)


class APIRequestError(RuntimeError):
    """Safe to log: no credentials, request headers or response body."""
    provider = "API"

    def __init__(self, status_code=None, *, attempts=0, reason="request_failed", provider_code=None):
        self.status_code, self.attempts, self.reason = status_code, attempts, reason
        self.provider_code = provider_code
        super().__init__(f"{self.provider} {reason}; HTTP={status_code or 'n/a'}; "
                         f"code={provider_code or 'n/a'}; attempts={attempts}")


def safe_code(value):
    value = str(value or "")
    return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) else None


class CompatibleClient:
    """Non-streaming chat.completions.create with one retry layer and a deadline."""
    config_type = APIConfig
    error_type = APIRequestError
    non_retryable_codes = frozenset()

    def __init__(self, config=None, *, api_key=None, sdk_client=None,
                 sleep=time.sleep, clock=time.monotonic, jitter=random.uniform):
        self.config = config or self.config_type()
        if sdk_client is None:
            key = api_key or os.environ.get(self.config.api_key_env)
            if not key or not key.strip():
                raise ValueError(f"Set {self.config.api_key_env} in the WSL terminal before starting the agent")
            sdk_client = OpenAI(api_key=key, base_url=self.config.base_url,
                                timeout=self.config.timeout, max_retries=0)
        self._sdk = sdk_client
        self._sleep, self._clock, self._jitter = sleep, clock, jitter
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.stats = {"requests": 0, "retries": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def create(self, *, deadline=None, **kwargs):
        if kwargs.get("stream"):
            raise ValueError("This client supports non-streaming completions only")
        kwargs.setdefault("model", self.config.model)
        if self.config.extra_body:
            kwargs["extra_body"] = {**self.config.extra_body, **kwargs.get("extra_body", {})}
        end = min(deadline, self._clock() + self.config.total_timeout) if deadline is not None else (
            self._clock() + self.config.total_timeout)
        requested_timeout = kwargs.pop("timeout", self.config.timeout)
        if type(requested_timeout) not in (int, float) or not math.isfinite(requested_timeout) or requested_timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds")
        attempts, status, code = 0, None, None
        for attempt in range(self.config.max_attempts):
            remaining = end - self._clock()
            if remaining <= 0:
                raise self.error_type(status, attempts=attempts, reason="deadline_exceeded", provider_code=code) from None
            attempts += 1
            self.stats["requests"] += 1
            try:
                result = self._sdk.chat.completions.create(
                    **kwargs, timeout=min(requested_timeout, self.config.timeout, remaining))
                # Some gateways forward provider error envelopes using HTTP 200.
                if not getattr(result, "choices", None):
                    raise self.error_type(200, attempts=attempts, reason="invalid_completion",
                                          provider_code=safe_code(getattr(result, "code", None)))
                usage = getattr(result, "usage", None)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    self.stats[key] += getattr(usage, key, 0) or 0
                return result
            except (APITimeoutError, APIConnectionError):
                status, code, retryable = None, None, True
            except APIStatusError as exc:
                status = exc.status_code
                body = exc.body if isinstance(exc.body, dict) else {}
                error = body.get("error", body)
                code = safe_code(error.get("code")) if isinstance(error, dict) else None
                retryable = status in (408, 429) or 500 <= status < 600
                if code in self.non_retryable_codes:
                    retryable = False
            if not retryable or attempts == self.config.max_attempts:
                raise self.error_type(status, attempts=attempts, provider_code=code) from None
            cap = min(self.config.backoff_max, self.config.backoff_initial * 2 ** attempt)
            delay = self._jitter(cap / 2, cap)
            if self._clock() + delay >= end:
                raise self.error_type(status, attempts=attempts, reason="deadline_exceeded", provider_code=code) from None
            self.stats["retries"] += 1
            self._sleep(delay)
        raise AssertionError("unreachable")

    def close(self):
        self._sdk.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
