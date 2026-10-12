"""Real compiler/recording with mocked supplier and environment, no API or GUI."""
from copy import deepcopy
import json
import sys
import time
from types import SimpleNamespace

import pytest

from ui_kobe.osworld import telemetry
from ui_kobe.osworld.actor_context import ContextClient, protocol_feedback, repair_messages, supplement
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.kimi_native import KimiNativeAgent, native_schema, native_system
from ui_kobe.osworld.kimi_transition_native import KimiTransitionNativeAgent
from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
from test_cua_contract import build_agent, png
from test_native_task_experiment import Transport, response, launch_sandbox as launch_sandbox

ARMS = (KimiNativeAgent, KimiTransitionNativeAgent, KimiTaskViewsNativeAgent)


def test_taskviews_repair_preserves_full_rejected_candidate_and_tool_feedback_once():
    original = {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'literal goal'}]}]}
    observed = response({'content': 'Original model intent', 'tool_calls': [
        {'id': 'real-call-a', 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{}'}},
        {'id': 'real-call-b', 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{"action":"key"}'}}
    ]}, 'tool_calls').model_dump()
    error = 'Original validation evidence ' * 60
    before = deepcopy([original, observed])
    compact = repair_messages(original, observed, error, role='executor', compact_executor_feedback=True)
    legacy = repair_messages(original, observed, error, role='executor')
    assert [original, observed] == before
    assert compact['messages'][:-1] == legacy['messages'][:-1]
    assert compact['messages'][1] == observed['choices'][0]['message']
    for message, identity in zip(compact['messages'][2:4], ('real-call-a', 'real-call-b')):
        assert message['tool_call_id'] == identity and json.loads(message['content']) == {'error': error}
    assert error in legacy['messages'][-1]['content'][0]['text']
    assert error not in compact['messages'][-1]['content'][0]['text']


def test_taskviews_compact_repair_retains_current_packet_within_same_input_limit():
    from ui_kobe.osworld.native_history import context_size
    contract = CUAContract(context_max_text_chars=32000, taskviews_context_bytes=8000)
    original = {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'G' * 22900}]}]}
    observed = response({'content': 'literal rejected intent', 'tool_calls': [
        {'id': 'real-call', 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{}'}}
    ]}, 'tool_calls').model_dump()
    error = 'E' * 700
    legacy = repair_messages(original, observed, error, role='executor')
    compact = repair_messages(original, observed, error, role='executor', compact_executor_feedback=True)
    packet = 'P' * 7950
    assert supplement(legacy['messages'], packet, label='TaskViews', contract=contract) is legacy['messages']
    prepared = supplement(compact['messages'], packet, label='TaskViews', contract=contract)
    assert prepared is not compact['messages'] and context_size(prepared)[1] <= 32000
    assert prepared[-1]['content'][-1]['text'] == 'TaskViews\n' + packet
    assert prepared[:-1] == compact['messages'][:-1]


@pytest.mark.parametrize('role', ['executor', 'perception'])
def test_compact_repair_without_complete_tool_replies_keeps_the_only_error(role):
    original = {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'literal goal'}]}]}
    result = repair_messages(original, None, 'Original error must remain', role=role,
                             compact_executor_feedback=True)
    assert 'Original error must remain' in result['messages'][-1]['content'][0]['text']


@pytest.mark.parametrize('checkpoint', [False, True])
def test_unadmitted_feedback_pauses_checkpoint_taskviews_before_supplier(checkpoint):
    from ui_kobe.osworld.checkpoints import ReadAnomaly
    owner = SimpleNamespace(cached_context='P' * 200, context_label='TaskViews',
                            contract=CUAContract(taskviews_context_bytes=100), feedback_v10=True,
                            checkpoint_reads=checkpoint, context_delivered=lambda: None)
    wire = Transport()
    client = ContextClient(owner, wire)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'literal goal'}]}]
    if checkpoint:
        with pytest.raises(ReadAnomaly, match='before actor dispatch'):
            client.create(messages=messages)
        assert not wire.requests
    else:
        client.create(messages=messages)
        assert wire.requests[0]['messages'] == messages


