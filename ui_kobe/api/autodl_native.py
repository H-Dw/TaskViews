"""AutoDL OpenAI-compatible streaming completions on the audited transport."""
from dataclasses import dataclass

from .qwen_native import QwenGenerationProfile, QwenNativeClient, transport_policy as shared_transport_policy

BASE_URL = 'https://www.autodl.art/api/v1'
MODEL = 'Qwen3.5-397B-A17B'
API_KEY_ENV = 'AUTODL_API_KEY'
PROTOCOL = 'autodl-qwen35-397b-a17b-native-tools-sse-v1'
GENERATION = 'autodl-qwen35-sse-total16k'


@dataclass(frozen=True)
class AutoDLGenerationProfile(QwenGenerationProfile):
    name: str = GENERATION
    reasoning_effort: str = 'provider_default'


def generation_profile(name=GENERATION):
    if name != GENERATION:
        raise ValueError('Unknown frozen AutoDL generation profile')
    return AutoDLGenerationProfile()


def generation_request_fields(profile):
    if profile != generation_profile(profile.name):
        raise ValueError('AutoDL generation profile changed its frozen bounds')
    # AutoDL documents Chat Completions, but no provider-specific thinking flags.
    return {}


def request_policy(profile):
    generation_request_fields(profile)
    return {'version': 'autodl-native-request-policy-v1', 'stream': True,
            'output_field': 'max_tokens', 'include_usage': True, 'trust_env': False}


def transport_policy(budget=None):
    return {**shared_transport_policy(budget), 'version': 'autodl-phase-aware-retry-v1',
            'upload_timeout_s': 120, 'endpoint_fallback': False,
            'billing_status_402': 'stop immediately; no retry',
            'reasoning': 'provider default; no undocumented thinking fields sent'}


class AutoDLNativeClient(QwenNativeClient):
    api_key_env = API_KEY_ENV
    base_url = BASE_URL
    model_name = MODEL
    request_prefix = 'autodl-'
    policy_for = staticmethod(request_policy)
    fields_for = staticmethod(generation_request_fields)
    write_timeout_s = 120
