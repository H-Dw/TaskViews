import json
import time

import httpx
import pytest

from ui_kobe.api.kimi_stream import (Completion, KimiStreamClient, SSEAccumulator,
    StreamBudget, StreamDeadlineError, StreamProtocolError)


def chunk(delta=None, finish=None, usage=None):
    value = {'id': 'c1', 'model': 'kimi-k3', 'created': 1,
             'choices': [] if usage else [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
    if usage:
        value['usage'] = usage
    return json.dumps(value)


USAGE = {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}


def fragments():
    return [chunk({'reasoning_content': '原始分析'}),
        chunk({'tool_calls': [{'index': 0, 'id': 'call1', 'type': 'function',
            'function': {'name': 'computer_use', 'arguments': '{"action":'}}]}),
        chunk({'tool_calls': [{'index': 0, 'function': {'arguments': '"left_click","coordinate":[100,200]}'}}]}),
        chunk(finish='tool_calls'), chunk(usage=USAGE), '[DONE]']


def test_native_sse_aggregates_all_fields_and_empty_choice_usage():
    accumulator = SSEAccumulator()
    for value in fragments():
        accumulator.add(value)
    data = accumulator.complete().model_dump()
    message = data['choices'][0]['message']
    assert message['reasoning_content'] == '原始分析'
    assert message['content'] is None
    assert message['tool_calls'][0]['function']['name'] == 'computer_use'
    assert json.loads(message['tool_calls'][0]['function']['arguments'])['coordinate'] == [100, 200]
    assert data['usage'] == USAGE


@pytest.mark.parametrize('fault', ['no_done', 'truncated', 'wrong_model'])
def test_stream_never_returns_incomplete_output(fault):
    values = fragments()
    if fault == 'no_done':
        values.pop()
    elif fault == 'no_usage':
        values.pop(-2)
    elif fault == 'truncated':
        values[3] = chunk(finish='length')
    else:
        values[0] = values[0].replace('kimi-k3', 'wrong-model')
    with pytest.raises(StreamProtocolError):
        a = SSEAccumulator()
        for value in values:
            a.add(value)
        a.complete()


def factory_for(handler):
    return lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs)


def test_real_httpx_sse_path_preserves_null_content_native_history(tmp_path):
    sent, events = [], []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text=''.join('data: ' + s + '\n\n' for s in fragments()),
                              headers={'x-request-id': 'server-1', 'content-type': 'text/event-stream'})
    c = KimiStreamClient(api_key='test-secret', http_factory=factory_for(handler), stream_dir=tmp_path,
                        emit=lambda event, **fields: events.append((event, fields)))
    first = c.create(messages=[{'role': 'user', 'content': 'first'}], max_completion_tokens=16000)
    message = first.model_dump()['choices'][0]['message']
    c.create(messages=[message, {'role': 'tool', 'tool_call_id': 'call1', 'content': 'receipt'}],
             max_completion_tokens=16000, tools=[{}], tool_choice='required')
    assert sent[1]['messages'][0] == message
    assert sent[1]['stream'] is True and sent[1]['stream_options']['include_usage'] is True
    assert sent[1]['reasoning_effort'] == 'max' and 'temperature' not in sent[1]
    assert c.last_timing['headers_s'] is not None and c.last_timing['first_tool_s'] is not None
    assert c.last_timing['server_request_id'] == 'server-1'
    assert sum(event == 'api_response' for event, _ in events) == 2
    assert 'test-secret' not in ''.join(p.read_text() for p in tmp_path.glob('*.jsonl'))


def test_complete_generation_deadline_is_not_extended_by_reader_thread():
    def handler(request):
        time.sleep(.15)
        return httpx.Response(200, text='')
    c = KimiStreamClient(api_key='test', budget=StreamBudget(.005, .01, .02, .03, 1, .04),
                        http_factory=factory_for(handler))
    started = time.monotonic()
    with pytest.raises(StreamDeadlineError):
        c.create(messages=[])
    assert time.monotonic() - started < .14


def test_wrong_model_not_silently_replaced():
    with pytest.raises(ValueError):
        KimiStreamClient(api_key='test').create(model='wrong', messages=[])


