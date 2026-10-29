"""Deterministic original-actor inputs for graph regression and offline reports."""
from contextlib import contextmanager
from itertools import count
from pathlib import Path
import runpy
from types import SimpleNamespace

from kobe_views.model import dumps


@contextmanager
def actor_fixture(monkeypatch, directory, mode='legacy', actions=None, packing=None):
    from ui_kobe.osworld import transitions
    from ui_kobe.api.kimi_stream import Completion

    helpers = runpy.run_path(str(Path(__file__).with_name('test_mini_taskviews.py')))
    identities = count(1)
    monkeypatch.setattr(transitions, 'uuid', SimpleNamespace(
        uuid4=lambda: SimpleNamespace(hex=f'{next(identities):032x}')))
    monkeypatch.setattr(transitions, 'now', lambda: '2026-10-22T00:00:00+00:00')
    # Source hashes include image paths; use a fixed synthetic locator across temporary test roots.
    monkeypatch.setattr(transitions, 'dumps', lambda value: dumps(value).replace(str(directory.resolve()), '/fixture'))
    monkeypatch.setenv('UI_KOBE_MINI_GRAPH_MODE', mode)
    if packing:
        monkeypatch.setenv('UI_KOBE_MINI_GRAPH_PACKING', packing)
    else:
        monkeypatch.delenv('UI_KOBE_MINI_GRAPH_PACKING', raising=False)
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
    monkeypatch.delenv('UI_KOBE_TASK_KEYBOARD_RESEARCH', raising=False)
    monkeypatch.setenv('UI_KOBE_MINI_KEYBOARD_TOOLS', '[]')
    actions = actions or [{'action': 'key', 'keys': ['ctrl', 'a']}] * 3
    actor, obs, transport = helpers['make_actor'](monkeypatch, directory, actions=actions)
    actor.task_current_date = '2026-10-22'
    original = transport.create

    def create(**kwargs):
        value = original(**kwargs).model_dump()
        value['choices'][0]['message']['content'] = '<key_lookup>editing</key_lookup>'
        return Completion(value)

    transport.create = create
    try:
        yield actor, obs, transport, helpers['predict']
    finally:
        actor.close()


def legacy_capture(monkeypatch, directory):
    import hashlib

    with actor_fixture(monkeypatch, directory) as (actor, obs, transport, predict):
        for step in range(3):
            predict(actor, obs, error='Original controller error' if step == 0 else None)
        return {'label': actor.context_label,
                'requests_sha256': [hashlib.sha256(dumps(r).encode()).hexdigest() for r in transport.requests],
                'packets': [r['messages'][-1]['content'][-1]['text'].split('\n', 1)[1]
                            for r in transport.requests]}


def projection_snapshot(actor):
    from copy import deepcopy
    from kobe_views.mini_graph import GraphIndex

    context = actor.mini_context
    cursor = context.trace['journal_seq']
    index = GraphIndex(actor.execution_journal.episode_id, actor.execution_journal.task_id)

    def read(query, parameters):
        return context.read(query.replace('WHERE seq>?', 'WHERE seq>? AND seq<=?'), (parameters[0], cursor))

    index.sync(read)
    return index, deepcopy(context.projection_inputs)
