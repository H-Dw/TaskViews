"""Tinker provider for the same two native CUA actors and Mini views."""
import os

from ui_kobe.api.tinker_native import (BASE_URL, MODEL, PROTOCOL, GENERATION,
                                      generation_profile, TinkerNativeClient)
from . import telemetry
from .mini_taskviews_native import MiniTaskViewsNativeAgent
from .qwen_native_base import QwenNativeProvider, QwenTransitionNativeAgent


class TinkerNativeProvider(QwenNativeProvider):
    provider_name = 'tinker'
    model_name = MODEL
    protocol = PROTOCOL

    def provider_profile(self, model, base_url, temperature, max_tokens):
        profile = generation_profile(os.environ.get('UI_KOBE_GENERATION_PROFILE', GENERATION))
        if (model, base_url, temperature, max_tokens) != (MODEL, BASE_URL, 0, profile.max_completion_tokens):
            raise ValueError('Tinker requires its frozen model, official endpoint and generation budget')
        return profile

    def provider_transport(self, api_key, trace):
        return TinkerNativeClient(api_key=api_key, budget=self.budget, profile=self.profile,
                                  emit=telemetry.emit, response_dir=trace / 'responses')

    def generation_fields(self, ledger, role):
        return {'max_tokens': ledger.allowance(role)}


class TinkerTransitionNativeAgent(TinkerNativeProvider, QwenTransitionNativeAgent):
    """Existing UI-KOBE-like retriever, checkpoints and image processing."""


class TinkerMiniTaskViewsNativeAgent(TinkerNativeProvider, MiniTaskViewsNativeAgent):
    """Existing fixed current/attempts/lessons views; no additional model role."""
