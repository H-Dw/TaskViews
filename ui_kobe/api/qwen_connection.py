"""Credential-free HTTPX phase evidence and conservative connection reset handling."""
from __future__ import annotations

from copy import deepcopy
import threading
import time

import httpx

from .kimi_stream import safe_error_body


def exception_chain(error, key):
    result, seen = [], set()
    while error is not None and id(error) not in seen and len(result) < 8:
        seen.add(id(error))
        result.append({'type': type(error).__name__, 'error': safe_error_body(str(error), key)[:1000],
                       'errno': getattr(error, 'errno', None)})
        error = error.__cause__ or error.__context__
    return result


class QwenConnectionUnavailable(httpx.ConnectError):
    code = 'connection_reset_circuit_open'

    def __init__(self, count, phase):
        super().__init__(f'{count} consecutive connection resets before origin HTTP dispatch ({phase}); '
                         'remaining retries stopped; preserve checkpoint and wait for connection recovery')


class ConnectionTrace:
    """Reader-thread callbacks collect only names, timings and redacted failures.

    No trace info dict, headers, request object, body or TLS object is serialized.
    The foreground caller emits the completed snapshot with its real request ID.
    Missing trace events never prove that a request was not sent.
    """
    def __init__(self, key, started=None):
        self.key = key
        self.started = time.monotonic() if started is None else started
        self._lock = threading.Lock()
        self.events = []
        self.first_failure = None
        self.headers_started = self.headers_complete = False
        self.body_started = self.body_complete = self.response_headers = False
        self.truncated = False

    def __call__(self, name, info):
        item = {'event': name, 'seconds': round(time.monotonic() - self.started, 6)}
        error = info.get('exception')
        if error is not None:
            item.update(error_type=type(error).__name__, error=safe_error_body(str(error), self.key)[:1000])
        # Ignore all other fields: httpcore may include credentials in request
        # objects and header tuples, even in otherwise harmless trace events.
        with self._lock:
            if len(self.events) < 64:
                self.events.append(item)
            else:
                self.truncated = True
            if name.endswith('.failed') and self.first_failure is None:
                self.first_failure = item
            if name.endswith('send_request_headers.started'):
                self.headers_started = True
            if name.endswith('send_request_headers.complete'):
                self.headers_complete = True
            if name.endswith('send_request_body.started'):
                self.body_started = True
            if name.endswith('send_request_body.complete'):
                self.body_complete = True
            if name.endswith('receive_response_headers.complete'):
                self.response_headers = True

    def snapshot(self):
        with self._lock:
            failure_phase = self.first_failure['event'] if self.first_failure else None
            pre_http = bool(failure_phase in ('connection.connect_tcp.failed', 'connection.start_tls.failed')
                            and not self.headers_started and not self.truncated)
            return deepcopy({'version': 'qwen-connection-trace-v1', 'events': self.events,
                'events_truncated': self.truncated, 'first_failure': self.first_failure,
                'failure_phase': failure_phase, 'request_headers_started': self.headers_started,
                'request_headers_complete': self.headers_complete, 'request_body_started': self.body_started,
                'request_body_complete': self.body_complete, 'response_headers_received': self.response_headers,
                'delivery': 'confirmed_no_origin_http_dispatch' if pre_http else
                            'response_headers_received' if self.response_headers else 'unconfirmed'})

    def confirmed_pre_http_reset(self, error):
        if not isinstance(error, httpx.ConnectError):
            return False
        reset = any(item['errno'] == 104 or 'connection reset' in item['error'].lower()
                    for item in exception_chain(error, self.key))
        return reset and self.snapshot()['delivery'] == 'confirmed_no_origin_http_dispatch'
