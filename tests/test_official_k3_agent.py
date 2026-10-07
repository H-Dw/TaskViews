from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from mm_agents.qwen.main import QwenAgent
from mm_agents.qwen.client import Completion as OfficialCompletion
from ui_kobe.api.kimi_stream import Completion, SSEAccumulator, StreamProtocolError, OutputTokenLimitError
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.kimi_official import OfficialK3Agent, OfficialK3TaskViewsAgent
from test_cua_contract import png
from ui_kobe.api.kimi import content_text


def xml(action='mouse_move', extra='<parameter=coordinate>[100, 100]</parameter>'):
    return '<tool_call><function=computer_use><parameter=action>' + action + '</parameter>' + extra + '</function></tool_call>'


class Transport:
    def __init__(self, contents):
        self.contents, self.requests = list(contents), []

    def create(self, **request):
        self.requests.append(deepcopy(request))
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        message = {'role': 'assistant', 'content': content, 'reasoning_content': 'original reasoning ' + str(len(self.requests))}
        if isinstance(content, dict):
            message = content
        return Completion({'choices': [{'finish_reason': 'stop', 'message': message}],
                           'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}})

    def close(self):
        pass


def build(cls, monkeypatch, path, contents):
    monkeypatch.setenv('KIMI_API_KEY', 'offline-only')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(path))
    monkeypatch.setenv('UI_KOBE_TASK_ID', 'compatibility')
    monkeypatch.setenv('UI_KOBE_GENERATION_PROFILE', 'low-16k')
    monkeypatch.setenv('UI_KOBE_CUA_CONTRACT_JSON', json.dumps(CUAContract().snapshot()))
    agent = cls(model='kimi-k3', base_url='https://api.moonshot.ai/v1', max_tokens=16000)
    agent.client.transport.close()
    agent.client.transport = Transport(contents)
    if agent.context_provider:
        agent.context_provider.transport = agent.client.transport
    return agent


def test_official_methods_are_inherited_and_baseline_messages_match_reference(monkeypatch, tmp_path):
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [xml()])
    for method in ('predict', '_system_prompt', '_prepare_messages', '_parse_with_repairs', '_apply_terminal_judge', '_payload'):
        assert getattr(OfficialK3Agent, method) is getattr(QwenAgent, method)
        assert getattr(OfficialK3TaskViewsAgent, method) is getattr(QwenAgent, method)
    agent.predict('literal goal', {'screenshot': png()})
    request = agent.client.transport.requests[0]
    # Reconstruct the exact original pre-completion state, then compare messages.
    response, action, count = agent.responses.pop(), agent.actions.pop(), agent.tool_call_counts.pop()
    assert request['messages'] == QwenAgent._messages(agent, 'literal goal', agent.frame.screenshot)
    agent.responses.append(response)
    agent.actions.append(action)
    agent.tool_call_counts.append(count)
    agent.close()


def test_original_reasoning_restored_for_history_and_official_xml_repair(monkeypatch, tmp_path):
    invalid = xml(extra='<parameter=coordinate>[1921, 100]</parameter>')
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [invalid, xml(), xml('wait', '')])
    _, commands = agent.predict('goal', {'screenshot': png()})
    assert len(commands) == 1 and len(agent.client.transport.requests) == 2
    repaired = agent.client.transport.requests[1]
    assert repaired['messages'][-2]['content'] == invalid
    assert repaired['messages'][-2]['reasoning_content'] == 'original reasoning 1'
    assert 'corrected complete XML' in repaired['messages'][-1]['content'][0]['text']
    assert repaired['deadline'] == agent.client.transport.requests[0]['deadline']
    agent.predict('goal', {'screenshot': png(), 'user_response': 'original user response'})
    request = agent.client.transport.requests[-1]
    assistant = next(m for m in request['messages'] if m['role'] == 'assistant')
    assert assistant == {'role': 'assistant', 'content': xml(), 'reasoning_content': 'original reasoning 2'}
    assert agent.user_responses[2] == 'original user response'
    assert agent.tool_call_counts == [1, 1] and len(agent.responses) == 2
    agent.close()