@pytest.mark.parametrize('values', [{'total_s': 100}, {'step_s': 900}, {'attempts': 3}, {'idle_s': float('inf')}])
def test_inconsistent_budgets_rejected(values):
    with pytest.raises(ValueError):
        StreamBudget(**values)


def test_native_cli_only_changes_agent_interface_flags():
    from scripts.osworld_task035_background import runner_command
    from scripts.run_official_qwen_task035 import parse_local_arguments
    command = runner_command({'model': 'kimi-k3', 'base_url': 'https://api.moonshot.ai/v1',
        'arm': 'baseline', 'agent_protocol': 'kimi-k3-native-tools-stream-v1',
        'official_results': '/tmp/result', 'run_dir': '/tmp/run'})
    local, official = parse_local_arguments(command[2:])
    assert local.native_kimi and not local.taskviews_config
    assert '--stream' in official and official[official.index('--max_steps') + 1] == '500'
    assert official[official.index('--sleep_after_execution') + 1] == '3'


def test_official_action_compilation_and_no_synthetic_done():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.home() / 'osworld2/OSWorld-V2'))
    from ui_kobe.osworld.kimi_native import validate_native
    from test_native_official_policy import relative_frame
    a = SSEAccumulator()
    for value in fragments():
        a.add(value)
    response = a.complete()
    arguments, batch = validate_native(response, relative_frame())
    assert arguments[0]['action'] == 'left_click' and batch.commands == ['pyautogui.click(192, 216)']
    data = response.model_dump()
    data['choices'][0]['message']['tool_calls'] = []
    data['choices'][0]['finish_reason'] = 'stop'
    arguments, batch = validate_native(Completion(data), relative_frame())
    assert arguments == [] and batch.commands == []


@pytest.mark.parametrize('arguments', ['{"action":"mouse_move"}', '{"action":"shell","text":"bad"}', '[1,2]'])
def test_native_rejects_bad_actions_before_controller(arguments):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.home() / 'osworld2/OSWorld-V2'))
    from ui_kobe.osworld.kimi_native import validate_native
    from test_native_official_policy import relative_frame
    a = SSEAccumulator()
    for value in fragments():
        a.add(value)
    data = a.complete().model_dump()
    data['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = arguments
    with pytest.raises(ValueError):
        validate_native(Completion(data), relative_frame())


def test_agent_keeps_exact_native_assistant_and_tool_history(monkeypatch, tmp_path):
    from io import BytesIO
    from PIL import Image
    from ui_kobe.osworld.kimi_native import KimiNativeAgent
    monkeypatch.setenv('KIMI_API_KEY', 'test')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    agent = KimiNativeAgent(model='kimi-k3', base_url='https://api.moonshot.ai/v1', temperature=1, max_tokens=16000,
                            coordinate_type='relative', model_screen_width=None, model_screen_height=None)
    accumulator = SSEAccumulator()
    for value in fragments():
        accumulator.add(value)
    response = accumulator.complete()
    sent = []
    class Stub:
        last_timing = {}
        def create(self, **kwargs):
            sent.append(kwargs)
            return response
    agent.client = Stub()
    png = BytesIO()
    Image.new('RGB', (1920, 1080)).save(png, 'PNG')
    for _ in range(2):
        _, actions = agent.predict('saved task', {'screenshot': png.getvalue()})
        assert actions == ['pyautogui.click(192, 216)']
    assert sent[1]['messages'][2] == response.model_dump()['choices'][0]['message']
    assert sent[1]['messages'][3]['role'] == 'tool'
    assert sent[1]['messages'][3]['tool_call_id'] == 'call1'
    assert sent[1]['tool_choice'] == 'auto'
    assert sent[1]['tools'][0]['function']['name'] == 'computer_use'
    assert sent[1]['messages'][-1]['content'][-1] == agent.frame.image
    # Whole old turns may leave the byte budget; retained assistant/tool pairs
    # stay exact and the current task and screenshot remain present.
    agent.turns[0][1]['reasoning_content'] = 'x' * 129000
    agent.predict('saved task', {'screenshot': png.getvalue()})
    assert agent.last_trace['history_turns_omitted'] == 1
    assert sent[2]['messages'][1]['role'] == 'user'


def test_native_launch_rejects_changed_code_and_unpassed_replays(monkeypatch, tmp_path):
    from scripts import launch_kimi_native_task035 as launch
    files = {'validation.json': {'exit_code': 0, 'code_hashes': {'a': 'original'}},
             'replay.json': {'passed': True, 'cases': [1, 2, 3]}, 'native-probe.json': {'passed': True}}
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data))
    monkeypatch.setattr(launch, 'code_hashes', lambda: {'a': 'changed'})
    with pytest.raises(RuntimeError, match='current interface'):
        launch.require_preparation(tmp_path)
    monkeypatch.setattr(launch, 'code_hashes', lambda: {'a': 'original'})
    (tmp_path / 'replay.json').write_text(json.dumps({'passed': False, 'cases': [1, 2, 3]}))
    with pytest.raises(RuntimeError, match='must pass'):
        launch.require_preparation(tmp_path)