def install_environment(monkeypatch, path, cls):
    """Exercise the actual passive wrappers and their raw controller returns."""
    class Controller:
        def execute_python_command(self, command):
            return {'returncode': 0, 'stdout': 'RAW_RECEIPT_ONLY', 'command': command}
    class Env:
        def step(self, action):
            Controller().execute_python_command(action)
            return {'screenshot': png((64, 48))}, 0, False, {'raw': 'RAW_INFO_ONLY'}
        def evaluate(self):
            return 0.2
        def close(self):
            return None
    import mm_agents.qwen
    monkeypatch.setattr(mm_agents.qwen, 'QwenAgent', cls)
    monkeypatch.setitem(sys.modules, 'desktop_env.desktop_env', SimpleNamespace(DesktopEnv=Env))
    monkeypatch.setitem(sys.modules, 'desktop_env.controllers.python', SimpleNamespace(PythonController=Controller))
    monkeypatch.setattr(telemetry, '_installed', False)
    monkeypatch.setattr(telemetry, '_root', path)
    monkeypatch.setattr(telemetry, 'install_api', lambda _: None)
    monkeypatch.setattr(cls, 'predict', cls.predict)  # Restore the real class after install wraps it.
    telemetry.install(path)
    return Env()


@pytest.mark.parametrize('cls', ARMS)
def test_raw_evidence_stays_complete_but_direct_feedback_is_minimal(monkeypatch, tmp_path, cls):
    env = install_environment(monkeypatch, tmp_path, cls)
    agent = build_agent(cls, monkeypatch, tmp_path)
    wire = Transport()
    agent.transport = agent.client.transport = wire
    if cls is KimiTaskViewsNativeAgent:
        monkeypatch.setattr(agent, 'build_views', lambda end: None)
    try:
        obs = {'screenshot': png((64, 48))}
        _, commands = agent.predict('Original literal task', obs)
        for command in commands:
            obs, *_ = env.step(command)
        agent.predict('Original literal task', obs)
        request = wire.requests[-1]
        feedback = [json.loads(m['content']) for m in request['messages'] if m['role'] == 'tool']
        assert feedback == [{'status': 'returned'}]
        assert request['messages'][1]['content'][1]['text'].endswith('Previous actions:\nNone')
        assert not any('Original literal task' in p.get('text', '') for p in request['messages'][-1]['content']
                       if not p.get('text', '').startswith('UI-KOBE execution memory'))
        assert env.evaluate() == 0.2
        if cls is KimiNativeAgent:
            assert agent.execution_journal is None
            assert not (tmp_path / 'transitions').exists()
            assert 'RAW_RECEIPT_ONLY' not in json.dumps(request['messages'])
            assert 'RAW_INFO_ONLY' not in json.dumps(request['messages'])
        else:
            graph = agent.execution_journal.export_ui_kobe()
            edge = graph['edges'][0]
            assert edge['source'] and edge['target'] and edge['instruction'] == 'Original literal task'
            assert edge['controller_receipts'][0]['result']['stdout'] == 'RAW_RECEIPT_ONLY'
            assert edge['info'] == {'raw': 'RAW_INFO_ONLY'}
            assert edge['effect_status'] == 'unknown' and edge['target_observation']
        if cls is KimiTransitionNativeAgent:
            assert len(wire.requests) == 2  # No perception/planner/verifier LLM.
            assert 'RAW_RECEIPT_ONLY' in request['messages'][-1]['content'][-1]['text']
            assert not hasattr(agent, 'control')
        records = [json.loads(line) for path in tmp_path.glob('events-*.jsonl') for line in path.read_text().splitlines()]
        assert any(r['event'] == 'controller_result' and r['result']['stdout'] == 'RAW_RECEIPT_ONLY' for r in records)
        assert any(r['event'] == 'action_result' and r['info'] == {'raw': 'RAW_INFO_ONLY'} for r in records)
        assert not any(r['event'] == 'transition_recording_warning' for r in records)
    finally:
        agent.close()


