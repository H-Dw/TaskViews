"""The same UI-KOBE-like and Mini actors served through OpenRouter."""
import os

from ui_kobe.api.openrouter_native import (BASE_URL, MODEL, PROTOCOL, GENERATION,
                                          generation_profile, OpenRouterNativeClient)
from . import telemetry
from .mini_taskviews_native import MiniTaskViewsNativeAgent
from .qwen_native_base import QwenNativeProvider, QwenTransitionNativeAgent


class OpenRouterNativeProvider(QwenNativeProvider):
    provider_name = 'openrouter'
    model_name = MODEL
    protocol = PROTOCOL

    def provider_profile(self, model, base_url, temperature, max_tokens):
        profile = generation_profile(os.environ.get('UI_KOBE_GENERATION_PROFILE', GENERATION))
        if (model, base_url, temperature, max_tokens) != (MODEL, BASE_URL, 0, profile.max_completion_tokens):
            raise ValueError('OpenRouter requires its frozen model, endpoint and output budget')
        return profile

    def provider_transport(self, api_key, trace):
        return OpenRouterNativeClient(api_key=api_key, budget=self.budget, profile=self.profile,
                                      emit=telemetry.emit, response_dir=trace / 'responses')

    def generation_fields(self, ledger, role):
        return {'max_tokens': ledger.allowance(role)}


class OpenRouterTransitionNativeAgent(OpenRouterNativeProvider, QwenTransitionNativeAgent):
    """Existing execution-edge retriever and checkpoint protocol."""


class OpenRouterMiniTaskViewsNativeAgent(OpenRouterNativeProvider, MiniTaskViewsNativeAgent):
    """Existing current/attempts/lessons fixed views."""
