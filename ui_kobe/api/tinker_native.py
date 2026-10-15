"""Tinker's official OpenAI-compatible endpoint, with no Pinggy extensions.

The requested low effort is explicit and must be accepted by the live service;
there is no silent downgrade to default/disabled thinking on HTTP 400.
"""
from dataclasses import dataclass

from .qwen_native import QwenGenerationProfile, QwenNativeClient, transport_policy as shared_transport_policy

BASE_URL = 'https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1'
MODEL = 'Qwen/Qwen3.6-35B-A3B'
PROTOCOL = 'tinker-qwen36-openai-native-tools-sse-v1'
GENERATION = 'tinker-qwen36-sse-low-total16k'


@dataclass(frozen=True)
class TinkerGenerationProfile(QwenGenerationProfile):
    name: str = GENERATION
    reasoning_effort: str = 'low'


def generation_profile(name=GENERATION):
    if name != GENERATION:
        raise ValueError('Unknown frozen Tinker generation profile')
    return TinkerGenerationProfile()


def generation_request_fields(profile):
    if profile != generation_profile(profile.name):
        raise ValueError('Tinker generation profile changed its frozen bounds')
    return {'reasoning_effort': 'low', 'separate_reasoning': True}


def request_policy(profile):
    generation_request_fields(profile)
    return {'version': 'tinker-openai-request-policy-v1', 'stream': True,
            'output_field': 'max_tokens', 'include_usage': True, 'trust_env': False}


def transport_policy(budget=None):
    return {**shared_transport_policy(budget), 'version': 'tinker-phase-aware-retry-v1',
            'billing_status_402': 'stop immediately; no retry',
            'unsupported_reasoning_400': 'stop immediately; no silent fallback'}


class TinkerNativeClient(QwenNativeClient):
    api_key_env = 'TINKER_API_KEY'
    base_url = BASE_URL
    model_name = MODEL
    request_prefix = 'tinker-'
    policy_for = staticmethod(request_policy)
    fields_for = staticmethod(generation_request_fields)
