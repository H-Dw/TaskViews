"""Qwen SSE framing and aggregation; incomplete streams never become actions."""
from copy import deepcopy
import codecs
import json
import queue
import threading
import time

from .kimi_stream import OutputTokenLimitError, StreamProtocolError


def response_events(client, url, payload, timeout, end):
    """Bound wall time even while the socket is waiting for its next bytes.

    A wall deadline is not retried: the sole reader may need its bounded socket
    timeout to unwind. It has no access to GUI dispatch or completion handling.
    """
    events, cancel = queue.Queue(maxsize=16), threading.Event()

    def put(kind, value):
        while not cancel.is_set():
            try:
                events.put((kind, value), timeout=0.1)
                return
            except queue.Full:
                pass

    def read():
        try:
            with client.stream('POST', url, json=payload, timeout=timeout) as response:
                put('headers', response)
                for chunk in response.iter_bytes():
                    if cancel.is_set():
                        return
                    put('chunk', chunk)
            put('eof', None)
        except Exception as exc:
            put('error', exc)

    reader = threading.Thread(target=read, daemon=True, name='qwen-sse-reader')
    reader.start()
    try:
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Qwen complete-generation deadline reached')
            try:
                kind, value = events.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError('Qwen complete-generation deadline reached') from None
            if kind == 'error':
                raise value
            if kind == 'eof':
                return
            yield kind, value
    finally:
        cancel.set()
        reader.join(timeout=0.1)


class QwenSSE:
    def __init__(self, model):
        self.expected_model = model
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer, self.lines = '', []
        self.identifier = self.model = self.created = None
        self.content, self.reasoning, self.tools = [], [], {}
        self.usage = self.finish = self.error = self.provider_failure = None
        self.done, self.events = False, 0

    def feed(self, chunk, final=False):
        self.buffer += self.decoder.decode(chunk, final=final)
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            line = line.rstrip('\r')
            if not line:
                if self.lines:
                    self.add('\n'.join(self.lines))
                    self.lines = []
            elif line.startswith('data:'):
                self.lines.append(line[5:].removeprefix(' '))
        if final and (self.buffer.strip() or self.lines):
            self.error = self.error or StreamProtocolError('Unterminated SSE event', code='invalid_sse')

    def add(self, value):
        self.events += 1
        try:
            self._add(value)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.error = self.error or (exc if isinstance(exc, StreamProtocolError) else
                StreamProtocolError('Malformed Qwen SSE delta', code='invalid_sse'))

    def _add(self, value):
        if self.done:
            raise StreamProtocolError('SSE data follows DONE', code='invalid_sse')
        if value == '[DONE]':
            self.done = True
            return
        data = json.loads(value)
        if not isinstance(data, dict):
            raise StreamProtocolError('Invalid SSE object', code='invalid_sse')
        nested = {}
        if isinstance(data.get('message'), str):
            try:
                nested = json.loads(data['message'])
            except ValueError:
                pass
        if data.get('error') or data.get('success') is False or (isinstance(nested, dict) and nested.get('error')):
            self.provider_failure = data
            raise StreamProtocolError('Provider error inside SSE', code='provider_error')
        usage = data.get('usage')
        if usage is not None:
            if (not isinstance(usage, dict) or not all(type(usage.get(k)) is int and usage[k] >= 0
                    for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                    or (self.usage is not None and usage != self.usage)):
                raise StreamProtocolError('Invalid or conflicting SSE usage', code='invalid_usage')
            self.usage = deepcopy(usage)
        for key in ('id', 'model', 'created'):
            value = data.get(key)
            attr = 'identifier' if key == 'id' else key
            previous = getattr(self, attr)
            if value is not None:
                if previous is not None and value != previous:
                    raise StreamProtocolError('Conflicting SSE response identity', code='invalid_sse')
                setattr(self, attr, value)
        if self.model is not None and self.model != self.expected_model:
            raise StreamProtocolError('Unexpected Qwen SSE model', code='invalid_sse')
        for choice in data.get('choices', []):
            if type(choice.get('index')) is not int or choice['index'] != 0:
                raise StreamProtocolError('Unexpected SSE choice', code='invalid_sse')
            delta = choice.get('delta') or {}
            if self.finish is not None and delta:
                raise StreamProtocolError('Delta after finish', code='invalid_sse')
            if delta.get('role', 'assistant') != 'assistant' or delta.get('refusal'):
                raise StreamProtocolError('Refused or invalid SSE role', code='invalid_sse')
            for key, target in (('content', self.content), ('reasoning_content', self.reasoning)):
                fragment = delta.get(key)
                if fragment is not None:
                    if not isinstance(fragment, str):
                        raise StreamProtocolError('Invalid SSE text', code='invalid_sse')
                    target.append(fragment)
            for call in delta.get('tool_calls') or []:
                index = call.get('index')
                if type(index) is not int or not 0 <= index < 128:
                    raise StreamProtocolError('Invalid SSE tool index', code='invalid_sse')
                tool = self.tools.setdefault(index, {'id': '', 'type': '', 'function': {'name': '', 'arguments': ''}})
                for key in ('id', 'type'):
                    value = call.get(key)
                    if value is not None:
                        if not isinstance(value, str) or (tool[key] and tool[key] != value):
                            raise StreamProtocolError('Conflicting SSE tool identity', code='invalid_sse')
                        tool[key] = value
                for key in ('name', 'arguments'):
                    fragment = (call.get('function') or {}).get(key)
                    if fragment is not None:
                        if not isinstance(fragment, str):
                            raise StreamProtocolError('Invalid SSE tool text', code='invalid_sse')
                        tool['function'][key] += fragment
            finish = choice.get('finish_reason')
            if finish is not None:
                if self.finish is not None:
                    raise StreamProtocolError('Duplicate SSE finish', code='invalid_sse')
                self.finish = finish

    def observed(self):
        message = {'role': 'assistant', 'content': ''.join(self.content),
                   'reasoning_content': ''.join(self.reasoning)}
        if self.tools:
            message['tool_calls'] = [deepcopy(self.tools[k]) for k in sorted(self.tools)]
        return {'id': self.identifier, 'model': self.model, 'created': self.created, 'object': 'chat.completion',
                'choices': [{'index': 0, 'finish_reason': self.finish, 'message': message}],
                'usage': deepcopy(self.usage)}

    def complete(self):
        body = self.observed()
        if self.error:
            self.error.observed_response = body
            raise self.error
        if not self.done:
            raise StreamProtocolError('Qwen SSE terminator missing', code='missing_done', observed_response=body)
        if self.finish == 'length':
            raise OutputTokenLimitError(body)
        if (not isinstance(self.identifier, str) or not self.identifier or self.model != self.expected_model
                or self.finish not in ('stop', 'tool_calls') or not isinstance(self.created, int)):
            raise StreamProtocolError('Incomplete Qwen SSE response identity/finish', observed_response=body)
        if self.tools:
            if sorted(self.tools) != list(range(len(self.tools))) or self.finish != 'tool_calls':
                raise StreamProtocolError('Incomplete Qwen tool batch', observed_response=body)
            ids = set()
            for tool in self.tools.values():
                if (not tool['id'] or tool['id'] in ids or tool['type'] != 'function'
                        or not tool['function']['name']):
                    raise StreamProtocolError('Incomplete Qwen tool identity', observed_response=body)
                ids.add(tool['id'])
                try:
                    args = json.loads(tool['function']['arguments'])
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    raise StreamProtocolError('Incomplete Qwen tool arguments', observed_response=body)
        elif self.finish == 'tool_calls':
            raise StreamProtocolError('Missing Qwen tool batch', observed_response=body)
        return body