@pytest.mark.parametrize('taskviews', [False, True])
@pytest.mark.parametrize('before_collapse_bytes', [127948, 127965, 128000])
def test_history_context_limit_keeps_original_pairs_and_current_frame(monkeypatch, tmp_path, taskviews, before_collapse_bytes):
    from copy import deepcopy
    from io import BytesIO
    from PIL import Image
    from ui_kobe.osworld.kimi_native import KimiNativeAgent
    from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent

    monkeypatch.setenv('KIMI_API_KEY', 'test')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', '046')
    agent_type = KimiTaskViewsNativeAgent if taskviews else KimiNativeAgent
    agent = agent_type(model='kimi-k3', base_url='https://api.moonshot.ai/v1', temperature=1, max_tokens=16000)
    accumulator = SSEAccumulator()
    for value in fragments():
        accumulator.add(value)
    response = accumulator.complete()
    sent = []

    class Stub:
        last_timing = {}
        def create(self, **kwargs):
            sent.append(deepcopy(kwargs))
            return response
        def close(self):
            pass

    if taskviews:
        agent.transport.close()
        agent.transport = agent.client.transport = Stub()
        monkeypatch.setattr(agent, 'build_views', lambda deadline: 'current model evidence')
    else:
        agent.client.close()
        agent.client = Stub()
    # Twenty complete old turns: one more image must collapse to retain the
    # current screenshot. Include multibyte text and exact assistant/tool IDs.
    for i in range(20):
        original = deepcopy(response.model_dump()['choices'][0]['message'])
        original['tool_calls'][0]['id'] = f'old-call-{i}'
        agent.turns.append([
            {'role': 'user', 'content': [{'type': 'text', 'text': '原始目标'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,old'}}]},
            original, {'role': 'tool', 'tool_call_id': f'old-call-{i}', 'content': 'unchanged receipt'}])
    def old_text(messages):
        return sum(len(json.dumps(m, ensure_ascii=False).encode('utf-8')) if m['role'] != 'user'
                   else sum(len(p.get('text', '').encode('utf-8')) for p in m['content']) for m in messages)
    initial = old_text([m for turn in agent.turns for m in turn])
    agent.turns[0][1]['reasoning_content'] += 'x' * (before_collapse_bytes - initial)
    saved = deepcopy(agent.turns)
    agent.total_steps = 20
    png = BytesIO()
    Image.new('RGB', (1920, 1080)).save(png, 'PNG')
    try:
        agent.predict('当前原文目标', {'screenshot': png.getvalue()})
        messages = sent[0]['messages']
        assert old_text(messages[1:-1]) <= 128000
        assert (agent.last_trace['retained_history_text_chars'] + agent.contract.context_reserve_chars
                <= agent.contract.context_max_text_chars)
        expected_drop = 1  # The oversized oldest turn leaves as a complete native ID/reply group.
        assert agent.last_trace['history_turns_omitted'] == expected_drop
        assert sum(p.get('type') == 'image_url' for m in messages if isinstance(m.get('content'), list)
                   for p in m['content']) <= 20
        assert 'Task: 当前原文目标' in messages[1]['content'][-1]['text']
        assert messages[-1]['content'][0]['type'] == 'image_url'
        assert not any('当前原文目标' in part.get('text', '') for part in messages[-1]['content'])
        assert [m for m in messages if m['role'] in ('assistant', 'tool')] == [
            m for turn in saved[expected_drop:] for m in turn[1:]]
    finally:
        agent.close()
