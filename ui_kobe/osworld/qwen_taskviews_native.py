"""Qwen native tools plus the audited TaskViews graph/checkpoint implementation.

This is a new provider protocol, not a claim of equivalence to the original
Qwen XML agent or to the completed Kimi comparison runs.
"""
from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, QwenGenerationProfile, QwenNativeClient
from . import telemetry
from .kimi_taskviews_native import KimiTaskViewsNativeAgent


class QwenTaskViewsNativeAgent(KimiTaskViewsNativeAgent):
    provider_name = 'qwen'
    model_name = MODEL
    protocol = PROTOCOL

    def provider_profile(self, model, base_url, temperature, max_tokens):
        profile = QwenGenerationProfile()
        if (model != MODEL or base_url != BASE_URL or temperature != 0 or max_tokens != profile.max_completion_tokens):
            raise ValueError('Qwen requires its frozen model, endpoint and 16000-token native profile')
        return profile

    def provider_transport(self, api_key, trace):
        return QwenNativeClient(api_key=api_key, budget=self.budget, profile=self.profile,
                                emit=telemetry.emit, response_dir=trace / 'responses')

    def generation_fields(self, ledger, role):
        return {'max_tokens': ledger.allowance(role)}
