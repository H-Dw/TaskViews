"""Per-step output admission; actual input/output usage is separately recorded."""
import time
from copy import deepcopy
from functools import wraps
from threading import RLock


def _locked(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return invoke


class StepTokenBudgetError(RuntimeError):
    code = 'step_output_budget_exhausted'


class StepLedger:
    def __init__(self, profile, deadline, emit, *, actor_repairs=None, advisory_repairs=None):
        self.profile, self.deadline, self.emit = profile, deadline, emit
        self.charged_output = self.regenerations = 0
        self.requests = {}
        self.repair_limits = {'executor': profile.semantic_regenerations if actor_repairs is None else actor_repairs,
                              'advisory': profile.semantic_regenerations if advisory_repairs is None else advisory_repairs}
        if any(type(n) is not int or not 0 <= n <= 2 for n in self.repair_limits.values()):
            raise ValueError('Repair pools must each be in 0..2')
        self.repair_counts = dict(executor=0, advisory=0)
        self.usage = dict(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    def allowance(self, role):
        remaining = self.profile.step_output_tokens - self.charged_output
        if role != 'executor':
            remaining -= self.profile.executor_reserve_tokens
        cap = self.profile.max_completion_tokens if role == 'executor' else self.profile.adviser_max_tokens
        if time.monotonic() >= self.deadline or remaining <= 0:
            raise StepTokenBudgetError('No output/time budget for ' + role)
        return min(cap, remaining)

    def reserve(self, request_id, role, tokens):
        if request_id in self.requests or not 0 < tokens <= self.allowance(role):
            raise StepTokenBudgetError('Request would exceed the shared step output budget')
        self.charged_output += tokens
        self.requests[request_id] = {'role': role, 'reserved_output': tokens, 'settled': False, 'usage': None}

    def settle(self, request_id, usage):
        record = self.requests[request_id]
        if record['settled']:
            raise RuntimeError('Request usage settled twice')
        record['settled'] = True
        valid = isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in self.usage)
        if valid:
            record['usage'] = dict(usage)
            self.charged_output += usage['completion_tokens'] - record['reserved_output']
            for key in self.usage:
                self.usage[key] += usage[key]
        # Without final usage, keep the entire reservation charged. It is an
        # admission estimate, not a fabricated provider measurement.
        self.emit('step_token_accounting', request_id=request_id, **self.snapshot())

    def regenerate(self, role, minimum_seconds):
        pool = 'executor' if role == 'executor' else 'advisory'
        if (self.repair_counts[pool] >= self.repair_limits[pool]
                or time.monotonic() + minimum_seconds >= self.deadline):
            return False
        try:
            self.allowance(role)
        except StepTokenBudgetError:
            return False
        self.regenerations += 1
        self.repair_counts[pool] += 1
        return True

    def snapshot(self):
        return {'output_limit': self.profile.step_output_tokens, 'charged_output': self.charged_output,
                'known_usage': dict(self.usage), 'unknown_usage_requests': sum(r['usage'] is None for r in self.requests.values()),
                'semantic_regenerations': self.regenerations, 'repair_counts': dict(self.repair_counts),
                'repair_limits': dict(self.repair_limits), 'requests': len(self.requests)}


class ConcurrentAdvisoryLedger(StepLedger):
    """Opt-in TaskViews locking; the common actor/baseline ledger is unchanged."""
    def __init__(self, *args, **kwargs):
        self._lock = RLock()
        super().__init__(*args, **kwargs)

    allowance = _locked(StepLedger.allowance)
    reserve = _locked(StepLedger.reserve)
    settle = _locked(StepLedger.settle)
    regenerate = _locked(StepLedger.regenerate)
    snapshot = _locked(StepLedger.snapshot)

    def __deepcopy__(self, memo):
        # Request capture may snapshot a ledger. Never copy/share its lock, or
        # let a recorder's independent snapshot spend the live admission pool.
        with self._lock:
            copied = type(self).__new__(type(self))
            memo[id(self)] = copied
            copied.__dict__ = {k: deepcopy(v, memo) for k, v in self.__dict__.items() if k != '_lock'}
            copied._lock = RLock()
            return copied