@pytest.mark.parametrize('label', ['task059-taskviews', 'task046-baseline', 'task046-taskviews'])
def test_sealed_empty_content_sse_uses_official_normalization_and_preserves_history(monkeypatch, tmp_path, label):
    fixtures = Path(__file__).parent / 'fixtures/k3-empty-content'
    data = (fixtures / (label + '.jsonl')).read_bytes()
    provenance = json.loads((fixtures / 'provenance.json').read_text())
    original = next(case for case in provenance['cases'] if case['fixture'] == label + '.jsonl')
    assert hashlib.sha256(data).hexdigest() == original['sha256']
    accumulator = SSEAccumulator()
    for line in data.decode().splitlines():
        accumulator.add(json.loads(line)['data'])
    raw = accumulator.complete().model_dump()
    message = raw['choices'][0]['message']
    assert raw['choices'][0]['finish_reason'] == 'stop' and accumulator.done
    assert message['content'] is None and message['reasoning_content']
    assert raw['usage']['total_tokens'] == raw['usage']['prompt_tokens'] + raw['usage']['completion_tokens']
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [message, xml('wait', '')])
    returned, commands = agent.predict('literal goal', {'screenshot': png()})
    assert commands == [] and message['reasoning_content'] in returned
    assert len(agent.client.transport.requests) == 1  # No fabricated XML or extra action repair.
    _, following = agent.predict('literal goal', {'screenshot': png(), 'user_response': 'original reply'})
    history = [entry for entry in agent.client.transport.requests[1]['messages'] if entry['role'] == 'assistant']
    assert history == [message] and history[0]['content'] is None
    assert following == ['WAIT'] and not agent.client.repairs
    agent.close()


@pytest.mark.parametrize('fields', [{}, {'content': None, 'reasoning_content': None},
    {'content': [{'text': 'text'}], 'reasoning': 'fallback reasoning'}])
def test_xml_completion_field_normalization_matches_pinned_client(monkeypatch, tmp_path, fields):
    from mm_agents.qwen.client import _text
    message = {'role': 'assistant', **fields}
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [message])
    # Initialize the same ledger/frame as predict without changing the parser.
    screenshot = agent._process_observation(png())
    completion = agent.client.complete(agent._payload(agent._messages('goal', screenshot)))
    reasoning = fields.get('reasoning_content')
    if reasoning is None:
        reasoning = fields.get('reasoning')
    assert completion == OfficialCompletion(_text(reasoning), _text(fields.get('content')))
    assert agent.client.restore_messages([{'role': 'assistant', 'content': completion.rendered(True)}]) == [message]
    agent.close()


def test_taskviews_changes_only_optional_context_and_uses_same_acting_image(monkeypatch, tmp_path):
    agent = build(OfficialK3TaskViewsAgent, monkeypatch, tmp_path, [xml()])
    provider = agent.context_provider
    seen = []
    def views(deadline):
        seen.append((provider.frame.image, deadline))
        return '{"module":"prepare","effects_verified":false}'
    monkeypatch.setattr(provider, 'build_views', views)
    agent.predict('literal goal', {'screenshot': png()})
    request = agent.client.transport.requests[0]
    assert request['messages'][-1]['content'][1]['text'].startswith('TaskViews evidence')
    assert next(x for x in request['messages'][-1]['content'] if x['type'] == 'image_url') == seen[0][0]
    assert seen[0][1] < request['deadline']
    assert len(agent.client.transport.requests) == 1
    assert 'module' not in agent.responses[0]
    agent.close()


def test_optional_context_error_keeps_literal_task_and_actor(monkeypatch, tmp_path):
    agent = build(OfficialK3TaskViewsAgent, monkeypatch, tmp_path, [xml()])
    def fail(_):
        raise OSError('memory projection unavailable')
    monkeypatch.setattr(agent.context_provider, 'build_views', fail)
    _, commands = agent.predict('literal goal', {'screenshot': png()})
    assert commands
    assert any('literal goal' in content_text(m['content']) for m in agent.client.transport.requests[0]['messages'])
    assert 'unavailable' in agent.context_provider.cached
    agent.close()


