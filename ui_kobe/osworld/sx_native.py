"""SX transport on the shared actor, UI-KOBE-like retriever and Mini views."""
import os

from ui_kobe.api.sx_native import (MODEL, PROTOCOL, GENERATION, selected_url_env,
                                  resolve_base_url, generation_profile, model_for_profile, SXNativeClient)
from . import telemetry
from .mini_taskviews_native import MiniTaskViewsNativeAgent
from .qwen_native_base import QwenNativeProvider, QwenTransitionNativeAgent
from .kimi_native import KimiNativeAgent


class SXNativeProvider(QwenNativeProvider):
    provider_name = 'sx'
    model_name = MODEL
    protocol = PROTOCOL

    def provider_profile(self, model, base_url, temperature, max_tokens):
        self.sx_url_env = selected_url_env()
        profile = generation_profile(os.environ.get('UI_KOBE_GENERATION_PROFILE', GENERATION))
        self.model_name = model_for_profile(profile)
        self.protocol = f'sx-{self.model_name}-native-tools-sse-{profile.reasoning_effort}-v2'
        if (model, base_url, temperature, max_tokens) != (
                self.model_name, resolve_base_url(self.sx_url_env), 0, profile.max_completion_tokens):
            raise ValueError('SX requires its frozen model, environment endpoint and output budget')
        return profile

    def provider_transport(self, api_key, trace):
        return SXNativeClient(api_key=api_key, url_env=self.sx_url_env, budget=self.budget, profile=self.profile,
                              emit=telemetry.emit, response_dir=trace / 'responses')

    def generation_fields(self, ledger, role):
        return {'max_tokens': ledger.allowance(role)}


class SXTransitionNativeAgent(SXNativeProvider, QwenTransitionNativeAgent):
    """Same UI-KOBE-like execution-edge retriever."""


class SXMiniTaskViewsNativeAgent(SXNativeProvider, MiniTaskViewsNativeAgent):
    """Same fixed current, attempts and lessons views."""


class SXBaselineNativeAgent(SXNativeProvider, KimiNativeAgent):
    """Official-style native prompt/history/compiler, with passive audit only.

    The execution journal is never queried or added to model context. No edge
    retrieval, Mini geometry supplement, TaskViews or extra model roles.
    """
    transition_recording = True
    strict_native_input = True
