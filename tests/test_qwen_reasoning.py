from copy import deepcopy
import json
import time

import httpx
import pytest

from scripts.taskviews_recovery import configure_qwen_reasoning
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.qwen_native import (MODEL, QwenGenerationProfile, QwenNativeClient, QwenTransportBudget,
                                     generation_profile, generation_request_fields, reasoning_migration_matches)
from ui_kobe.osworld.cua_contract import options_contract
from ui_kobe.osworld.qwen_native_base import QwenTransitionNativeAgent
from ui_kobe.osworld.taskviews_profiles import MINI_PROFILE, UI_KOBE_PROFILE
from ui_kobe.osworld.transitions import TransitionJournal
from test_mini_profiles import TASK, make_actor, manager, predict
from test_qwen_native_checkpoints import completed


@pytest.mark.parametrize('effort', ['low', 'medium', 'xhigh'])
def test_reasoning_wire_preserves_original_history_usage_and_budget(tmp_path, effort):
    profile = generation_profile(f'qwen-native-{effort}-16k')
    ledger = StepLedger(profile, time.monotonic() + 930, lambda *a, **k: None)
    history = [{'role': 'assistant', 'content': 'public answer', 'reasoning_content': 'original private field',
                'tool_calls': [{'id': 'original-id', 'type': 'function', 'function': {
                    'name': 'computer_use', 'arguments': '{"action":"key","keys":["enter"]}'}}]},
               {'role': 'tool', 'tool_call_id': 'original-id', 'content': 'original receipt'}]
    body = completed()
    body['choices'][0]['message']['reasoning_content'] = 'separate original response field'
    body['usage']['completion_tokens_details'] = {'reasoning_tokens': 8}
    payloads = []
    def handler(req):
        payloads.append(json.loads(req.content))
        return httpx.Response(200, json=body)
    client = QwenNativeClient(api_key='offline', budget=QwenTransportBudget(), profile=profile,
        emit=lambda *a, **k: None, response_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        result = client.create(model=MODEL, messages=history, tools=[], tool_choice='auto', max_tokens=16000,
                               deadline=ledger.deadline, step_ledger=ledger, budget_role='executor')
        assert result.model_dump() == body
        assert payloads[0]['messages'] == history
        assert payloads[0]['enable_thinking'] is True and payloads[0]['reasoning_effort'] == effort
        assert payloads[0]['preserve_thinking'] is True and 'thinking_budget' not in payloads[0]
        assert payloads[0]['max_tokens'] == 16000 and ledger.profile.step_output_tokens == 32000
        assert ledger.snapshot()['known_usage']['completion_tokens'] == 10
        assert profile.semantic_regenerations == 2 and client.budget.attempts == 6
    finally:
        client.close()


@pytest.mark.parametrize('field,value', [('reasoning_effort', 'high'), ('enable_thinking', False),
                                      ('thinking_budget', 262144), ('preserve_thinking', False)])
def test_conflicting_reasoning_fields_rejected_before_request(tmp_path, field, value):
    profile = generation_profile('qwen-native-xhigh-16k')
    ledger = StepLedger(profile, time.monotonic() + 930, lambda *a, **k: None)
    client = QwenNativeClient(api_key='offline', budget=QwenTransportBudget(), profile=profile,
        emit=lambda *a, **k: pytest.fail('No request permitted'), response_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('No API permitted'))))
    try:
        with pytest.raises(ValueError, match='frozen Qwen reasoning'):
            client.create(model=MODEL, max_tokens=16000, deadline=ledger.deadline, step_ledger=ledger,
                          budget_role='executor', **{field: value})
    finally:
        client.close()


