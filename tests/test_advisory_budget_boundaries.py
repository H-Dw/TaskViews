"""Simultaneous claims on the one analysis pool; no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time

import pytest

from ui_kobe.api.kimi_budget import ConcurrentAdvisoryLedger, StepTokenBudgetError
from ui_kobe.api.qwen_native import QwenGenerationProfile


def ledger():
    return ConcurrentAdvisoryLedger(QwenGenerationProfile(), time.monotonic() + 30,
                                   lambda *args, **kwargs: None)


def race(functions):
    barrier = Barrier(len(functions))
    def invoke(function):
        barrier.wait(timeout=5)
        try:
            return ('ok', function())
        except (StepTokenBudgetError, RuntimeError) as error:
            return ('error', type(error))
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(invoke, functions))


def test_only_one_job_can_reserve_the_last_advisory_cap():
    shared = ledger()
    for index in range(3):
        shared.reserve(str(index), 'planner', 4000)
        shared.settle(str(index), None)
    results = race([lambda: shared.reserve('left', 'planner', 4000),
                    lambda: shared.reserve('right', 'verifier', 4000)])
    assert sorted(kind for kind, _ in results) == ['error', 'ok']
    snapshot = shared.snapshot()
    assert snapshot['charged_output'] == 16000 and snapshot['requests'] == 4
    assert snapshot['unknown_usage_requests'] == 4
    with pytest.raises(StepTokenBudgetError):
        shared.allowance('planner')


def test_simultaneous_duplicate_request_identity_reserves_once():
    shared = ledger()
    results = race([lambda: shared.reserve('same', 'planner', 4000)] * 2)
    assert sorted(kind for kind, _ in results) == ['error', 'ok']
    assert shared.snapshot()['requests'] == 1 and shared.snapshot()['charged_output'] == 4000


def test_simultaneous_settlement_cannot_double_count_original_usage():
    shared = ledger()
    shared.reserve('same', 'planner', 4000)
    usage = {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}
    results = race([lambda: shared.settle('same', usage)] * 2)
    assert sorted(kind for kind, _ in results) == ['error', 'ok']
    snapshot = shared.snapshot()
    assert snapshot['known_usage'] == usage and snapshot['charged_output'] == 10
    assert snapshot['unknown_usage_requests'] == 0


def test_parallel_roles_share_two_repairs_without_spending_actor_repairs():
    shared = ledger()
    results = race([lambda: shared.regenerate('planner', 0),
                    lambda: shared.regenerate('verifier', 0),
                    lambda: shared.regenerate('perception', 0)])
    assert all(kind == 'ok' for kind, _ in results)
    assert sum(value is True for _, value in results) == 2
    assert shared.snapshot()['repair_counts'] == {'executor': 0, 'advisory': 2}
