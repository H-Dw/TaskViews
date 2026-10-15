"""Explicit Sui-xiang Qwen profiles with frozen HTTPS routing."""
from dataclasses import dataclass
import json
import os
from urllib.parse import urlsplit

from .qwen_native import QwenGenerationProfile, QwenNativeClient, transport_policy as shared_transport_policy
from .qwen_sse import QwenSSE
from .kimi_stream import StreamProtocolError

MODEL = 'qwen3.8-flash'
PROTOCOL = 'sx-qwen38-flash-native-tools-sse-v1'
GENERATION = 'sx-qwen38-flash-sse-low-total16k'
MAX_HIGH_GENERATION = 'sx-qwen38-max-sse-high-total16k'
URL_ENVS = ('SX_URL', 'SX_URL_SB')


def selected_url_env():
    name = os.environ.get('UI_KOBE_SX_URL_ENV', 'SX_URL')
    if name not in URL_ENVS:
        raise ValueError('SX URL must come from SX_URL or SX_URL_SB')
    return name


def resolve_base_url(url_env=None):
    name = url_env or selected_url_env()
    if name not in URL_ENVS:
        raise ValueError('Unknown SX URL environment variable')
    value = os.environ.get(name, '').strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError(name + ' must contain an HTTPS URL without embedded credentials/query')
    if not parsed.path:
        value += '/v1'
    elif not parsed.path.endswith('/v1'):
        raise ValueError(name + ' must be an origin or a /v1 API base URL')
    return value


@dataclass(frozen=True)
class SXGenerationProfile(QwenGenerationProfile):
    name: str = GENERATION
    reasoning_effort: str = 'low'


def generation_profile(name=GENERATION):
    if name == GENERATION:
        return SXGenerationProfile()
    if name == MAX_HIGH_GENERATION:
        return SXGenerationProfile(name=name, reasoning_effort='high')
    raise ValueError('Unknown frozen SX generation profile')


def model_for_profile(profile):
    generation_request_fields(profile)
    return 'qwen3.8-max' if profile.name == MAX_HIGH_GENERATION else MODEL


def generation_request_fields(profile):
    if profile != generation_profile(profile.name):
        raise ValueError('SX generation profile changed its frozen bounds')
    if profile.name == MAX_HIGH_GENERATION:
        return {'enable_thinking': True, 'reasoning_effort': 'high'}
    return {'reasoning_effort': 'low'}


def request_policy(profile):
    generation_request_fields(profile)
    return {'version': 'sx-native-request-policy-v1', 'stream': True, 'output_field': 'max_tokens',
            'include_usage': True, 'trust_env': False}


def transport_policy(budget=None):
    return {**shared_transport_policy(budget), 'version': 'sx-phase-aware-retry-v1',
            'upload_timeout_s': 120, 'outer_deadlines_unchanged': True,
            'endpoint_fallback': False, 'billing_status_402': 'stop immediately; no retry',
            'sse_created': 'gateway emits per-chunk timestamps; canonical first, raw stream and last preserved'}


class SXSSE(QwenSSE):
    """SX updates `created` per chunk; response/tool identities remain strict."""
    def __init__(self, model):
        super().__init__(model)
        self.first_created = self.last_created = None
        self.created_changes = 0

    def _add(self, value):
        if value == '[DONE]':
            return super()._add(value)
        data = json.loads(value)
        if isinstance(data, dict) and data.get('created') is not None:
            timestamp = data['created']
            if (type(timestamp) is not int or timestamp < 0
                    or (self.last_created is not None and timestamp < self.last_created)):
                raise StreamProtocolError('Invalid SX chunk timestamp', code='invalid_sse')
            if self.first_created is None:
                self.first_created = timestamp
            elif timestamp != self.last_created:
                self.created_changes += 1
            self.last_created = timestamp
            data['created'] = self.first_created
        super()._add(json.dumps(data, ensure_ascii=False))

    def observed(self):
        body = super().observed()
        body['sx_stream_metadata'] = {'created_semantics': 'per_chunk_timestamp',
            'first_created': self.first_created, 'last_created': self.last_created,
            'timestamp_changes': self.created_changes}
        return body


class SXNativeClient(QwenNativeClient):
    api_key_env = 'SX_QWEN_API_KEY'
    model_name = MODEL
    request_prefix = 'sx-'
    policy_for = staticmethod(request_policy)
    fields_for = staticmethod(generation_request_fields)
    write_timeout_s = 120

    def __init__(self, *, url_env=None, **kwargs):
        self.base_url = resolve_base_url(url_env)
        self.model_name = model_for_profile(kwargs['profile'])
        super().__init__(**kwargs)

    def accumulator(self):
        return SXSSE(self.model_name)
