"""Two independent read-only API jobs over one immutable frame/revision.

Caller commits results in its original order after BOTH jobs complete. Executor
and GUI operations are not accepted, and every job needs its own transport.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from . import telemetry


@dataclass(frozen=True)
class AdvisoryJob:
    role: str
    frame_id: str
    revision: int
    transport: object
    call: object


def run_advisory_jobs(jobs, *, concurrency=1):
    jobs = tuple(jobs)
    if concurrency not in (1, 2) or not 1 <= len(jobs) <= 2:
        raise ValueError('Advisory concurrency is bounded at two')
    if (any(job.role not in {'planner', 'verifier'} for job in jobs)
            or len({job.role for job in jobs}) != len(jobs)
            or len({(job.frame_id, job.revision) for job in jobs}) != 1
            or len({id(job.transport) for job in jobs}) != len(jobs)):
        raise ValueError('Independent advisory jobs require one frame/revision and isolated transports')
    if concurrency == 1 or len(jobs) == 1:
        return {job.role: job.call() for job in jobs}
    context = telemetry.capture_context()
    def invoke(job):
        with telemetry.audit_context(context):
            return job.call()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='taskviews-advisory') as pool:
        pending = [pool.submit(invoke, job) for job in jobs]
        # Preserve role order and propagate failures before graph/module commit.
        return {job.role: future.result() for job, future in zip(jobs, pending)}
