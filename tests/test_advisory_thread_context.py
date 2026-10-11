"""Real telemetry context tests; no model, controller, or VM calls."""
import json
import os
from threading import Barrier, local

import pytest

from ui_kobe.osworld import telemetry
from ui_kobe.osworld.advisory_concurrency import AdvisoryJob, run_advisory_jobs


@pytest.fixture
def telemetry_records(tmp_path, monkeypatch):
    # Preserve the suite's original thread-local object, including absent keys.
    # Only tiny diagnostic events are written through the real emit function.
    monkeypatch.setattr(telemetry, '_context', local())
    monkeypatch.setattr(telemetry, '_root', tmp_path)
    path = tmp_path / f'events-{os.getpid()}.jsonl'

    def read():
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    return read


@pytest.mark.parametrize('concurrency', [1, 2])
def test_readonly_jobs_inherit_actual_parent_step_and_phase(telemetry_records, concurrency):
    telemetry.set_context(42, 'agent')
    telemetry.emit('parent_before')
    rendezvous = Barrier(2) if concurrency == 2 else None

    def read(role):
        if rendezvous is not None:
            rendezvous.wait(timeout=5)
        telemetry.emit('readonly_probe', budget_role=role)
        return role

    jobs = [AdvisoryJob(role, 'same-frame', 7, object(), lambda r=role: read(r))
            for role in ('planner', 'verifier')]
    assert run_advisory_jobs(jobs, concurrency=concurrency) == {
        'planner': 'planner', 'verifier': 'verifier'}
    telemetry.emit('parent_after')
    records = telemetry_records()
    probes = [record for record in records if record['event'] == 'readonly_probe']
    assert {record['budget_role'] for record in probes} == {'planner', 'verifier'}
    assert all((record['step'], record['phase']) == (42, 'agent') for record in records)
    assert records[0]['event'] == 'parent_before'
    assert records[-1]['event'] == 'parent_after'


@pytest.mark.parametrize('failed_role', ['planner', 'verifier'])
def test_failed_job_keeps_each_roles_context_and_parent_unmodified(telemetry_records, failed_role):
    telemetry.set_context(81, 'agent')
    telemetry.emit('parent_before')
    rendezvous = Barrier(2)

    class ExpectedReadFailure(RuntimeError):
        pass

    def read(role):
        rendezvous.wait(timeout=5)
        telemetry.emit('readonly_probe', budget_role=role)
        if role == failed_role:
            raise ExpectedReadFailure('bounded read failed: ' + role)
        return role

    jobs = [AdvisoryJob(role, 'same-frame', 11, object(), lambda r=role: read(r))
            for role in ('planner', 'verifier')]
    with pytest.raises(ExpectedReadFailure, match=failed_role):
        run_advisory_jobs(jobs, concurrency=2)
    telemetry.emit('parent_after_failure')
    records = telemetry_records()
    probes = [record for record in records if record['event'] == 'readonly_probe']
    assert len(probes) == 2
    assert {record['budget_role'] for record in probes} == {'planner', 'verifier'}
    assert all((record['step'], record['phase']) == (81, 'agent') for record in records)
    assert records[0]['event'] == 'parent_before'
    assert records[-1]['event'] == 'parent_after_failure'


def test_nested_failure_restores_existing_and_absent_keys_without_copying_actor(monkeypatch):
    monkeypatch.setattr(telemetry, '_context', local())
    telemetry._context.step = 3
    actor, receipts = object(), []
    telemetry._context.agent = actor
    telemetry._context.receipts = receipts
    assert telemetry.capture_context() == (3, 'harness')

    with pytest.raises(RuntimeError, match='inner read failed'):
        with telemetry.audit_context((42, 'agent')):
            assert telemetry.capture_context() == (42, 'agent')
            with telemetry.audit_context((81, 'readonly')):
                assert telemetry.capture_context() == (81, 'readonly')
                raise RuntimeError('inner read failed')

    assert telemetry._context.step == 3
    assert not hasattr(telemetry._context, 'phase')
    assert telemetry._context.agent is actor and telemetry._context.receipts is receipts