def test_three_native_arms_inherit_the_same_actor_entry():
    from scripts.run_official_native_tasks import agent_class
    for name, cls in zip(('baseline', 'ui_kobe_like', 'taskviews'), ARMS):
        assert agent_class('k3-native', name) is cls
        assert cls.predict is KimiNativeAgent.predict
        assert cls.generate_candidate is KimiNativeAgent.generate_candidate
    assert [cls.transition_recording for cls in ARMS] == [False, True, True]
    from mm_agents.qwen.main import QwenAgent
    for name in ('baseline', 'ui_kobe_like', 'taskviews'):
        cls = agent_class('official-xml', name)
        assert cls.predict is QwenAgent.predict


def test_all_three_actor_payloads_match_when_optional_context_is_unavailable(monkeypatch, tmp_path):
    payloads = []
    for cls in ARMS:
        agent = build_agent(cls, monkeypatch, tmp_path / cls.__name__)
        wire = agent.transport = agent.client.transport = Transport()
        if cls is KimiTaskViewsNativeAgent:
            monkeypatch.setattr(agent, 'build_views', lambda end: None)
        try:
            for _ in range(2):
                _, commands = agent.predict('literal goal', {'screenshot': png()})
                for command in commands:
                    agent.record_execution(command, receipts=[{'result': {'returncode': 0}}])
            payloads.append([{key: request[key] for key in ('model', 'messages', 'tools', 'tool_choice',
                'reasoning_effort', 'max_completion_tokens', 'generation_attempt')} for request in wire.requests])
        finally:
            agent.close()
    assert payloads[0] == payloads[1] == payloads[2]


@pytest.mark.parametrize('call', [None, {'id': ['invalid']}, {'id': '', 'type': 'function'},
    {'id': 'x', 'type': 'function', 'function': {'name': 'unknown', 'arguments': '{}'}}])
def test_malformed_candidates_never_create_orphan_tool_history(call):
    observed = response({'tool_calls': [call]}, 'tool_calls').model_dump()
    original = {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'original goal'}]}]}
    corrected = repair_messages(original, observed, 'invalid native identity', role='executor')
    assert corrected['messages'][:-1] == original['messages']
    assert not any(message['role'] in ('assistant', 'tool') for message in corrected['messages'])


def test_prompt_is_upstream_with_only_native_wire_instructions():
    from mm_agents.qwen.history import COLLAPSED_SCREENSHOT_TEXT
    from mm_agents.qwen.prompts import build_system_prompt
    frame = CUAContract().process(png(), 1)
    expected = build_system_prompt(native_schema(frame), collapsed_screenshot_text=COLLAPSED_SCREENSHOT_TEXT,
        task_current_date='2030-01-02', enable_batch_actions=True)
    start, end = expected.index('When using the tool,'), expected.index('Rules:\n')
    expected = expected[:start] + (
        'Use native computer_use function calls with JSON parameters.\n'
        'The action field must exactly match the declared enum, including underscores. '
        'Python/PyAutoGUI method names and other aliases are not action identifiers.\n\n'
    ) + expected[end:]
    expected = expected.replace('- Return each action as a separate complete <tool_call>...</tool_call> block; do not return an actions array.',
        '- Return each action as a separate complete native function call; do not return an actions array.')
    assert native_system(frame, '2030-01-02') == expected
    assert frame.metadata['original_sha256'] not in expected


def test_feedback_does_not_claim_effect_success_and_keeps_real_user_answer():
    assert json.loads(protocol_feedback([])) == {'status': 'unobserved'}
    raw = [{'action': 'pyautogui.click(1,2)', 'error': 'actual error', 'controller_receipts': ['RAW']}]
    assert json.loads(protocol_feedback(raw)) == {'error': 'actual error'}
    assert json.loads(protocol_feedback([], 'Actual user answer')) == {'user_response': 'Actual user answer'}
    assert raw[0]['controller_receipts'] == ['RAW']
    assert json.loads(protocol_feedback([{'controller_receipts': [
        {'result': {'returncode': 7, 'stdout': 'not model feedback'}}]}])) == {'returncode': 7}


