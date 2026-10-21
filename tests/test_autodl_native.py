from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import time

import httpx
from PIL import Image
import pytest

from scripts import verified_invoice as verified
from scripts.run_official_native_tasks import agent_class
from ui_kobe.api import autodl_native as api
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import OutputTokenLimitError, ProviderQuotaBlocked, StreamProtocolError
from ui_kobe.api.qwen_native import QwenTransportBudget
from ui_kobe.osworld.autodl_native import AutoDLNativeProvider, AutoDLMiniTaskViewsNativeAgent
from ui_kobe.osworld.cua_contract import CUAContract, options_contract
from ui_kobe.osworld.kimi_native import KimiNativeAgent
from ui_kobe.osworld.transitions import TransitionJournal


def response_bytes(*, done=True, model=api.MODEL, finish='tool_calls', usage=True):
    def frame(delta=None, finish=None, usage=None):
        body = {'id': 'autodl-offline-response', 'model': model, 'created': 1,
                'choices': [] if usage else [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
        if usage:
            body['usage'] = usage
        return ('data: ' + json.dumps(body, ensure_ascii=False) + '\n\n').encode()
    result = (frame({'role': 'assistant', 'content': None, 'reasoning_content': '离线样例'})
        + frame({'content': '观察当前窗口', 'tool_calls': [{'index': 0, 'id': 'original-autodl-tool',
            'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{"action":'}}]})
        + frame({'tool_calls': [{'index': 0, 'function': {'arguments': '"mouse_move","coordinate":[4,3]}'}}]})
        + frame(finish=finish))
    if usage:
        result += frame(usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15})
    return result + (b'data: [DONE]\n\n' if done else b'')


class Chunks(httpx.SyncByteStream):
    def __init__(self, raw):
        self.raw = raw

    def __iter__(self):
        for i in range(0, len(self.raw), 7):
            yield self.raw[i:i+7]


def setup(tmp_path, handler, attempts=1):
    profile = api.generation_profile()
    events, waits = [], []
    ledger = StepLedger(profile, time.monotonic() + 930, lambda *a, **k: None)
    client = api.AutoDLNativeClient(api_key='offline-autodl-secret', profile=profile,
        budget=QwenTransportBudget(attempts=attempts), response_dir=tmp_path,
        emit=lambda name, **fields: events.append({'event': name, **deepcopy(fields)}), sleep=waits.append,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, ledger, events, waits


def invoke(client, ledger, **extra):
    return client.create(model=api.MODEL, messages=extra.pop('messages', []), max_tokens=16000,
                         step_ledger=ledger, budget_role='executor', deadline=ledger.deadline, **extra)


@pytest.mark.parametrize('usage', [False, True])
def test_stream_fragments_images_history_usage_and_raw_evidence(tmp_path, usage):
    raw, requests = response_bytes(usage=usage), []
    def handler(request):
        assert str(request.url) == api.BASE_URL + '/chat/completions'
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks(raw))
    client, ledger, events, waits = setup(tmp_path, handler)
    history = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]},
               {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'old', 'type': 'function',
                    'function': {'name': 'computer_use', 'arguments': '{}'}}]},
               {'role': 'tool', 'tool_call_id': 'old', 'content': 'Synthetic result'}]
    try:
        result = invoke(client, ledger, messages=history).model_dump()
        payload = requests[0]
        assert payload['model'] == api.MODEL and payload['stream'] is True
        assert payload['max_tokens'] == 16000 and payload['messages'] == history
        assert payload['stream_options'] == {'include_usage': True}
        assert not any(k in payload for k in ('enable_thinking', 'reasoning_effort', 'preserve_thinking',
                                              'reasoning', 'provider', 'max_completion_tokens'))
        message = result['choices'][0]['message']
        assert message['content'] == '观察当前窗口' and message['reasoning_content'] == '离线样例'
        assert message['tool_calls'][0]['id'] == 'original-autodl-tool'
        assert json.loads(message['tool_calls'][0]['function']['arguments'])['coordinate'] == [4, 3]
        assert (result['usage'] is not None) == usage
        assert ledger.snapshot()['unknown_usage_requests'] == (0 if usage else 1)
        assert next(tmp_path.glob('*.sse')).read_bytes() == raw and not waits
        assert any(e['event'] == 'api_response' for e in events)
    finally:
        client.close()


