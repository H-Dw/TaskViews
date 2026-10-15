"""Audited Qwen native completions; HTTP 200 error envelopes are failures.

Legacy profiles remain non-streaming; the explicit SSE profile preserves real
frames, DONE, usage and tool identity. Every attempt settles its own ledger.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import time
import uuid

import httpx

from .kimi_stream import (Completion, OutputTokenLimitError, ProviderQuotaBlocked,
                          RateLimitDeferred, StreamBudget, StreamProtocolError, retry_after_seconds, safe_error_body)
from .qwen_connection import ConnectionTrace, QwenConnectionUnavailable, exception_chain

BASE_URL = 'https://pjfdspqowq.a.pinggy.link'
MODEL = 'qwen3.8-max'
PROTOCOL = 'qwen3.8-max-native-tools-official-cua-checkpoints-v9'


@dataclass(frozen=True)
class QwenTransportBudget(StreamBudget):
    """More network attempts within the existing time/output admission bounds."""
    attempts: int = 6
    connect_reset_limit: int = 3

    def __post_init__(self):
        if type(self.attempts) is not int or not 1 <= self.attempts <= 6:
            raise ValueError('Qwen supports at most six transport attempts')
        if type(self.connect_reset_limit) is not int or not 0 <= self.connect_reset_limit <= 6:
            raise ValueError('Qwen connection reset limit must be 0..6')
        StreamBudget(**{**{k: v for k, v in self.__dict__.items() if k != 'connect_reset_limit'},
                        'attempts': min(2, self.attempts)})


def transport_policy(budget=None):
    budget = budget or QwenTransportBudget()
    return {'version': 'qwen-phase-aware-retry-v2', 'budget': budget.__dict__,
            'backoff': 'exponential 3s, capped at 60s; 429 respects Retry-After >=60s',
            'idle_connection_reuse': False, 'unknown_usage': 'NULL; reservation remains charged',
            'output_admission': 'first original cap; retry shares remaining role output across remaining attempts',
            'connection_reset_circuit': {'consecutive_limit': budget.connect_reset_limit,
                'requires': 'ConnectError reset plus trace-confirmed failure before origin HTTP dispatch',
                'state': 'per original create call; no automatic recovery probe or route change'},
            'phase_trace': 'bounded credential-free TCP/TLS/upload/headers/body trace and original exception chain'}


@dataclass(frozen=True)
class QwenGenerationProfile:
    name: str = 'qwen-native-16k'
    reasoning_effort: str = 'disabled'
    max_completion_tokens: int = 16000
    step_output_tokens: int = 32000
    executor_reserve_tokens: int = 16000
    adviser_max_tokens: int = 4000
    semantic_regenerations: int = 2


def generation_profile(name='qwen-native-16k'):
    """Explicit reasoning selection; all existing output/repair bounds stay fixed."""
    if name == 'qwen-native-16k':
        return QwenGenerationProfile()
    for effort in ('low', 'high', 'xhigh'):
        if name == f'qwen-sse-{effort}-total16k':
            return QwenGenerationProfile(name=name, reasoning_effort=effort)
    for effort in ('low', 'medium', 'xhigh'):
        if name == f'qwen-native-{effort}-16k':
            return QwenGenerationProfile(name=name, reasoning_effort=effort)
    raise ValueError('Unknown frozen Qwen generation profile')


def request_policy(profile):
    streaming = profile.name in ('qwen-sse-low-total16k', 'qwen-sse-high-total16k', 'qwen-sse-xhigh-total16k')
    return {'version': 'qwen-request-policy-v1', 'stream': streaming,
            'output_field': 'max_completion_tokens' if streaming else 'max_tokens',
            'include_usage': streaming, 'trust_env': not streaming}


def streaming_migration_matches(migration, *, tag, before, after):
    if migration != {'version': 'qwen-streaming-migration-v1', 'checkpoint': tag, 'before': before, 'after': after}:
        return False
    return (before == generation_profile('qwen-native-xhigh-16k').__dict__
            and after == generation_profile('qwen-sse-xhigh-total16k').__dict__)


def generation_request_fields(profile):
    if profile.__dict__ != generation_profile(profile.name).__dict__:
        raise ValueError('Qwen generation profile changed its frozen bounds')
    fields = {'enable_thinking': profile.reasoning_effort != 'disabled'}
    if fields['enable_thinking']:
        fields.update(reasoning_effort=profile.reasoning_effort, preserve_thinking=True)
    return fields


def reasoning_migration_matches(migration, *, tag, before, after):
    """Permit only the declared checkpoint's exact generation-only migration."""
    if not isinstance(migration, dict) or migration != {
            'version': 'qwen-reasoning-migration-v1', 'checkpoint': tag,
            'before': before, 'after': after}:
        return False
    try:
        return (before == generation_profile(before['name']).__dict__
                and after == generation_profile(after['name']).__dict__
                and before != after)
    except (KeyError, TypeError, ValueError):
        return False


