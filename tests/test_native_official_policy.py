"""Offline equivalence to the pinned official action compiler, no GUI/API effects."""
import json
import time

import httpx
import pytest

from ui_kobe.api.kimi import generation_profile
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import Completion, KimiStreamClient, StreamProtocolError
from ui_kobe.osworld.kimi_native import native_schema as schema_for_frame, validate_native as validate_for_frame
from ui_kobe.osworld.cua_contract import CUAFrame
from test_native_generation_budget import make_agent


def relative_frame():
    from mm_agents.qwen.images import ProcessedScreenshot
    return CUAFrame(ProcessedScreenshot('', 'relative', 1920, 1080, 1920, 1080), 'offline', 1)


def native_schema():
    return schema_for_frame(relative_frame())


def validate_native(response):
    return validate_for_frame(response, relative_frame())


def candidate(arguments):
    return Completion({'id': 'batch', 'model': 'kimi-k3', 'usage': None, 'choices': [{
        'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'reasoning_content': 'exact reasoning', 'tool_calls': [
            {'id': f'call-{i}', 'type': 'function', 'function': {'name': 'computer_use',
             'arguments': json.dumps(value)}} for i, value in enumerate(arguments)]}}]})


@pytest.mark.parametrize('arguments', [
    [{'action': 'left_click', 'coordinate': [100, 200]}] * 9,
    [{'action': 'type', 'text': 12}],
    [{'action': 'type', 'text': 'a' * 5001}],
    [{'action': 'key_up', 'keys': ['a', 'b']}],
    [{'action': 'terminate'}],
    [{'action': 'left_click', 'extra': 1}],
    [{'action': 'left_click_drag', 'coordinate': [100, 200], 'duration': 31}],
])
def test_native_action_policy_is_exactly_official(arguments):
    from mm_agents.qwen.actions import translate_tool_calls
    from mm_agents.qwen.images import ProcessedScreenshot
    from mm_agents.qwen.parser import ToolCall
    from mm_agents.qwen.prompts import build_tool_schema
    _, actual = validate_native(candidate(arguments))
    expected = translate_tool_calls([ToolCall(value, 0, 0) for value in arguments],
        screenshot=ProcessedScreenshot('', 'relative', 1920, 1080, 1920, 1080),
        coordinate_type='relative', enable_zoom=False)
    assert actual == expected
    assert native_schema() == build_tool_schema(coordinate_type='relative', model_width=1920,
                                                model_height=1080, enable_zoom=False)


def test_entire_batch_rejected_if_one_call_invalid():
    with pytest.raises(StreamProtocolError) as caught:
        validate_native(candidate([{'action': 'left_click'}, {'action': 'mouse_move'}]))
    assert caught.value.retryable


def test_coordinate_bounds_remain_an_official_validation():
    from mm_agents.qwen.actions import ActionValidationError, translate_tool_calls
    from mm_agents.qwen.images import ProcessedScreenshot
    from mm_agents.qwen.parser import ToolCall
    value = {'action': 'left_click', 'coordinate': [-1, 1200]}
    with pytest.raises(ActionValidationError):
        translate_tool_calls([ToolCall(value, 0, 0)],
            screenshot=ProcessedScreenshot('', 'relative', 1920, 1080, 1920, 1080),
            coordinate_type='relative', enable_zoom=False)
    with pytest.raises(StreamProtocolError):
        validate_native(candidate([value]))