def test_runner_options_and_legacy_disabled_profile_are_exact():
    assert generation_request_fields(QwenGenerationProfile()) == {'enable_thinking': False}
    profile = generation_profile('qwen-native-xhigh-16k')
    options_contract({'enable_thinking': True}, provider='qwen', generation_profile=profile)
    with pytest.raises(ValueError, match='enable_thinking'):
        options_contract({'enable_thinking': False}, provider='qwen', generation_profile=profile)
    with pytest.raises(ValueError, match='bounds'):
        generation_request_fields(QwenGenerationProfile(max_completion_tokens=32000))
    with pytest.raises(ValueError):
        generation_profile('qwen-native-high-16k')


def migration_inputs():
    before = QwenGenerationProfile().__dict__
    manifest = {'agent_interface': 'qwen-native', 'taskviews_profile': MINI_PROFILE, 'arm': 'ui_kobe_like',
                'generation_profile': deepcopy(before), 'official_arguments': ['--no-enable_thinking', '--no-stream']}
    plan = {'agent_interface': 'qwen-native', 'generation_profile': deepcopy(before),
            'provider_request': {'enable_thinking': False, 'temperature': 0, 'top_p': 0.9}}
    saved = {'tag': 'original-tag', 'checkpoint_actor_profile': UI_KOBE_PROFILE, 'generation_profile': before}
    return plan, manifest, saved


def test_explicit_migration_preserves_budgets_and_rejects_foreign_boundary():
    plan, manifest, saved = migration_inputs()
    original = deepcopy(saved)
    configure_qwen_reasoning(plan, manifest, saved, 'xhigh')
    assert saved == original
    after = manifest['generation_profile']
    assert {k: v for k, v in after.items() if k not in ('name', 'reasoning_effort')} == {
        k: v for k, v in original['generation_profile'].items() if k not in ('name', 'reasoning_effort')}
    assert manifest['official_arguments'] == ['--enable_thinking', '--no-stream']
    assert plan['provider_request']['reasoning_effort'] == 'xhigh'
    migration = manifest['qwen_reasoning_migration']
    assert reasoning_migration_matches(migration, tag=saved['tag'], before=saved['generation_profile'], after=after)
    assert not reasoning_migration_matches(migration, tag='another-tag', before=saved['generation_profile'], after=after)
    assert not reasoning_migration_matches(migration, tag=saved['tag'], before=saved['generation_profile'],
                                          after={**after, 'step_output_tokens': 64000})
    plan, manifest, saved = migration_inputs()
    saved['generation_profile'] = generation_profile('qwen-native-low-16k').__dict__
    with pytest.raises(ValueError, match='exact current'):
        configure_qwen_reasoning(plan, manifest, saved, 'xhigh')


def test_real_checkpoint_restores_ids_history_without_replay_only_with_exact_migration(tmp_path, monkeypatch):
    actor, obs, _ = make_actor(monkeypatch, tmp_path / 'first', cls=QwenTransitionNativeAgent)
    actor.execution_journal = TransitionJournal(tmp_path / 'journal', task_id='059',
                                               run_id='offline-reasoning', contract=actor.contract)
    predict(actor, obs)
    cp = manager(tmp_path, 'ui_kobe_like')
    tag = cp.save(actor, TASK, obs)
    before = deepcopy(actor.turns)
    pending = deepcopy(actor.pending)
    _, saved = cp.read(tag, metadata_only=True)
    restored, _, _ = make_actor(monkeypatch, tmp_path / 'second', cls=QwenTransitionNativeAgent)
    restored.profile = generation_profile('qwen-native-xhigh-16k')
    with pytest.raises(ValueError, match='contract changed'):
        cp.restore_agent(restored)
    cp.manifest.update(agent_interface='qwen-native', qwen_reasoning_migration={
        'version': 'qwen-reasoning-migration-v1', 'checkpoint': tag,
        'before': saved['generation_profile'], 'after': restored.profile.__dict__})
    cp.restore_agent(restored)
    assert restored.turns == before and restored.pending == pending and restored.total_steps == 1
    assert restored.profile.reasoning_effort == 'xhigh'
    assert cp.read(tag, metadata_only=True)[1]['generation_profile'] == saved['generation_profile']
    actor.close()
    restored.close()
