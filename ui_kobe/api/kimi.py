"""Kimi K3 transport: fixed sampling and preserved assistant reasoning."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass

from .compatible import APIConfig, APIRequestError, CompatibleClient

BASE_URL = "https://api.moonshot.ai/v1"


@dataclass(frozen=True)
class GenerationProfile:
    name: str
    reasoning_effort: str
    max_completion_tokens: int
    step_output_tokens: int
    executor_reserve_tokens: int
    adviser_max_tokens: int
    semantic_regenerations: int = 2

    def __post_init__(self):
        if self.reasoning_effort not in ('low', 'high', 'max'):
            raise ValueError('Invalid generation effort')
        limits = (self.max_completion_tokens, self.step_output_tokens,
                  self.executor_reserve_tokens, self.adviser_max_tokens)
        if any(type(n) is not int or n <= 0 for n in limits):
            raise ValueError('Generation limits must be positive integers')
        if not self.adviser_max_tokens <= self.max_completion_tokens <= self.executor_reserve_tokens <= self.step_output_tokens:
            raise ValueError('Inconsistent generation reserves')
        if type(self.semantic_regenerations) is not int or not 0 <= self.semantic_regenerations <= 2:
            raise ValueError('At most two repairs in each actor/advisory pool within the shared step budget')


GENERATION_PROFILES = {
    'low-16k': GenerationProfile('low-16k', 'low', 16000, 32000, 16000, 4000),
    'max-16k': GenerationProfile('max-16k', 'max', 16000, 32000, 16000, 4000),
    'max-32k': GenerationProfile('max-32k', 'max', 32768, 65536, 32768, 8192),
}


def generation_profile(name='low-16k'):
    return GENERATION_PROFILES[name]


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if item.get("type") == "text")
    return ""


class K3Requests:
    """Translate provider fields only; retain exact returned assistant messages."""
    def __init__(self, effort="max", *, profile=None):
        if profile is not None:
            effort = profile.reasoning_effort
        if effort not in ("low", "high", "max"):
            raise ValueError("Invalid K3 reasoning effort")
        self.effort = effort
        self.profile = profile
        self.messages = OrderedDict()

    def prepare(self, kwargs):
        request = deepcopy(kwargs)
        if request.get("model") != "kimi-k3":
            raise ValueError("K3 transport requires the exact kimi-k3 model")
        for field, expected in (("temperature", 1), ("top_p", 0.95)):
            value = request.pop(field, expected)
            if value is not None and value != expected:
                raise ValueError(f"K3 {field} is fixed at {expected}")
        extra = dict(request.pop("extra_body", {}) or {})
        # The official XML runner emits Qwen's field. It has no K3 meaning.
        extra.pop("enable_thinking", None)
        if "thinking" in extra or "chat_template_kwargs" in extra:
            raise ValueError("K3 cannot disable thinking or use Qwen chat template fields")
        if extra:
            request["extra_body"] = extra
        if "max_tokens" in request:
            request["max_completion_tokens"] = request.pop("max_tokens")
        if self.profile is not None:
            limit = request.setdefault('max_completion_tokens', self.profile.max_completion_tokens)
            if type(limit) is not int or not 1 <= limit <= self.profile.max_completion_tokens:
                raise ValueError('Request exceeds frozen generation profile')
        effort = request.setdefault("reasoning_effort", self.effort)
        if effort != self.effort:
            raise ValueError("K3 reasoning effort must remain fixed")
        request.setdefault("stream", False)
        for index, message in enumerate(request.get("messages", [])):
            if message.get("role") == "assistant":
                original = self.messages.get(content_text(message.get("content")).strip())
                if original is None:
                    raise ValueError("K3 assistant history is missing its original response")
                request["messages"][index] = deepcopy(original)
        return request

    def remember(self, response):
        message = response.choices[0].message
        original = message.model_dump(exclude_none=True)
        text = content_text(original.get("content")).strip()
        if text:
            self.messages[text] = original
            self.messages.move_to_end(text)
            # The official runner retains up to 500 turns plus repair/summary
            # responses. This bounded cache must outlast that history window.
            while len(self.messages) > 2048:
                self.messages.popitem(last=False)


@dataclass(frozen=True)
class KimiConfig(APIConfig):
    base_url: str = BASE_URL
    model: str = "kimi-k3"
    api_key_env: str = "KIMI_API_KEY"
    reasoning_effort: str = "max"

    def __post_init__(self):
        super().__post_init__()
        if self.model != "kimi-k3" or self.extra_body:
            raise ValueError("This Kimi profile supports kimi-k3 without thinking overrides")
        K3Requests(self.reasoning_effort)


class KimiRequestError(APIRequestError):
    provider = "KIMI"


class KimiClient(CompatibleClient):
    config_type = KimiConfig
    error_type = KimiRequestError

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.k3 = K3Requests(self.config.reasoning_effort)

    def create(self, *, deadline=None, **kwargs):
        kwargs.setdefault("model", self.config.model)
        response = super().create(deadline=deadline, **self.k3.prepare(kwargs))
        self.k3.remember(response)
        return response


def install_official_k3_transport():
    """Install inside the runner process, without writing OSWorld source."""
    import functools
    import openai

    original_init = openai.OpenAI.__init__
    # OSWorld creates a fresh backend for each user-simulator answer. Share only
    # within the same system prompt, so its original reasoning is retained too.
    sessions = {}

    @functools.wraps(original_init)
    def initialize(client, *args, **kwargs):
        original_init(client, *args, **kwargs)
        if str(client.base_url).rstrip("/") != BASE_URL:
            return
        original_create = client.chat.completions.create

        @functools.wraps(original_create)
        def create(*args, **kwargs):
            system = tuple(content_text(m.get("content")) for m in kwargs.get("messages", []) if m.get("role") == "system")
            transport = sessions.setdefault(system, K3Requests())
            response = original_create(*args, **transport.prepare(kwargs))
            transport.remember(response)
            return response

        client.chat.completions.create = create

    openai.OpenAI.__init__ = initialize
