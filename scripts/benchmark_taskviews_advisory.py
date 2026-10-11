"""Latency sanity check for independent MOCK API jobs, not Qwen service speed."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def benchmark_mock(concurrency, delay=0.08):
    import httpx
    from ui_kobe.api.kimi_budget import ConcurrentAdvisoryLedger
    from ui_kobe.api.kimi_stream import StreamBudget
    from ui_kobe.api.qwen_native import QwenGenerationProfile, QwenNativeClient, MODEL
    from ui_kobe.osworld.advisory_concurrency import AdvisoryJob, run_advisory_jobs
    import tempfile
    profile, events = QwenGenerationProfile(), []
    deadline = time.monotonic() + 30
    ledger = ConcurrentAdvisoryLedger(profile, deadline, lambda event, **fields: events.append((event, fields)))
    def handler(request):
        time.sleep(delay)
        return httpx.Response(200, json={'id': 'mock', 'model': MODEL, 'choices': [
            {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}})
    clients = []
    with tempfile.TemporaryDirectory(prefix='taskviews-concurrency-') as directory:
        try:
            for role in ('planner', 'verifier'):
                clients.append(QwenNativeClient(api_key='offline-mock-key', budget=StreamBudget(),
                    profile=profile, emit=lambda event, **fields: events.append((event, fields)),
                    response_dir=Path(directory) / role,
                    client=httpx.Client(transport=httpx.MockTransport(handler))))
            def call(client, role):
                return client.create(deadline=deadline, step_ledger=ledger, budget_role=role,
                    model=MODEL, max_tokens=4000, messages=[{'role': 'user', 'content': 'Immutable mock frame'}]).model_dump()
            jobs = [AdvisoryJob(role, 'same-frame', 1, client,
                               lambda c=client, r=role: call(c, r))
                    for client, role in zip(clients, ('planner', 'verifier'))]
            started = time.monotonic()
            results = run_advisory_jobs(jobs, concurrency=concurrency)
            elapsed = time.monotonic() - started
            outcomes = [fields for event, fields in events if event == 'request_outcome']
            assert len(outcomes) == len({r['request_id'] for r in outcomes}) == 2
            assert list(results) == ['planner', 'verifier']
            return {'concurrency': concurrency, 'seconds': round(elapsed, 4),
                    'requests': len(outcomes), 'ledger': ledger.snapshot(), 'mock_only': True}
        finally:
            for client in clients:
                client.close()


def main():
    from scripts.osworld_native_experiment import require_scope
    require_scope(128 * 1024**2)
    values = [benchmark_mock(1), benchmark_mock(2)]
    print(json.dumps({'test_kind': 'MOCK latency only', 'runs': values,
                      'speedup': round(values[0]['seconds'] / values[1]['seconds'], 2)}))


if __name__ == '__main__':
    main()