class GatewayRequestError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Qwen gateway error: ' + str(code))


def provider_error(body):
    """Decode the gateway's nested error JSON without confusing HTTP with success."""
    if not isinstance(body, dict):
        return 'invalid_response'
    error = body.get('error')
    message = body.get('message')
    if isinstance(message, str):
        try:
            nested = json.loads(message)
        except ValueError:
            nested = {}
        if isinstance(nested, dict) and nested.get('error'):
            error = nested['error']
    if body.get('choices') and not error and body.get('success') is not False:
        return None
    return (error.get('code') or error.get('type') or 'gateway_error') if isinstance(error, dict) else 'gateway_error'


class QwenNativeClient:
    # Provider hooks keep the audited transport shared without changing module
    # globals or sending one provider's credential/extension fields to another.
    api_key_env = 'QWEN_API_KEY'
    base_url = BASE_URL
    model_name = MODEL
    request_prefix = 'qwens-'
    policy_for = staticmethod(request_policy)
    fields_for = staticmethod(generation_request_fields)

    def accumulator(self):
        from .qwen_sse import QwenSSE
        return QwenSSE(self.model_name)

    def __init__(self, *, api_key=None, budget, profile, emit, response_dir, client=None, sleep=time.sleep):
        self.key = api_key or os.environ.get(self.api_key_env)
        if not self.key:
            raise ValueError(self.api_key_env + ' is missing')
        self.budget, self.profile, self.emit = budget, profile, emit
        self.request_policy = self.policy_for(profile)
        self.response_dir = Path(response_dir)
        self.response_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(headers={'Authorization': 'Bearer ' + self.key}, follow_redirects=False,
                                             trust_env=self.request_policy['trust_env'],
                                             limits=httpx.Limits(max_keepalive_connections=0))
        self.sleep = sleep
        self.last_timing, self.last_request_id = {}, None

    def create(self, *, deadline, step_ledger, budget_role, generation_attempt=1, parent_request_id=None, **payload):
        cap_field = self.request_policy['output_field']
        streaming = self.request_policy['stream']
        other_cap = 'max_tokens' if cap_field == 'max_completion_tokens' else 'max_completion_tokens'
        if payload.get('model') != self.model_name or other_cap in payload:
            raise ValueError('Qwen requires its exact model and Qwen generation fields')
        payload = deepcopy(payload)
        fields = self.fields_for(self.profile)
        for key in ('enable_thinking', 'reasoning_effort', 'preserve_thinking', 'thinking_budget',
                    'separate_reasoning', 'reasoning', 'provider'):
            if key in payload and (key not in fields or payload[key] != fields[key]):
                raise ValueError('Request differs from frozen Qwen reasoning fields: ' + key)
        payload.update(temperature=0, top_p=0.9, stream=streaming, **fields)
        if streaming:
            payload['stream_options'] = {'include_usage': True}
        requested_cap = payload[cap_field]
        if type(requested_cap) is not int or not 0 < requested_cap <= step_ledger.allowance(budget_role):
            raise ValueError('Request exceeds its declared role output admission')
        overall = min(deadline, time.monotonic() + self.budget.total_s)
        pre_http_resets = 0
        for attempt in range(1, self.budget.attempts + 1):
            remaining = min(overall - time.monotonic(), self.budget.generation_s)
            if remaining <= self.budget.connect_s:
                raise TimeoutError('Qwen role deadline has insufficient request time')
            cap = requested_cap
            if attempt > 1:
                available = step_ledger.profile.step_output_tokens - step_ledger.charged_output
                if budget_role != 'executor':
                    available -= step_ledger.profile.executor_reserve_tokens
                cap = min(requested_cap, step_ledger.allowance(budget_role),
                          available // (self.budget.attempts - attempt + 1))
            if cap <= 0:
                raise ValueError('Insufficient output admission for remaining Qwen transport attempts')
            payload[cap_field] = cap
            rid = self.last_request_id = self.request_prefix + uuid.uuid4().hex
            step_ledger.reserve(rid, budget_role, cap)
            self.emit('api_request', request_id=rid, endpoint=self.base_url, attempt=attempt,
                generation_attempt=generation_attempt, parent_request_id=parent_request_id,
                budget_role=budget_role, payload=payload)
            started = time.monotonic()
            trace = ConnectionTrace(self.key, started)
            self.last_timing = {'stream': streaming, 'first_sse_s': None, 'stream_done_s': None}
            usage, body, error, response_path, raw_sha, status = None, None, None, None, None, None
            sse_path = None
            accumulator = None
            raw = bytearray()
            retry_delay = None
            try:
                timeout = httpx.Timeout(min(self.budget.idle_s, remaining), connect=min(self.budget.connect_s, remaining),
                                        write=min(30, remaining), pool=min(self.budget.connect_s, remaining))
                if streaming:
                    from .qwen_sse import response_events
                    accumulator = self.accumulator()
                    response = None
                    is_sse = False
                    last_chunk = None
                    for kind, value in response_events(self.client, self.base_url + '/chat/completions', payload,
                                                       timeout, min(overall, started + self.budget.generation_s), trace=trace):
                        elapsed = round(time.monotonic() - started, 4)
                        if kind == 'headers':
                            response = value
                            status = response.status_code
                            self.last_timing['headers_s'] = elapsed
                            is_sse = status == 200 and response.headers.get('content-type', '').split(';')[0] == 'text/event-stream'
                            self.emit('http_response', request_id=rid, status_code=status, duration_s=elapsed,
                                      headers={k: response.headers[k] for k in ('content-type', 'x-request-id', 'retry-after') if k in response.headers})
                            continue
                        if len(raw) + len(value) > 8 * 1024**2:
                            raise ValueError('Provider response exceeds bounded audit size')
                        raw.extend(value)
                        self.last_timing.setdefault('first_chunk_s', elapsed)
                        self.last_timing['chunks'] = self.last_timing.get('chunks', 0) + 1
                        if last_chunk is not None:
                            self.last_timing['max_chunk_gap_s'] = max(self.last_timing.get('max_chunk_gap_s', 0), elapsed-last_chunk)
                        last_chunk = elapsed
                        if is_sse:
                            accumulator.feed(value)
                            usage = accumulator.usage
                            if accumulator.events and self.last_timing['first_sse_s'] is None:
                                self.last_timing['first_sse_s'] = elapsed
                            if accumulator.done and self.last_timing['stream_done_s'] is None:
                                self.last_timing['stream_done_s'] = elapsed
                    raw_sha = hashlib.sha256(raw).hexdigest()
                    sse_path = self.response_dir / (rid + ('.sse' if is_sse and not accumulator.error and accumulator.done else '.redacted.sse'))
                    if is_sse and not accumulator.error and accumulator.done:
                        with sse_path.open('xb') as saved:
                            saved.write(raw)
                    else:
                        redacted = raw.decode('utf-8', errors='replace').replace(self.key, '[REDACTED]')
                        redacted = re.sub(r'\b(?:ak-|sk-|org-)[A-Za-z0-9_-]+', '[REDACTED-ID]', redacted)
                        with sse_path.open('x', encoding='utf-8') as saved:
                            saved.write(redacted)
                    if not is_sse or accumulator.provider_failure:
                        try:
                            error_body = accumulator.provider_failure or json.loads(raw)
                        except (ValueError, UnicodeError):
                            error_body = None
                        code = provider_error(error_body)
                        self.emit('http_error_body', request_id=rid, status=status,
                                  body=safe_error_body(str(error_body) if error_body else raw.decode('utf-8', errors='replace'), self.key),
                                  original_response_sha256=raw_sha)
                        if status == 402 or code in ('exceeded_current_quota_error', 'insufficient_quota', 'insufficient_balance'):
                            raise ProviderQuotaBlocked('Qwen provider billing/quota blocked', request=response.request, response=response)
                        if status == 429:
                            retry_delay = max(60, retry_after_seconds(response.headers.get('retry-after')) or 60)
                            raise RateLimitDeferred('Qwen rate limit', request=response.request, response=response)
                        if status != 200:
                            response.raise_for_status()
                        raise GatewayRequestError(code or 'expected_sse')
                    accumulator.feed(b'', final=True)
                    body = accumulator.observed()
                    response_path = self.response_dir / (rid + '.json')
                    with response_path.open('x', encoding='utf-8') as saved:
                        json.dump(body, saved, ensure_ascii=False)
                    body = accumulator.complete()
                    if usage is not None and usage['completion_tokens'] > cap:
                        raise OutputTokenLimitError(body)
                    self.last_timing['transport'] = trace.snapshot()
                    self.emit('api_response', request_id=rid, response=body, timings=self.last_timing,
                              raw_response_sha256=raw_sha, raw_sse_path=str(sse_path), raw_response_path=str(response_path),
                              canonical_response_sha256=hashlib.sha256(response_path.read_bytes()).hexdigest())
                    return Completion(body)
                with self.client.stream('POST', self.base_url + '/chat/completions', json=payload,
                                        timeout=timeout, extensions={'trace': trace}) as response:
                    status = response.status_code
                    self.last_timing = {'headers_s': round(time.monotonic() - started, 4), 'stream': False,
                                        'first_sse_s': None, 'stream_done_s': None}
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= min(overall, started + self.budget.generation_s):
                            raise TimeoutError('Qwen complete-generation deadline reached')
                        if len(raw) + len(chunk) > 8 * 1024**2:
                            raise ValueError('Provider response exceeds bounded audit size')
                        raw.extend(chunk)
                    raw_sha = hashlib.sha256(raw).hexdigest()
                    try:
                        body = json.loads(raw)
                    except (ValueError, UnicodeError):
                        body = None
                    code = provider_error(body)
                    successful_body = status == 200 and code is None
                    response_path = self.response_dir / (rid + '.json')
                    text = raw.decode('utf-8', errors='replace')
                    # Successful complete responses remain byte-exact. Provider
                    # errors may echo credentials; retain original digest plus
                    # explicitly redacted bytes rather than copy a secret.
                    with response_path.open('x', encoding='utf-8') as saved:
                        saved.write(text if successful_body else safe_error_body(text, self.key))
                    if not successful_body:
                        self.emit('http_error_body', request_id=rid, status=status,
                            body=safe_error_body(text, self.key), original_response_sha256=raw_sha,
                            headers={k: response.headers[k] for k in ['retry-after', 'content-type', 'x-request-id'] if k in response.headers})
                        if status == 402 or code in ['exceeded_current_quota_error', 'insufficient_quota', 'insufficient_balance']:
                            raise ProviderQuotaBlocked('Qwen provider billing/quota blocked', request=response.request, response=response)
                        if status == 429:
                            delay = retry_after_seconds(response.headers.get('retry-after'))
                            retry_delay = max(60, delay if delay is not None else 60)
                            raise RateLimitDeferred('Qwen rate limit; bounded Retry-After', request=response.request, response=response)
                        if status != 200:
                            response.raise_for_status()
                        raise GatewayRequestError(code)
                    supplied = body.get('usage')
                    if isinstance(supplied, dict) and all(type(supplied.get(k)) is int and supplied[k] >= 0
                            for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']):
                        usage = supplied
                    choice = body['choices'][0]
                    if choice.get('finish_reason') == 'length':
                        raise OutputTokenLimitError(body)
                    if (choice.get('finish_reason') not in ['stop', 'tool_calls']
                            or not isinstance(choice.get('message'), dict)):
                        raise StreamProtocolError('Incomplete Qwen completion', code='invalid_finish', observed_response=body, retryable=True)
                    self.last_timing['transport'] = trace.snapshot()
                    self.emit('api_response', request_id=rid, response=body, timings=self.last_timing,
                              raw_response_sha256=raw_sha, raw_response_path=str(response_path))
                    return Completion(body)
            except Exception as failure:
                error = failure
                failure.request_id = rid
                if streaming and accumulator is not None:
                    usage = accumulator.usage
                    body = accumulator.observed()
                    if isinstance(failure, StreamProtocolError):
                        failure.observed_response = body
                    if raw and sse_path is None:
                        raw_sha = hashlib.sha256(raw).hexdigest()
                        sse_path = self.response_dir / (rid + '.partial-redacted.sse')
                        redacted = raw.decode('utf-8', errors='replace').replace(self.key, '[REDACTED]')
                        with sse_path.open('x', encoding='utf-8') as saved:
                            saved.write(re.sub(r'\b(?:ak-|sk-|org-)[A-Za-z0-9_-]+', '[REDACTED-ID]', redacted))
                if raw and response_path is None:
                    raw_sha = hashlib.sha256(raw).hexdigest()
                    response_path = self.response_dir / (rid + '.partial-redacted.txt')
                    with response_path.open('x', encoding='utf-8') as saved:
                        saved.write(safe_error_body(raw.decode('utf-8', errors='replace'), self.key))
                self.emit('api_error', request_id=rid, error_type=type(failure).__name__,
                          error=safe_error_body(str(failure), self.key), error_code=getattr(failure, 'code', None),
                          status_code=status, observed_response=body if usage is not None else None,
                          error_causes=exception_chain(failure, self.key), transport=trace.snapshot())
                pre_http_resets = pre_http_resets + 1 if trace.confirmed_pre_http_reset(failure) else 0
                reset_limit = getattr(self.budget, 'connect_reset_limit', 3)
                if reset_limit and pre_http_resets >= reset_limit:
                    phase = trace.snapshot()['failure_phase']
                    self.emit('connection_circuit_open', request_id=rid, consecutive_resets=pre_http_resets,
                              failure_phase=phase, automatic_recovery_probe=False)
                    unavailable = QwenConnectionUnavailable(pre_http_resets, phase)
                    unavailable.request_id = rid
                    raise unavailable from failure
                # A reused gateway connection can close before headers, or
                # during its body. No candidate is returned or executed until
                # the complete response passes validation. Keep this retry in
                # the same attempt/time/output bounds and settle unknown usage.
                transport_retry = isinstance(failure, (httpx.NetworkError, httpx.TimeoutException,
                                                        httpx.RemoteProtocolError))
                if streaming and isinstance(failure, StreamProtocolError) and failure.code == 'missing_done':
                    transport_retry = True
                if isinstance(failure, httpx.HTTPStatusError) and not isinstance(failure, ProviderQuotaBlocked):
                    transport_retry = status == 429 or status in [502, 503, 504]
                delay = retry_delay if retry_delay is not None else min(60, 3 * 2**(attempt - 1))
                if not transport_retry or attempt >= self.budget.attempts or time.monotonic() + delay + self.budget.connect_s >= overall:
                    raise
            finally:
                self.last_timing['complete_s'] = round(time.monotonic() - started, 4)
                transport = trace.snapshot()
                transport['exception_chain'] = exception_chain(error, self.key) if error else []
                trace_path = self.response_dir / (rid + '.transport.json')
                archive_error = None
                try:
                    with trace_path.open('x', encoding='utf-8') as saved:
                        json.dump(transport, saved, ensure_ascii=False, indent=2)
                        saved.write('\n')
                except Exception as failure:
                    archive_error = failure
                    self.emit('transport_trace_archive_error', request_id=rid,
                              error_type=type(failure).__name__, error=safe_error_body(str(failure), self.key))
                self.last_timing['transport'] = transport
                step_ledger.settle(rid, usage)
                self.emit('request_outcome', request_id=rid, attempt=attempt, generation_attempt=generation_attempt,
                    parent_request_id=parent_request_id, outcome='error' if error else 'complete',
                    usage=usage, observed_response=body if usage is not None else None, stream=streaming,
                    stream_done=accumulator.done if accumulator is not None else False,
                    raw_sse_path=str(sse_path) if sse_path else None, raw_response_path=str(response_path) if response_path else None,
                    raw_response_sha256=raw_sha, duration_s=self.last_timing['complete_s'], executable=False,
                    transport=transport, transport_trace_path=str(trace_path) if archive_error is None else None,
                    transport_trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest() if archive_error is None else None)
                if archive_error is not None:
                    raise archive_error from error
            self.emit('transport_retry', request_id=rid, next_attempt=attempt + 1, sleep_s=delay)
            self.sleep(delay)
        raise RuntimeError('Qwen transport attempts exhausted')

    def close(self):
        self.client.close()
