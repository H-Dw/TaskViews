"""AutoDL provider for the common native actor and current Mini views."""
import os

from ui_kobe.api.autodl_native import (BASE_URL, MODEL, PROTOCOL, GENERATION,
                                      AutoDLNativeClient, generation_profile)
from . import telemetry
from .kimi_native import KimiNativeAgent
from .mini_taskviews_native import MiniTaskViewsNativeAgent
from .qwen_native_base import QwenNativeProvider, QwenTransitionNativeAgent


class AutoDLNativeProvider(QwenNativeProvider):
    provider_name = 'autodl'
    model_name = MODEL
    protocol = PROTOCOL

    def provider_profile(self, model, base_url, temperature, max_tokens):
        profile = generation_profile(os.environ.get('UI_KOBE_GENERATION_PROFILE', GENERATION))
        if (model, base_url, temperature, max_tokens) != (MODEL, BASE_URL, 0, profile.max_completion_tokens):
            raise ValueError('AutoDL requires its frozen model, endpoint and output budget')
        return profile

    def provider_transport(self, api_key, trace):
        return AutoDLNativeClient(api_key=api_key, budget=self.budget, profile=self.profile,
                                  emit=telemetry.emit, response_dir=trace / 'responses')

    def generation_fields(self, ledger, role):
        return {'max_tokens': ledger.allowance(role)}


class AutoDLTransitionNativeAgent(AutoDLNativeProvider, QwenTransitionNativeAgent):
    """The existing execution-edge retriever with AutoDL transport."""


class AutoDLMiniTaskViewsNativeAgent(AutoDLNativeProvider, MiniTaskViewsNativeAgent):
    """Current Mini views and recovery with AutoDL transport."""


class AutoDLBaselineNativeAgent(AutoDLNativeProvider, KimiNativeAgent):
    """Common native loop with passive audit and no optional views."""
    transition_recording = True
    strict_native_input = True
