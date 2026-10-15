"""OpenRouter Qwen native tools, including opaque reasoning-details replay."""
from copy import deepcopy
from dataclasses import dataclass
import json

from .kimi_stream import StreamProtocolError
from .qwen_native import QwenGenerationProfile, QwenNativeClient, transport_policy as shared_transport_policy
from .qwen_sse import QwenSSE

BASE_URL = 'https://openrouter.ai/api/v1'
MODEL = 'qwen/qwen3.6-35b-a3b'
PROTOCOL = 'openrouter-qwen36-native-tools-reasoning-details-sse-v1'
GENERATION = 'openrouter-qwen36-sse-low-total16k'


@dataclass(frozen=True)
class OpenRouterGenerationProfile(QwenGenerationProfile):
    name: str = GENERATION
    reasoning_effort: str = 'low'


def generation_profile(name=GENERATION):
    if name != GENERATION:
        raise ValueError('Unknown frozen OpenRouter generation profile')
    return OpenRouterGenerationProfile()


def generation_request_fields(profile):
    if profile != generation_profile(profile.name):
        raise ValueError('OpenRouter generation profile changed its frozen bounds')
    return {'reasoning': {'enabled': True, 'effort': 'low'},
            'provider': {'require_parameters': True}}


def request_policy(profile):
    generation_request_fields(profile)
    return {'version': 'openrouter-native-request-policy-v1', 'stream': True,
            'output_field': 'max_tokens', 'include_usage': True, 'trust_env': False}


def transport_policy(budget=None):
    return {**shared_transport_policy(budget), 'version': 'openrouter-phase-aware-retry-v1',
            'billing_status_402': 'stop immediately; no retry',
            'reasoning_details': 'append stream objects in original order; replay unchanged',
            'routing': 'OpenRouter default routing restricted to supported parameters; record returned provider'}


class OpenRouterSSE(QwenSSE):
    def __init__(self, model):
        super().__init__(model)
        self.reasoning_details = []
        self.details_seen = self.reasoning_seen = False
        self.router_reasoning = []
        self.provider = None

    def _add(self, value):
        super()._add(value)
        if value == '[DONE]':
            return
        data = json.loads(value)
        provider = data.get('provider')
        if provider is not None:
            if not isinstance(provider, str) or (self.provider is not None and provider != self.provider):
                raise StreamProtocolError('Conflicting OpenRouter provider', code='invalid_sse')
            self.provider = provider
        for choice in data.get('choices', []):
            delta = choice.get('delta') or {}
            reasoning = delta.get('reasoning')
            if reasoning is not None:
                if not isinstance(reasoning, str):
                    raise StreamProtocolError('Invalid OpenRouter reasoning text', code='invalid_sse')
                self.reasoning_seen = True
                self.router_reasoning.append(reasoning)
            details = delta.get('reasoning_details')
            if details is not None:
                if not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
                    raise StreamProtocolError('Invalid OpenRouter reasoning details', code='invalid_sse')
                self.details_seen = True
                # OpenRouter documents concatenation in arrival order. Do not
                # rewrite indices/IDs/signatures or summarize opaque objects.
                self.reasoning_details.extend(deepcopy(details))

    def observed(self):
        body = super().observed()
        message = body['choices'][0]['message']
        if not self.reasoning:
            message.pop('reasoning_content')
        if self.reasoning_seen:
            message['reasoning'] = ''.join(self.router_reasoning)
        if self.details_seen:
            message['reasoning_details'] = deepcopy(self.reasoning_details)
        if self.provider is not None:
            body['provider'] = self.provider
        return body


class OpenRouterNativeClient(QwenNativeClient):
    api_key_env = 'OPENROUTER_LTY_API_KEY'
    base_url = BASE_URL
    model_name = MODEL
    request_prefix = 'openrouter-'
    policy_for = staticmethod(request_policy)
    fields_for = staticmethod(generation_request_fields)

    def accumulator(self):
        return OpenRouterSSE(self.model_name)
