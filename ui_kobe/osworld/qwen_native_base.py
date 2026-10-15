"""Frozen Qwen provider on the shared native loop, independent of TaskViews."""
import os

from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, generation_profile, QwenNativeClient, request_policy
from . import telemetry
from .kimi_native import KimiNativeAgent
from .kimi_transition_native import KimiTransitionNativeAgent
from .taskviews_profiles import UI_KOBE_PROFILE


class QwenNativeProvider:
    provider_name = 'qwen'
    model_name = MODEL
    protocol = PROTOCOL

    def provider_profile(self, model, base_url, temperature, max_tokens):
        profile = generation_profile(os.environ.get('UI_KOBE_GENERATION_PROFILE', 'qwen-native-16k'))
        if (model != MODEL or base_url != BASE_URL or temperature != 0 or max_tokens != profile.max_completion_tokens):
            raise ValueError('Qwen requires its frozen model, endpoint and 16000-token native profile')
        return profile

    def provider_transport(self, api_key, trace):
        return QwenNativeClient(api_key=api_key, budget=self.budget, profile=self.profile,
                                emit=telemetry.emit, response_dir=trace / 'responses')

    def generation_fields(self, ledger, role):
        profile = getattr(self, 'profile', generation_profile())
        return {request_policy(profile)['output_field']: ledger.allowance(role)}

    def current_frame_content(self):
        from ui_kobe.api.qwen_png_transport import recompress
        content = super().current_frame_content()
        result = []
        for part in content:
            if part.get('type') != 'image_url':
                result.append(part)
                continue
            contract = getattr(self, 'contract', None)
            target = (max(0, contract.context_max_payload_chars - contract.context_max_text_chars
                          - contract.context_reserve_chars) if contract is not None else None)
            url, record = recompress(part['image_url']['url'],
                                    (self.frame.screenshot.model_width, self.frame.screenshot.model_height),
                                    target_data_url_chars=target)
            result.append({**part, 'image_url': {**part['image_url'], 'url': url}})
            telemetry.emit('qwen_image_transport', frame_id=self.frame.metadata['frame_id'],
                           source_screenshot_sha256=self.frame.original_sha256, **record)
        return result


class QwenNativeAgent(QwenNativeProvider, KimiNativeAgent):
    """No graph, roles, pointer workflow or TaskViews control initialization."""


class QwenTransitionNativeAgent(QwenNativeProvider, KimiTransitionNativeAgent):
    """The existing UI-KOBE-like edge retriever with the same Qwen transport."""
    checkpoint_profile = UI_KOBE_PROFILE
    strict_native_input = True

    def checkpoint_ready(self):
        return hasattr(self, 'context_provider')

    def flush_execution(self):
        from .checkpoints import ReadAnomaly
        journal = self.execution_journal
        if (journal is None and self.total_steps) or (journal and (journal.closed or journal.read_only)):
            raise ReadAnomaly('UI-KOBE-like checkpoint needs its live original journal')

    def checkpoint_state(self):
        return {'profile': UI_KOBE_PROFILE}

    def restore_checkpoint_state(self, value):
        from .checkpoints import ReadAnomaly
        if value != self.checkpoint_state():
            raise ReadAnomaly('UI-KOBE-like checkpoint profile changed')
        self.cached_context = self.context_provider.cached = None