@pytest.mark.parametrize('status,error', [(400, httpx.HTTPStatusError), (401, httpx.HTTPStatusError),
                                         (403, httpx.HTTPStatusError), (402, ProviderQuotaBlocked)])
def test_failed_provider_never_falls_back_and_does_not_leak_key(tmp_path, status, error):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, json={'error': {'message': 'offline-autodl-secret'}})
    client, ledger, events, waits = setup(tmp_path, handler, attempts=6)
    try:
        with pytest.raises(error):
            invoke(client, ledger)
        assert seen == [api.BASE_URL + '/chat/completions'] and not waits
        assert 'offline-autodl-secret' not in json.dumps(events)
        assert all('offline-autodl-secret' not in p.read_text() for p in tmp_path.iterdir())
        assert ledger.snapshot()['unknown_usage_requests'] == 1
    finally:
        client.close()


@pytest.mark.parametrize('change,error', [({'done': False}, StreamProtocolError),
    ({'model': 'qwen3.8-max'}, StreamProtocolError), ({'finish': 'length'}, OutputTokenLimitError)])
def test_incomplete_or_foreign_stream_never_becomes_an_action(tmp_path, change, error):
    client, ledger, events, _ = setup(tmp_path, lambda _: httpx.Response(200,
        headers={'content-type': 'text/event-stream'}, content=response_bytes(**change)))
    try:
        with pytest.raises(error):
            invoke(client, ledger)
        assert not any(e['event'] == 'api_response' for e in events)
    finally:
        client.close()


def test_credentials_are_explicit_and_redacted(monkeypatch, tmp_path):
    from ui_kobe.osworld.telemetry import safe
    monkeypatch.delenv(api.API_KEY_ENV, raising=False)
    monkeypatch.setenv('QWEN_API_KEY', 'wrong-provider-key')
    monkeypatch.setenv('SX_QWEN_API_KEY', 'wrong-provider-key')
    kwargs = dict(profile=api.generation_profile(), budget=QwenTransportBudget(),
                  emit=lambda *a, **k: None, response_dir=tmp_path)
    with pytest.raises(ValueError, match='AUTODL_API_KEY'):
        api.AutoDLNativeClient(**kwargs)
    monkeypatch.setenv(api.API_KEY_ENV, 'offline-autodl-secret')
    client = api.AutoDLNativeClient(**kwargs)
    try:
        assert client.key == 'offline-autodl-secret' and client.client._trust_env is False
        assert safe('echo offline-autodl-secret') == 'echo [REDACTED]'
    finally:
        client.close()


def test_frozen_profile_and_default_plan_do_not_rewrite_legacy():
    plan = verified.specification()
    assert plan['provider'] == 'autodl' and plan['experiment'] == 'autodl-mini40'
    assert plan['model'] == api.MODEL and plan['base_url'] == api.BASE_URL
    assert plan['api_key_env'] == api.API_KEY_ENV and plan['generation_fields'] == {}
    assert plan['arms'] == ['taskviews'] and plan['max_steps'] == 40
    assert plan['execution_authorized'] is False and plan['live_provider_check_required']
    assert plan['mini_grounding_check_required']
    assert plan['generation_profile']['reasoning_effort'] == 'provider_default'
    assert verified.specification('qwen')['model'] == 'qwen3.8-max'
    assert verified.specification('qwen')['max_steps'] == 35
    with pytest.raises(ValueError):
        api.generation_request_fields(replace(api.generation_profile(), max_completion_tokens=32000))
    for provider, experiment in [('sx', 'autodl-mini40'), ('autodl', 'sx-mini-max-high40'), ('autodl', 'legacy-low35')]:
        with pytest.raises(ValueError):
            verified.specification(provider, experiment=experiment)
    _, budget, _, _ = options_contract({}, provider='autodl', generation_profile=api.generation_profile())
    assert budget.attempts == 6
    with pytest.raises(ValueError, match='provider-controlled'):
        options_contract({'enable_thinking': True}, provider='autodl', generation_profile=api.generation_profile())


