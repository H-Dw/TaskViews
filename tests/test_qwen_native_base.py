from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from ui_kobe.api.kimi_stream import Completion
from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, QwenGenerationProfile
from ui_kobe.osworld.kimi_native import KimiNativeAgent
from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
from ui_kobe.osworld.qwen_native_base import QwenNativeAgent, QwenNativeProvider, QwenTransitionNativeAgent
from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent


def test_provider_extraction_preserves_full_path_and_shared_native_loop():
    assert QwenTaskViewsNativeAgent.optional_context is KimiTaskViewsNativeAgent.optional_context
    for cls in (QwenNativeAgent, QwenTransitionNativeAgent, QwenTaskViewsNativeAgent):
        assert cls.predict is KimiNativeAgent.predict
        assert cls.provider_profile is QwenNativeProvider.provider_profile
        assert cls.provider_transport is QwenNativeProvider.provider_transport
        assert cls.generation_fields is QwenNativeProvider.generation_fields
        assert cls.protocol == PROTOCOL


@pytest.mark.parametrize('change', [{'model': 'other'}, {'base_url': 'https://other'},
                                   {'temperature': 1}, {'max_tokens': 32000}])
def test_frozen_provider_options_are_not_relaxed(change):
    args = dict(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
    with pytest.raises(ValueError, match='frozen model'):
        QwenNativeProvider().provider_profile(**{**args, **change})
    assert QwenNativeProvider().provider_profile(**args) == QwenGenerationProfile()


def test_native_baseline_and_edge_arm_do_not_initialize_full_views(monkeypatch, tmp_path):
    class Transport:
        last_timing = {}

        def create(self, **kwargs):
            self.request = kwargs
            return Completion({'choices': [{'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': 'Current image instruction', 'tool_calls': [{
                    'id': 'original-tool-id', 'type': 'function', 'function': {
                        'name': 'computer_use', 'arguments': json.dumps({'action': 'left_click'})}}]}}]})

        def close(self):
            pass

    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('QWEN_API_KEY', 'offline-placeholder')
    monkeypatch.delenv('UI_KOBE_CUA_CONTRACT_JSON', raising=False)
    monkeypatch.setattr(QwenNativeProvider, 'provider_transport', lambda *a: Transport())
    image = BytesIO()
    Image.new('RGB', (1920, 1080)).save(image, format='PNG')
    for cls in (QwenNativeAgent, QwenTransitionNativeAgent):
        actor = cls(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000)
        assert not hasattr(actor, 'control') and not hasattr(actor, 'modules')
        _, commands = actor.predict('Original user task', {'screenshot': image.getvalue()})
        assert commands == ['pyautogui.click()'] and actor.pending == 'original-tool-id'
        sent = actor.transport.request
        assert sent['max_tokens'] == 16000
        assert 'reasoning_effort' not in sent and 'max_completion_tokens' not in sent
        assert actor.turns[-1][-1]['tool_calls'][0]['id'] == 'original-tool-id'
        actor.close()


def test_generation_fields_use_the_original_role_allowance():
    ledger = SimpleNamespace(allowance=lambda role: 4000 if role == 'perception' else 16000)
    assert QwenNativeProvider().generation_fields(ledger, 'executor') == {'max_tokens': 16000}
    assert QwenNativeProvider().generation_fields(ledger, 'perception') == {'max_tokens': 4000}