@pytest.mark.parametrize('bad_delta', [False, True])
def test_nine_call_sse_drains_to_final_usage_before_accept_or_repair(tmp_path, bad_delta):
    rows = []
    for i in range(9):
        rows.append({'id': 'batch', 'model': 'kimi-k3', 'choices': [{'delta': {'tool_calls': [{
            'index': -1 if bad_delta and i == 8 else i, 'id': f'call-{i}', 'type': 'function',
            'function': {'name': 'computer_use', 'arguments': '{"action":"left_click"}'}}]}}]})
    rows.extend([{'id': 'batch', 'model': 'kimi-k3', 'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]},
                 {'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130}}])
    body = ''.join('data: ' + json.dumps(row) + '\n\n' for row in rows) + 'data: [DONE]\n\n'
    events = []
    ledger = StepLedger(generation_profile(), time.monotonic() + 50, lambda *a, **k: None)
    client = KimiStreamClient(api_key='offline', profile=generation_profile(), stream_dir=tmp_path,
        emit=lambda name, **value: events.append((name, value)),
        http_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body)), **kwargs))
    if bad_delta:
        with pytest.raises(StreamProtocolError) as caught:
            client.create(messages=[], step_ledger=ledger)
        assert caught.value.retryable
    else:
        result = client.create(messages=[], step_ledger=ledger)
        assert len(validate_native(result)[1].commands) == 9
    outcome = next(value for name, value in events if name == 'request_outcome')
    assert outcome['stream_done'] and outcome['usage']['total_tokens'] == 130
    assert ledger.snapshot()['known_usage']['total_tokens'] == 130


def test_batch_commands_not_joined_and_feedback_ids_preserved(monkeypatch, tmp_path):
    agent, obs = make_agent(monkeypatch, tmp_path)
    completion = candidate([{'action': 'key_up', 'keys': ['a', 'b']}, {'action': 'left_click'}])
    class Transport:
        last_timing = {}
        def create(self, **kwargs):
            self.request = kwargs
            return completion
        def close(self):
            pass
    agent.client.close()
    agent.client = Transport()
    _, commands = agent.predict('original task', obs)
    assert commands == ['pyautogui.keyUp("a")', 'pyautogui.keyUp("b")', 'pyautogui.click()']
    for command in commands:
        agent.record_execution(command, receipts=[{'result': {'status': 'error', 'returncode': 1}}])
    agent.predict('original task', obs)
    messages = agent.client.request['messages']
    assert messages[2] == completion.model_dump()['choices'][0]['message']
    assert [m['tool_call_id'] for m in messages if m['role'] == 'tool'] == ['call-0', 'call-1']
    assert len(json.loads(messages[3]['content'])['executions']) == 2
    assert json.loads(messages[4]['content'])['executions'][0]['controller_receipts'][0]['result']['returncode'] == 1
    agent.close()


def test_two_repairs_then_complete_batch_without_resetting_step_budget(monkeypatch, tmp_path):
    agent, obs = make_agent(monkeypatch, tmp_path)
    calls = []
    class Transport:
        last_timing = {}
        def create(self, **kwargs):
            calls.append(kwargs)
            return candidate([{'action': 'shell'}] if len(calls) < 3 else [{'action': 'left_click'}] * 9)
        def close(self):
            pass
    agent.client.close()
    agent.client = Transport()
    _, commands = agent.predict('goal', obs)
    assert len(calls) == 3 and len(commands) == 9
    assert len({c['deadline'] for c in calls}) == 1
    assert agent.step_ledger.regenerations == 2
    agent.close()


def test_passive_hooks_return_failed_controller_receipt_without_gate(monkeypatch):
    import sys
    from types import SimpleNamespace
    from ui_kobe.osworld import telemetry
    result = {'status': 'error', 'returncode': 1}
    returned = ({'screenshot': b''}, 0, False, {'controller_error': True})
    class Agent:
        def predict(self, instruction, obs):
            return '', ['command']
        def record_execution(self, action, **kwargs):
            raise ValueError('diagnostic-only recording failed')
    class Controller:
        def execute_python_command(self, command):
            return result
    class Env:
        def step(self, action):
            assert Controller().execute_python_command(action) is result
            return returned
        def evaluate(self):
            return 0.5
        def close(self):
            return None
    monkeypatch.setitem(sys.modules, 'mm_agents.qwen', SimpleNamespace(QwenAgent=Agent))
    monkeypatch.setitem(sys.modules, 'desktop_env.desktop_env', SimpleNamespace(DesktopEnv=Env))
    monkeypatch.setitem(sys.modules, 'desktop_env.controllers.python', SimpleNamespace(PythonController=Controller))
    monkeypatch.setattr(telemetry, 'install_api', lambda root: None)
    monkeypatch.setattr(telemetry, '_installed', False)
    monkeypatch.setattr(telemetry, 'emit', lambda *args, **kwargs: None)
    telemetry.install(None)
    Agent().predict('goal', {})
    assert Env().step('command') == returned
    assert Env().evaluate() == 0.5