@pytest.mark.parametrize('task', ['invoice', 'gimp', 'vlc'])
def test_all_current_tasks_select_autodl_without_using_old_experiment_labels(task):
    for experiment, arms in verified.AUTODL_EXPERIMENTS.items():
        plan = verified.specification(task_key=task, experiment=experiment)
        assert plan['task_key'] == task and plan['arms'] == list(arms)
        assert plan['cua_contract']['context_max_payload_chars'] == 12_000_000


def test_cli_default_and_explicit_legacy_selection(monkeypatch, tmp_path):
    import sys
    captured = []
    monkeypatch.setattr(verified, 'prepare', lambda args: captured.append(verified.specification(
        args.provider, args.sx_url_env, args.coordinate_type, args.experiment)))
    for options in ([], ['--provider', 'qwen']):
        monkeypatch.setattr(sys, 'argv', ['verified_invoice.py', 'prepare', '--root', str(tmp_path), *options])
        verified.main()
    assert [p['model'] for p in captured] == [api.MODEL, 'qwen3.8-max']


def test_search_requires_its_own_explicit_capability_and_credentials():
    from ui_kobe.api.keyboard_research import settings
    with pytest.raises(ValueError, match='explicit keyboard research'):
        settings(verified.specification())
    config = settings(verified.specification(), {'protocol': 'responses', 'model': 'search-fixture',
        'api_key_env': 'KEYBOARD_RESEARCH_API_KEY', 'base_url': 'https://search.example/v1'})
    assert config['api_key_env'] == 'KEYBOARD_RESEARCH_API_KEY'
    assert config['base_url'] == 'https://search.example/v1'


def test_mini_uses_autodl_stream_through_original_predict_and_four_views(monkeypatch, tmp_path):
    from test_mini_taskviews import predict
    plan = verified.specification()
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_GENERATION_PROFILE', api.GENERATION)
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_PROFILE', 'mini_fixed_v1')
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_FEEDBACK_V10', '0')
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', '[]')
    monkeypatch.setenv('UI_KOBE_TASK_KEYBOARD_RESEARCH', '')
    monkeypatch.setenv('UI_KOBE_CUA_CONTRACT_JSON', json.dumps(plan['cua_contract']))
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=response_bytes())
    monkeypatch.setattr(AutoDLNativeProvider, 'provider_transport', lambda *a: setup(tmp_path, handler)[0])
    cls = agent_class('autodl-native', 'taskviews', 'mini_fixed_v1')
    assert cls is AutoDLMiniTaskViewsNativeAgent and cls.predict is KimiNativeAgent.predict
    actor = cls(model=api.MODEL, base_url=api.BASE_URL, temperature=0, max_tokens=16000)
    actor.execution_journal = TransitionJournal(tmp_path / 'journal', task_id='fixture', run_id='fixture',
                                               contract=CUAContract(**plan['cua_contract']))
    image = BytesIO()
    Image.new('RGB', (1920, 1080)).save(image, format='PNG')
    try:
        commands = predict(actor, {'screenshot': image.getvalue()}, dispatch=False)
        assert commands == ['pyautogui.moveTo(4, 3)']
        packets = [json.loads(part['text'].split('\n', 1)[1])
                   for part in requests[0]['messages'][-1]['content']
                   if part.get('type') == 'text' and part.get('text', '').startswith('TaskViews:')]
        assert len(requests) == 1 and len(packets) == 1
        assert set(packets[0]['views']) == {'current', 'keyboard', 'attempts', 'lessons'}
        assert actor.pending == 'original-autodl-tool'
    finally:
        actor.close()
