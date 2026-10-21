"""Bounded pre-CUA research requests with explicit provider-side web search."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import httpx

DEFAULTS = {'protocol': 'responses', 'max_apps': 4, 'topics_per_app': 2,
            'max_output_tokens': 4096, 'timeout_seconds': 90, 'total_seconds': 600}


def settings(actor, overrides=None):
    overrides = dict(overrides or {})
    if actor.get('provider') == 'autodl' and not (
            {'protocol', 'model', 'api_key_env'} <= overrides.keys()
            and ('base_url' in overrides or 'base_url_env' in overrides)):
        raise ValueError('AutoDL Chat Completions has no verified web-search API; '
                         'provide an explicit keyboard research endpoint, protocol, model and key environment')
    allowed = {*DEFAULTS, 'model', 'base_url', 'base_url_env', 'api_key_env'}
    if overrides.keys() - allowed:
        raise ValueError('Unknown keyboard research settings; credentials must use an environment variable')
    value = {**DEFAULTS, 'model': actor.get('model'), 'base_url': actor.get('base_url'),
             'api_key_env': actor.get('api_key_env'), **overrides}
    if 'base_url_env' in value:
        if 'base_url' in overrides:
            raise ValueError('Choose base_url or base_url_env')
        value['base_url'] = os.environ.get(value.pop('base_url_env'), '')
    if value['protocol'] not in ('responses', 'dashscope'):
        raise ValueError('Research requires a Responses or DashScope endpoint with search sources')
    parsed = urlsplit(value['base_url'] or '')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('Research API requires an HTTPS base URL without credentials or query')
    value['base_url'] = value['base_url'].rstrip('/')
    if not isinstance(value['model'], str) or not value['model']:
        raise ValueError('Research model is required')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value['api_key_env'] or ''):
        raise ValueError('Research credential environment variable is required')
    for name, lower, upper in (('max_apps', 1, 6), ('topics_per_app', 1, 3), ('max_output_tokens', 512, 8192),
                               ('timeout_seconds', 5, 180), ('total_seconds', 30, 1200)):
        if type(value[name]) is not int or not lower <= value[name] <= upper:
            raise ValueError('Research setting outside bounded range: ' + name)
    return value


def response_parts(body, protocol):
    if body.get('error') or body.get('code'):
        raise ValueError('Research API returned an error envelope')
    if protocol == 'dashscope':
        output = body['output']
        choice = output['choices'][0]
        if choice.get('finish_reason') not in ('stop', None):
            raise ValueError('Incomplete research response')
        content = choice['message']['content']
        if isinstance(content, list):
            content = ''.join(part.get('text', '') for part in content)
        sources = output.get('search_info', {}).get('search_results', [])
    else:
        if body.get('status') not in ('completed', None) or body.get('incomplete_details'):
            raise ValueError('Incomplete research response')
        content = ''.join(part.get('text', '') for item in body.get('output', [])
                          if item.get('type') == 'message' for part in item.get('content', [])
                          if part.get('type') == 'output_text')
        sources = [source for item in body.get('output', []) if item.get('type') == 'web_search_call'
                   and item.get('status') in ('completed', None)
                   for source in item.get('action', {}).get('sources', [])]
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Research API returned no content')
    return content, sources


class ResearchClient:
    def __init__(self, config, directory, *, client=None):
        self.config, self.root = config, Path(directory)
        self.calls = []
        self.deadline = time.monotonic() + config['total_seconds']
        self.key = os.environ.get(config['api_key_env'])
        if not self.key:
            raise ValueError(config['api_key_env'] + ' is missing; no research request sent')
        self.owned = client is None
        self.client = client or httpx.Client(trust_env=False, follow_redirects=False)

    def call(self, stage, system, content, *, search=False):
        from kobe_views.task_keyboard import url
        c = self.config
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or len(self.calls) >= 1 + 2 * c['max_apps']:
            raise ValueError('Task keyboard research request/time budget exhausted')
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]
        if c['protocol'] == 'responses':
            route = '/responses'
            payload = {'model': c['model'], 'input': messages, 'max_output_tokens': c['max_output_tokens'],
                       'tools': [{'type': 'web_search'}] if search else []}
        else:
            route = '/services/aigc/text-generation/generation'
            parameters = {'result_format': 'message', 'max_tokens': c['max_output_tokens'], 'enable_search': search}
            if search:
                parameters['search_options'] = {'forced_search': True, 'enable_source': True,
                                                'enable_citation': True, 'search_strategy': 'max'}
            payload = {'model': c['model'], 'input': {'messages': messages}, 'parameters': parameters}
        index = len(self.calls) + 1
        item = {'index': index, 'stage': stage, 'search_enabled': search, 'usage': None, 'status': 'started'}
        self.calls.append(item)
        prefix = self.root / 'api' / f'{index:02d}-{stage}'
        prefix.parent.mkdir(exist_ok=True)
        prefix.with_suffix('.request.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        started = time.monotonic()
        try:
            with self.client.stream('POST', c['base_url'] + route, json=payload,
                                    headers={'Authorization': 'Bearer ' + self.key},
                                    timeout=min(c['timeout_seconds'], remaining)) as response:
                item['http_status'] = response.status_code
                response.raise_for_status()
                raw = bytearray()
                for block in response.iter_bytes():
                    raw.extend(block)
                    if len(raw) > 2 * 1024**2 or time.monotonic() > min(self.deadline, started + c['timeout_seconds']):
                        raise ValueError('Research response exceeded time/size budget')
            prefix.with_suffix('.response.json').write_bytes(raw)
            body = json.loads(raw)
            item['usage'] = deepcopy(body.get('usage'))
            answer, sources = response_parts(body, c['protocol'])
            # A flag or a model-written citation is not proof that search ran.
            verified = []
            for source in sources:
                if isinstance(source, dict) and source.get('url'):
                    verified.append({'url': url(source['url']), 'title': source.get('title') or source['url']})
            if search and not verified:
                raise ValueError('API search returned no source evidence; cannot build a researched catalog')
            item.update(status='completed', source_count=len(verified))
            return answer, verified
        except Exception as exc:
            item.update(status='failed', error_type=type(exc).__name__)
            raise
        finally:
            item['elapsed_seconds'] = round(time.monotonic() - started, 3)
            (self.root / 'usage.json').write_text(json.dumps(
                {'calls': self.calls, 'request_count': len(self.calls), 'max_requests': 1 + 2*c['max_apps'],
                 'scope': 'pre_cua_research_separate_from_actor', 'unknown_usage': 'null, never zero'},
                ensure_ascii=False, indent=2), encoding='utf-8')

    def close(self):
        if self.owned:
            self.client.close()