def test_collision_is_not_resolved_by_guessing_reasoning(monkeypatch, tmp_path):
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [])
    for reasoning in ('one', 'two'):
        agent.client.remember(OfficialCompletion(reasoning, 'same'),
            {'role': 'assistant', 'content': 'same', 'reasoning_content': reasoning})
    with pytest.raises(StreamProtocolError, match='ambiguous'):
        agent.client.restore_messages([{'role': 'assistant', 'content': 'same'}])
    restored = agent.client.restore_messages([{'role': 'assistant', 'content': OfficialCompletion('one', 'same').rendered(True)}])
    assert restored[0]['reasoning_content'] == 'one'
    agent.reset()
    assert not agent.client.history and not agent.responses
    agent.close()


@pytest.mark.parametrize('content', [{'role': 'assistant', 'content': '', 'reasoning_content': 'reason',
    'tool_calls': [{'id': 'x', 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{}'}}]},
    OutputTokenLimitError({'usage': {'completion_tokens': 16000}})])
def test_native_mismatch_and_length_never_execute_or_switch_interface(monkeypatch, tmp_path, content):
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [content])
    with pytest.raises(StreamProtocolError):
        agent.predict('goal', {'screenshot': png()})
    assert not agent.responses and len(agent.client.transport.requests) == 1
    agent.close()


def test_no_extra_coordinate_or_terminal_parser(monkeypatch, tmp_path):
    agent = build(OfficialK3Agent, monkeypatch, tmp_path, [xml('terminate', '<parameter=status>success</parameter>')])
    _, commands = agent.predict('goal', {'screenshot': png()})
    assert commands == ['DONE'] and len(agent.client.transport.requests) == 1
    agent.close()


def test_taskviews_consumes_shared_transition_records_across_actual_predictions(monkeypatch, tmp_path):
    from test_native_task_experiment import Transport as AdvisoryTransport
    from ui_kobe.osworld.transitions import TransitionJournal, decision_tools
    agent = build(OfficialK3TaskViewsAgent, monkeypatch, tmp_path, [])
    actor, advisory = Transport([xml(), xml('wait', ''), xml('wait', '')]), AdvisoryTransport()
    class Combined:
        def create(self, **request):
            return advisory.create(**request) if request.get('response_format') else actor.create(**request)
        def close(self):
            pass
    agent.client.transport = agent.context_provider.transport = Combined()
    agent.execution_journal = log = TransitionJournal(tmp_path / 'journal', task_id='task', run_id='run', contract=agent.contract)
    try:
        for step in (1, 2):
            obs = {'screenshot': png()}
            log.begin('goal', obs, step=step)
            returned, commands = agent.predict('goal', obs)
            log.decide(returned, commands, step=step, tools=decision_tools(agent))
            log.result(commands[0], step=step, observation=obs)
            agent.record_execution(commands[0])
        modules = agent.context_provider.modules
        assert modules is not None and len(modules.recent) == 2
        assert not modules.gaps
        assert modules.active and len(modules.modules[modules.active]['outputs']) == 2
        assert agent.context_provider.view_trace['view_changes']['executor']['base_revision'] is not None
        context = actor.requests[-1]['messages'][-1]['content'][1]['text']
        assert 'recent_transitions' in context and 'mouse_move' in context
        previous = modules.previous_revision
        previous_views = modules.views
        def fail(_):
            raise OSError('optional projection unavailable')
        monkeypatch.setattr(agent.context_provider, 'build_views', fail)
        log.begin('goal', obs, step=3)
        agent.predict('goal', obs)
        assert modules.previous_revision == previous and modules.views is previous_views
        assert modules.new_events  # These records were not delivered as context.
    finally:
        agent.close()
