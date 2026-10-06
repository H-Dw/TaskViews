"""Bounded K3 SSE transport; complete messages, never partial actions, escape it."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid

import httpx

from .kimi import BASE_URL, K3Requests


class StreamProtocolError(ValueError):
    def __init__(self, message, *, code='protocol_error', observed_response=None, retryable=False):
        super().__init__(message)
        self.code, self.observed_response, self.retryable = code, observed_response, retryable


class OutputTokenLimitError(StreamProtocolError):
    def __init__(self, observed_response):
        super().__init__('Provider output token budget exhausted', code='output_token_limit',
                         observed_response=observed_response, retryable=True)


class StreamDeadlineError(TimeoutError):
    pass


@dataclass(frozen=True)
class StreamBudget:
    connect_s: float = 15
    idle_s: float = 120
    generation_s: float = 600
    total_s: float = 900
    attempts: int = 2
    step_s: float = 930

    def __post_init__(self):
        import math
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in
               (self.connect_s, self.idle_s, self.generation_s, self.total_s, self.step_s)):
            raise ValueError('Stream deadlines must be finite and positive')
        if not self.connect_s <= self.idle_s <= self.generation_s <= self.total_s < self.step_s:
            raise ValueError('Inconsistent connection/idle/generation/retry/step deadlines')
        if type(self.attempts) is not int or not 1 <= self.attempts <= 2:
            raise ValueError('At most two transport attempts are supported')


class Completion:
    """A small, SDK-independent completion with the usual accessors."""
    def __init__(self, data):
        from types import SimpleNamespace
        self.data = data
        self.choices = [SimpleNamespace(finish_reason=data['choices'][0]['finish_reason'],
            message=SimpleNamespace(**data['choices'][0]['message']))]
        self.usage = SimpleNamespace(**(data.get('usage') or {}))

    def model_dump(self, **kwargs):
        return deepcopy(self.data)


class SSEAccumulator:
    def __init__(self):
        self.model = self.identifier = None
        self.created = 0
        self.content, self.reasoning, self.tools = [], [], {}
        self.usage, self.finish, self.done = None, None, False
        self.characters = 0
        self.refusal = None
        self.parse_error = None

    def add(self, value):
        try:
            return self._add(value)
        except StreamProtocolError as exc:
            # Drain malformed candidates for their final usage. Nothing is
            # executable until complete() and whole-batch validation succeed.
            self.parse_error = self.parse_error or exc
        except (ValueError, TypeError, KeyError, AttributeError):
            self.parse_error = self.parse_error or StreamProtocolError(
                'Invalid SSE JSON or delta structure', code='invalid_delta', retryable=True)

    def _add(self, value):
        if value == '[DONE]':
            self.done = True
            return
        if self.done:
            raise StreamProtocolError('Data arrived after the stream terminator')
        data = json.loads(value)
        if data.get('error'):
            raise StreamProtocolError('Provider sent an error in the SSE body')
        if data.get('model'):
            if data['model'] != 'kimi-k3':
                raise StreamProtocolError('Unexpected streamed model')
            self.model = data['model']
        self.identifier = data.get('id', self.identifier)
        self.created = data.get('created', self.created)
        if data.get('usage') is not None:
            self.usage = data['usage']
        for choice in data.get('choices', []):
            if choice.get('index', 0) != 0:
                raise StreamProtocolError('Only one completion choice is allowed')
            if choice.get('finish_reason'):
                self.finish = choice['finish_reason']
            delta = choice.get('delta') or {}
            if delta.get('refusal'):
                self.refusal = delta['refusal']
            for name, target in (('content', self.content), ('reasoning_content', self.reasoning)):
                fragment = delta.get(name)
                if fragment:
                    if not isinstance(fragment, str):
                        raise StreamProtocolError('Invalid text delta')
                    target.append(fragment)
                    self.characters += len(fragment)
            for call in delta.get('tool_calls') or []:
                index = call.get('index')
                if type(index) is not int or index < 0:
                    raise StreamProtocolError('Invalid tool delta index', code='invalid_delta', retryable=True)
                tool = self.tools.setdefault(index, {'id': '', 'type': 'function',
                                                     'function': {'name': '', 'arguments': ''}})
                for key in ('id', 'type'):
                    if call.get(key):
                        tool[key] = call[key]
                for key in ('name', 'arguments'):
                    fragment = (call.get('function') or {}).get(key)
                    if fragment:
                        tool['function'][key] += fragment
                        self.characters += len(fragment)

    def observed_response(self):
        message = {'role': 'assistant', 'content': ''.join(self.content) or None,
                   'reasoning_content': ''.join(self.reasoning)}
        if self.tools:
            message['tool_calls'] = [deepcopy(self.tools[i]) for i in sorted(self.tools)]
        return {'id': self.identifier, 'model': self.model, 'created': self.created,
                'choices': [{'index': 0, 'finish_reason': self.finish, 'message': message}],
                'usage': deepcopy(self.usage), 'stream_done': self.done}

    def complete(self):
        if not self.done:
            raise StreamProtocolError('Stream terminator missing', code='missing_done', retryable=True)
        if self.finish == 'length':
            raise OutputTokenLimitError(self.observed_response())
        if self.parse_error:
            self.parse_error.retryable = True
            raise self.parse_error
        if self.refusal or self.finish not in ('stop', 'tool_calls'):
            raise StreamProtocolError('Refused or invalid stream finish', code='invalid_finish')
        if self.model != 'kimi-k3' or not self.identifier:
            raise StreamProtocolError('Missing K3 response identity')
        message = {'role': 'assistant', 'content': ''.join(self.content) or None,
                   'reasoning_content': ''.join(self.reasoning)}
        if self.tools:
            if sorted(self.tools) != list(range(len(self.tools))):
                raise StreamProtocolError('Discontinuous tool indices', code='invalid_delta', retryable=True)
            message['tool_calls'] = [self.tools[i] for i in sorted(self.tools)]
            if any(not t['id'] or t['type'] != 'function' or not t['function']['name']
                   for t in message['tool_calls']):
                raise StreamProtocolError('Incomplete tool identity')
        return Completion({'id': self.identifier, 'model': self.model, 'created': self.created,
            'object': 'chat.completion', 'choices': [{'index': 0, 'finish_reason': self.finish,
            'message': message}], 'usage': self.usage})


class KimiStreamClient:
    def __init__(self, *, budget=None, profile=None, api_key=None, emit=None, stream_dir=None, http_factory=None):
        self.budget = budget or StreamBudget()
        self.profile = profile
        self.key = api_key or os.environ.get('KIMI_API_KEY')
        if not self.key:
            raise ValueError('KIMI_API_KEY is required')
        self.emit = emit or (lambda *args, **kwargs: None)
        self.stream_dir = Path(stream_dir) if stream_dir else None
        self.http_factory = http_factory or httpx.Client
        self.last_timing = {}

    def create(self, *, deadline=None, step_ledger=None, budget_role='executor', generation_attempt=1, parent_request_id=None, **kwargs):
        messages = deepcopy(kwargs.get('messages', []))
        # Native history already contains complete assistant messages, keyed by
        # tool_call_id rather than the legacy XML adapter's content-only cache.
        request = K3Requests(profile=self.profile).prepare({'model': 'kimi-k3', **kwargs, 'messages': []})
        for message in messages:
            if message.get('role') == 'assistant' and 'reasoning_content' not in message:
                raise StreamProtocolError('Native history must preserve original assistant reasoning')
        request.update(messages=messages, stream=True, stream_options={'include_usage': True})
        request.pop('timeout', None)
        end = min(deadline or float('inf'), time.monotonic() + self.budget.total_s)
        for attempt in range(self.budget.attempts):
            if time.monotonic() >= end:
                raise StreamDeadlineError('Role retry budget exhausted')
            try:
                if step_ledger is not None:
                    request['max_completion_tokens'] = min(request['max_completion_tokens'], step_ledger.allowance(budget_role))
                return self._attempt(request, min(end, time.monotonic() + self.budget.generation_s), attempt + 1,
                    step_ledger=step_ledger, budget_role=budget_role, generation_attempt=generation_attempt,
                    parent_request_id=parent_request_id)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if (status is not None and status not in (408, 429) and status < 500) or attempt + 1 == self.budget.attempts:
                    raise
                if time.monotonic() + 3 >= end:
                    raise StreamDeadlineError('No retry budget remains') from None
                time.sleep(3)
        raise AssertionError('unreachable')

    def _attempt(self, payload, end, attempt, *, step_ledger=None, budget_role='executor', generation_attempt=1, parent_request_id=None):
        started = time.monotonic()
        request_id = 'k3s-' + uuid.uuid4().hex
        self.last_request_id = request_id
        if step_ledger is not None:
            step_ledger.reserve(request_id, budget_role, payload['max_completion_tokens'])
        events, cancel = queue.Queue(maxsize=16), threading.Event()
        timing = {'headers_s': None, 'first_chunk_s': None, 'first_reasoning_s': None,
                  'first_content_s': None, 'first_tool_s': None, 'max_chunk_gap_s': 0, 'chunks': 0}
        self.emit('api_request', request_id=request_id, endpoint=BASE_URL, payload=payload,
                  attempt=attempt, generation_attempt=generation_attempt, parent_request_id=parent_request_id,
                  stream_budget=self.budget.__dict__)

        def put(kind, value):
            while not cancel.is_set():
                try:
                    events.put((kind, value, time.monotonic()), timeout=0.2)
                    return
                except queue.Full:
                    pass

        def produce():
            try:
                timeout = httpx.Timeout(connect=self.budget.connect_s, read=self.budget.idle_s,
                                        write=30, pool=self.budget.connect_s)
                with self.http_factory(timeout=timeout) as client:
                    with client.stream('POST', BASE_URL + '/chat/completions',
                            headers={'Authorization': 'Bearer ' + self.key}, json=payload) as response:
                        put('headers', {'status': response.status_code, 'request_id': response.headers.get('x-request-id')})
                        response.raise_for_status()
                        data = []
                        for line in response.iter_lines():
                            if cancel.is_set():
                                break
                            if not line:
                                if data:
                                    put('data', '\n'.join(data))
                                data = []
                            elif line.startswith('data:'):
                                data.append(line[5:].lstrip(' '))
                        if data:
                            put('data', '\n'.join(data))
                put('eof', None)
            except Exception as exc:
                put('error', exc)

        worker = threading.Thread(target=produce, daemon=True, name=request_id)
        worker.start()
        accumulator, last_chunk, status = SSEAccumulator(), None, None
        log = None
        outcome_error = None
        if self.stream_dir:
            self.stream_dir.mkdir(parents=True, exist_ok=True)
            log = (self.stream_dir / (request_id + '.jsonl')).open('w', encoding='utf-8')
        try:
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise StreamDeadlineError('Complete-generation deadline exceeded')
                try:
                    kind, value, at = events.get(timeout=remaining)
                except queue.Empty:
                    raise StreamDeadlineError('Complete-generation deadline exceeded') from None
                elapsed = round(at - started, 4)
                if kind == 'error':
                    raise value
                if kind == 'headers':
                    status = value['status']
                    timing.update(headers_s=elapsed, server_request_id=value['request_id'])
                    self.emit('http_response', status_code=status, request_id=request_id,
                              duration_s=elapsed, url=BASE_URL + '/chat/completions', method='POST')
                elif kind == 'data':
                    if log:
                        log.write(json.dumps({'elapsed_s': elapsed, 'data': value.replace(self.key, '[REDACTED]')}, ensure_ascii=False) + '\n')
                        log.flush()
                    timing['chunks'] += 1
                    if timing['first_chunk_s'] is None:
                        timing['first_chunk_s'] = elapsed
                    if last_chunk is not None:
                        timing['max_chunk_gap_s'] = max(timing['max_chunk_gap_s'], round(at - last_chunk, 4))
                    last_chunk = at
                    accumulator.add(value)
                    for name, seen in (('reasoning', bool(accumulator.reasoning)),
                                       ('content', bool(accumulator.content)), ('tool', bool(accumulator.tools))):
                        if seen and timing['first_' + name + '_s'] is None:
                            timing['first_' + name + '_s'] = elapsed
                elif kind == 'eof':
                    result = accumulator.complete()
                    timing['complete_s'] = round(time.monotonic() - started, 4)
                    self.last_timing = timing
                    self.emit('api_response', request_id=request_id, status_code=status,
                              duration_s=timing['complete_s'], response=result.model_dump(), timings=timing)
                    return result
        except Exception as exc:
            outcome_error = exc
            if isinstance(exc, StreamProtocolError):
                exc.observed_response = accumulator.observed_response()
                exc.request_id = request_id
            self.last_timing = timing
            self.emit('api_error', request_id=request_id, status_code=status,
                      duration_s=round(time.monotonic() - started, 4), error_type=type(exc).__name__,
                      error_code=getattr(exc, 'code', None),
                      error=str(exc).replace(self.key, '[REDACTED]')[:1000], timings=timing)
            raise
        finally:
            cancel.set()
            if log:
                log.close()
            # Never retry an overall-deadline failure: an in-flight producer can
            # take one bounded idle interval to unwind. It cannot execute an action.
            worker.join(timeout=0.1)
            observed = json.loads(json.dumps(accumulator.observed_response(), ensure_ascii=False).replace(self.key, '[REDACTED]'))
            if step_ledger is not None:
                step_ledger.settle(request_id, accumulator.usage)
            self.emit('request_outcome', request_id=request_id, attempt=attempt,
                generation_attempt=generation_attempt, parent_request_id=parent_request_id,
                outcome='error' if outcome_error else 'complete', error_code=getattr(outcome_error, 'code', None),
                finish_reason=accumulator.finish, usage=observed['usage'], observed_response=observed,
                executable=False, stream_done=accumulator.done,
                raw_sse_path=str(self.stream_dir / (request_id + '.jsonl')) if self.stream_dir else None,
                duration_s=round(time.monotonic() - started, 4), timings=timing)

    def close(self):
        pass