def test_optional_context_cannot_replace_or_truncate_actor_input():
    contract = CUAContract(taskviews_context_bytes=100)
    messages = [{'role': 'system', 'content': 'original rules'}, {'role': 'user', 'content': [
        {'type': 'text', 'text': 'original task'}, {'type': 'image_url', 'image_url': {'url': 'original frame'}}]}]
    original = deepcopy(messages)
    assert supplement(messages, 'x' * 101, label='memory', contract=contract) is messages
    modified = supplement(messages, '{"grade":"model_proposal"}', label='memory', contract=contract)
    assert messages == original and modified[0] == messages[0]
    assert modified[-1]['content'][:-1] == messages[-1]['content']
    with pytest.raises(TypeError):
        supplement(messages, {'commands': ['DONE']}, label='memory', contract=contract)


def test_advisory_usage_cannot_spend_actor_budget_or_advance_actor_clock(monkeypatch, tmp_path):
    agent = build_agent(KimiTaskViewsNativeAgent, monkeypatch, tmp_path)
    clock = [100.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    def analysis(end):
        for index in range(4):
            agent.advisory_ledger.reserve(str(index), 'perception', 4000)
            agent.advisory_ledger.settle(str(index), None)
        clock[0] += 300
        return None
    monkeypatch.setattr(agent, 'build_views', analysis)
    wire = agent.transport = agent.client.transport = Transport()
    try:
        agent.predict('goal', {'screenshot': png()})
        actor = wire.requests[-1]
        assert actor['deadline'] == 400 + agent.budget.step_s
        assert actor['max_completion_tokens'] == 16000
        assert agent.step_ledger.charged_output == 0  # Mock supplier does not settle usage.
        assert agent.step_ledger.repair_counts == {'executor': 0, 'advisory': 0}
        assert agent.advisory_ledger.snapshot()['unknown_usage_requests'] == 4
        assert agent.step_ledger.deadline == actor['step_ledger'].deadline
        assert agent.advisory_ledger.deadline < actor['step_ledger'].deadline
    finally:
        agent.close()


def test_three_arm_plan_rejects_old_plans_and_invalid_arms_before_resources(launch_sandbox):
    from scripts import osworld_native_experiment as campaign
    root, checks, commands = launch_sandbox
    plan = campaign.load(root / 'plan.json')
    assert plan['arms'] == list(campaign.ARMS)
    assert len(set(plan['protocols'])) == 1
    campaign.write(root / 'plan.json', {**plan, 'implementation_version': 6})
    with pytest.raises(RuntimeError, match='v7'):
        campaign.launch(root, 'baseline')
    assert checks == [('source', root)] and not commands


def test_provider_is_not_an_actor_and_cannot_modify_tools(monkeypatch, tmp_path):
    agent = build_agent(KimiTransitionNativeAgent, monkeypatch, tmp_path)
    wire = Transport()
    client = ContextClient(agent, wire)
    agent.cached_context = '{"model_verified":true,"suggested_action":"terminate"}'
    messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': [{'type': 'text', 'text': 'goal'}]}]
    tools = [{'type': 'function', 'function': {'name': 'computer_use'}}]
    try:
        client.create(messages=messages, tools=tools, tool_choice='auto', max_completion_tokens=16000)
        assert wire.requests[0]['tools'] == tools and wire.requests[0]['tool_choice'] == 'auto'
        assert messages[-1]['content'] == [{'type': 'text', 'text': 'goal'}]
    finally:
        agent.close()


@pytest.mark.parametrize('context', ['x' * 32001, {'suggested_action': 'terminate'}])
def test_invalid_or_oversized_native_context_is_omitted_without_acknowledgment(monkeypatch, tmp_path, context):
    agent = build_agent(KimiTransitionNativeAgent, monkeypatch, tmp_path)
    wire = agent.transport = agent.client.transport = Transport()
    delivered = []
    monkeypatch.setattr(agent, 'optional_context', lambda instruction, obs: context)
    monkeypatch.setattr(agent, 'context_delivered', lambda: delivered.append(True))
    try:
        _, commands = agent.predict('literal goal', {'screenshot': png()})
        assert commands and not delivered
        assert not any(part.get('text', '').startswith(agent.context_label)
            for part in wire.requests[0]['messages'][-1]['content'])
    finally:
        agent.close()
