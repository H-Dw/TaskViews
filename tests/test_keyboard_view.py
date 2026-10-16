from copy import deepcopy
import json

import pytest

from kobe_views.keyboard_view import CATALOG, record, select_topic
from ui_kobe.api.kimi_stream import Completion
from ui_kobe.osworld.checkpoints import ReadAnomaly
from test_mini_taskviews import make_actor, packet, predict


@pytest.mark.parametrize('prose,topic,keys', [
    ('Click in the document area and use Page Down to scroll.', 'page_navigation', ['pagedown']),
    ('Go back and zoom out with Ctrl+-.', 'zoom', ['ctrl', '-']),
    ('Move the invoice into the folder.', 'file_transfer', ['ctrl', 'x']),
    ('Maximize the window.', 'window', ['alt', 'f10']),
])
def test_intent_retrieval_supplies_exact_native_call_before_generation(prose, topic, keys):
    selected, reason = select_topic([prose])
    view = record(selected, reason)
    assert selected == topic and view['recipes'][0]['tool'] == {'action': 'key', 'keys': keys}
    assert 'not_visual_detection' in reason


def annotated(transport, text):
    original = transport.create
    def create(**kwargs):
        body = original(**kwargs).model_dump()
        body['choices'][0]['message']['content'] = text()
        return Completion(body)
    transport.create = create


def test_agent_can_request_a_view_and_retrieve_keyboard_memory_beyond_four_edges(monkeypatch, tmp_path):
    actions = [{'action': 'key', 'keys': ['pagedown']}] + [{'action': 'left_click'}] * 8
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=actions)
    text = 'Page Down'
    annotated(transport, lambda: text)
    predict(actor, obs)
    first = actor.execution_journal.db.execute(
        "SELECT id FROM events WHERE json_extract(payload,'$.kind')='transition'").fetchone()[0]
    text = 'Observe current image'
    for _ in range(6):
        predict(actor, obs)
    text = '<key_lookup>page_navigation</key_lookup>'
    predict(actor, obs)
    predict(actor, obs)
    view = packet(transport)['views']['keyboard']['records'][0]
    assert view['selection'] == 'same_actor_explicit_lookup'
    assert view['memory'][0]['source_event_id'] == first
    assert view['memory'][0]['keys'] == ['pagedown']
    assert view['memory'][0]['image_delta'] == 'same_bytes'
    assert view['memory'][0]['effect_status'] == 'unknown'
    assert len(transport.requests) == 9 and actor.mini_context.trace['packet_bytes'] <= 3000
    assert all(r['source_event_id'] != first for r in packet(transport)['views']['attempts']['records'])
    actor.close()


def test_keyboard_memory_provenance_is_required(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path, actions=[{'action': 'key', 'keys': ['pagedown']}]*2)
    annotated(transport, lambda: 'Page Down')
    predict(actor, obs)
    original = actor.mini_context.read
    def corrupt(query, parameters=()):
        rows = deepcopy(original(query, parameters))
        if parameters and rows and rows[0][1]['kind'] == 'observation':
            rows[0][1]['frame']['original_sha256'] = 'f' * 64
        return rows
    actor.mini_context.read = corrupt
    with pytest.raises(ReadAnomaly, match='provenance'):
        predict(actor, obs)
    assert len(transport.requests) == 1
    actor.close()


@pytest.mark.parametrize('text', ['<key_lookup>shell_command</key_lookup>',
    '<key_lookup>zoom</key_lookup><key_lookup>window</key_lookup>', '<key_lookup>{}</key_lookup>'])
def test_malformed_lookup_never_changes_schema_or_creates_external_actions(text):
    topic, reason = select_topic([text])
    assert topic in CATALOG and reason != 'same_actor_explicit_lookup'
    assert all(r['tool']['action'] == 'key' for r in record(topic, reason)['recipes'])


def test_reference_not_raw_wrong_alias_is_in_current_request(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    annotated(transport, lambda: 'Use Page Down to reveal the next part of the document.')
    predict(actor, obs)
    predict(actor, obs)
    view = packet(transport)['views']['keyboard']['records'][0]
    assert view['recipes'][0]['tool']['keys'] == ['pagedown']
    assert 'page_down' not in json.dumps(view)
    assert actor.mini_context.trace['views']['keyboard']['omitted_records'] == 0
    actor.close()
