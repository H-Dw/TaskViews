"""Offline API protocol, archive provenance, opt-in preparation and task isolation."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from kobe_views.keyboard_research import prepare_research, research
from kobe_views.keyboard_selection import task_keyboard_policy
from kobe_views.keyboard_view import DATA, active_catalog, record, select_topic
from kobe_views.task_keyboard import ENV, environment, load_bundle, sha
from scripts.run_official_native_tasks import configure_profile
from ui_kobe.api.keyboard_research import settings
from ui_kobe.osworld.checkpoints import ReadAnomaly
from test_keyboard_view import annotated
from test_mini_profiles import mini_plan
from test_mini_taskviews import make_actor, packet, predict

TASK = {'instruction': 'Use VLC to take a video snapshot, then move the image to the Desktop.',
        'related_apps': ['vlc'], 'evaluator': {'secret': 'never send to researcher'}, 'config': ['do not inspect']}
URLS = {'VLC': 'https://docs.videolan.org/fixture-keyboard.html',
        'GNOME Files': 'https://help.gnome.org/fixture-keyboard.html'}


def mocked_api(root, *, fault=None, before_extract=None):
    seen = []
    apps = [
        {'id': 'vlc', 'name': 'VLC', 'origin': 'explicit', 'evidence': 'VLC',
         'operations': ['snapshot'], 'official_domains': ['docs.videolan.org']},
        {'id': 'files', 'name': 'GNOME Files', 'origin': 'inferred', 'evidence': 'Moving the image needs a file manager',
         'operations': ['rename'], 'official_domains': ['help.gnome.org']},
    ]

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        dashscope = request.url.path.endswith('/generation')
        messages = body['input']['messages'] if dashscope else body['input']
        value = json.loads(messages[-1]['content'])
        searching = body['parameters']['enable_search'] if dashscope else bool(body['tools'])
        sources = []
        if 'public_task' in value:
            assert set(value['public_task']) == {'instruction', 'related_apps'}
            answer = json.dumps({'software': apps})
        elif searching:
            assert 'public_task' not in value and TASK['instruction'] not in request.content.decode()
            name = value['software']
            answer = 'VLC snapshot: Shift+S.' if name == 'VLC' else 'GNOME Files rename: F2.'
            sources = [{'url': URLS[name], 'title': name + ' fixture reference'}]
            if fault == 'missing_sources':
                sources = []
            if dashscope:
                assert body['parameters']['search_options']['forced_search'] is True
                assert body['parameters']['search_options']['enable_source'] is True
            else:
                assert body['tools'] == [{'type': 'web_search'}]
        else:
            name = value['software']
            slug = 'vlc' if name == 'VLC' else 'files'
            archive = root / 'archives' / ('app-' + slug + '.md')
            assert archive.is_file()
            assert value['saved_markdown'] == archive.read_text(encoding='utf-8')
            if before_extract:
                before_extract(archive, value)
            is_vlc = name == 'VLC'
            recipe = {'intent': 'snapshot' if is_vlc else 'rename',
                      'keys': ['shift', 's'] if is_vlc else ['f2'], 'source_url': URLS[name],
                      'evidence': 'Shift+S' if is_vlc else 'F2'}
            if fault == 'unarchived_binding':
                recipe['evidence'] = 'Ctrl+Alt+Q'
            if fault == 'foreign_source':
                recipe['source_url'] = 'https://unrelated.example/guessed'
            if fault == 'bad_key':
                recipe['keys'] = ['page_down']
            if fault == 'sequential_chord':
                recipe['keys'] = ['g', 'i']
            answer = json.dumps({'topics': [{'id': recipe['intent'], 'scope': name + ', Linux default keymap; focus main view',
                                             'check': 'Confirm the requested visible change', 'recipes': [recipe]}],
                                 'notes': 'Synthetic offline fixture, not real web research.'})
        usage = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
                 'x_tools': {'web_search': {'count': 1}} if searching else {}}
        if dashscope:
            response = {'output': {'choices': [{'finish_reason': 'stop', 'message': {'content': answer}}],
                                   'search_info': {'search_results': sources}}, 'usage': usage}
        else:
            response = {'status': 'completed', 'output': [
                *([{'type': 'web_search_call', 'status': 'completed', 'action': {'sources': sources}}] if searching else []),
                {'type': 'message', 'content': [{'type': 'output_text', 'text': answer}]}], 'usage': usage}
        return httpx.Response(200, json=response)
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


@pytest.fixture
def build(monkeypatch, tmp_path):
    monkeypatch.setenv('TASK_KEYBOARD_TEST_KEY', 'test-only-not-a-real-credential')

    def make(name='bundle', *, protocol='responses', fault=None, task=None):
        root = tmp_path / name
        client, seen = mocked_api(root, fault=fault)
        config = settings({'model': 'fixture-model', 'base_url': 'https://fixture.example/v1',
                           'api_key_env': 'TASK_KEYBOARD_TEST_KEY'}, {'protocol': protocol})
        try:
            reference = research(task or TASK, root, config, client=client)
        finally:
            client.close()
        return reference, seen
    return make


@pytest.mark.parametrize('protocol', ['responses', 'dashscope'])
def test_api_search_is_real_archived_before_extraction_and_does_not_change_shared_catalog(build, protocol):
    before = deepcopy(DATA)
    reference, calls = build(protocol=protocol)
    root = Path(reference['directory'])
    catalog = load_bundle(reference, task=TASK)
    assert set(catalog['topics']) == {'task.vlc.snapshot', 'task.files.rename'}
    assert len(calls) == 5
    assert (root / 'archives/app-vlc.md').is_file() and (root / 'keyboard/app-vlc.md').is_file()
    assert DATA == before and 'task.vlc.snapshot' not in active_catalog()
    usage = json.loads((root / 'usage.json').read_text())
    assert usage['request_count'] == 5 and [c['search_enabled'] for c in usage['calls']] == [False, True, False, True, False]
    assert all(c['usage']['total_tokens'] == 150 for c in usage['calls'])
    saved = ''.join(p.read_text(encoding='utf-8') for p in root.rglob('*') if p.is_file())
    assert 'test-only-not-a-real-credential' not in saved and 'never send to researcher' not in saved
    assert select_topic(['<key_lookup>task.vlc.snapshot</key_lookup>'])[0] is None
    assert record('task.vlc.snapshot', 'fixture', task_catalog=catalog)['recipes'][0]['tool']['keys'] == ['shift', 's']


@pytest.mark.parametrize('fault', ['missing_sources', 'unarchived_binding', 'foreign_source', 'bad_key', 'sequential_chord'])
def test_search_or_evidence_failure_retains_attempt_and_never_activates_catalog(build, tmp_path, fault):
    with pytest.raises(ValueError):
        build(fault=fault)
    root = tmp_path / 'bundle'
    failure = json.loads((root / 'failure.json').read_text())
    assert failure['catalog_activation'] is False and failure['gui_actions'] == 0
    assert (root / 'usage.json').is_file() and not (root / 'manifest.json').exists()
    if fault != 'missing_sources':
        assert (root / 'archives/app-vlc.md').is_file()


def test_hash_binding_rejects_changed_archive_different_task_and_overwrite(build):
    reference, _ = build()
    root = Path(reference['directory'])
    with pytest.raises(ValueError, match='different task'):
        load_bundle(reference, task={'instruction': 'Another task'})
    with pytest.raises(FileExistsError):
        research(TASK, root, {})
    (root / 'archives/app-vlc.md').write_text('changed after freezing', encoding='utf-8')
    with pytest.raises(ValueError, match='artifact changed'):
        load_bundle(reference)


def test_opt_in_disabled_makes_no_requests_or_directories(monkeypatch, tmp_path):
    monkeypatch.setattr('kobe_views.keyboard_research.ResearchClient',
                        lambda *a, **k: pytest.fail('Research must not run while disabled'))
    plan = mini_plan()
    prepare_research(plan, TASK, tmp_path / 'new')
    assert not (tmp_path / 'new').exists() and 'mini_keyboard_research' not in plan
    with pytest.raises(ValueError, match='requires --keyboard-research'):
        prepare_research(plan, TASK, tmp_path, config_path=tmp_path / 'config')
    assert environment({}, arm='taskviews')[ENV] == ''
    assert environment({'mini_keyboard_research': {'foreign': True}}, arm='baseline')[ENV] == ''


def test_temporary_topics_reach_actor_but_do_not_leak_and_checkpoint_rejects_other_bundle(build, monkeypatch, tmp_path):
    reference, _ = build()
    monkeypatch.setattr('test_mini_taskviews.TASK', TASK['instruction'])
    from scripts import osworld_native_experiment
    monkeypatch.setattr(osworld_native_experiment, 'require_mini_branch', lambda: None)
    plan = {**mini_plan(), 'official': TASK, **task_keyboard_policy(TASK), 'mini_keyboard_research': reference}
    manifest = {key: plan[key] for key in ('taskviews_profile', 'mini_profile', 'source_branch',
                                           'mini_keyboard_tools', 'mini_keyboard_selection', 'mini_keyboard_research')}
    configure_profile(plan, manifest)
    actor, obs, transport = make_actor(monkeypatch, tmp_path / 'actor')
    try:
        annotated(transport, lambda: '<key_lookup>task.vlc.snapshot</key_lookup>')
        predict(actor, obs)
        assert 'task.vlc.snapshot' in packet(transport)['views']['current']['records'][0]['keyboard_lookup']['topics']
        predict(actor, obs)
        row = packet(transport)['views']['keyboard']['records'][0]
        assert row['topic'] == 'task.vlc.snapshot' and row['verification'] == 'web_reference_not_guest_tested'
        assert actor.mini_context.trace['packet_bytes'] <= 3000 and len(transport.requests) == 2
        saved = actor.checkpoint_state()
        actor.restore_checkpoint_state(saved)
        second, _ = build('second')
        actor.task_keyboard = load_bundle(second)
        with pytest.raises(ReadAnomaly, match='profile'):
            actor.restore_checkpoint_state(saved)
        monkeypatch.setattr('test_mini_taskviews.TASK', 'Different task')
        with pytest.raises(ReadAnomaly, match='different task'):
            predict(actor, obs)
        assert len(transport.requests) == 2
    finally:
        actor.close()
    configure_profile(mini_plan(), {key: mini_plan()[key] for key in ('taskviews_profile', 'mini_profile', 'source_branch')})
    assert os.environ[ENV] == ''
    other, _, _ = make_actor(monkeypatch, tmp_path / 'other')
    assert other.task_keyboard is None
    other.close()


def test_verified_prepare_research_precedes_plan_and_is_frozen(build, tmp_path, monkeypatch):
    from scripts import verified_invoice as verified
    reference, _ = build()
    task_file = tmp_path / verified.task_path('invoice')
    verified.write(task_file, TASK)
    monkeypatch.setattr(verified, 'verify_task', lambda *a: TASK)
    monkeypatch.setattr(verified, 'sources', lambda *a: {
        'benchmark': {'repo': str(tmp_path)}, 'actor_compiler': {'repo': str(tmp_path)}})
    monkeypatch.setattr(verified, 'project_identity', lambda: {})
    monkeypatch.setattr(verified, 'asset_files', lambda task: [])
    monkeypatch.setattr(verified, 'validation_evidence', lambda *a: {'directory': str(tmp_path), 'sha256': {}})
    monkeypatch.setattr(verified.subprocess, 'check_output', lambda *a, **k: 'fixture-commit')
    calls = []

    def prepare(plan, task, root, **kwargs):
        assert not (root / 'plan.json').exists() and kwargs['enabled'] is True
        assert task == TASK
        calls.append(kwargs)
        plan['mini_keyboard_research'] = reference

    monkeypatch.setattr('kobe_views.keyboard_research.prepare_research', prepare)
    args = SimpleNamespace(root=tmp_path / 'plan', benchmark_repo=tmp_path, compiler_repo=tmp_path,
        assets=tmp_path, image=tmp_path / 'no-image', image_proof=tmp_path / 'no-proof',
        validation_dir=tmp_path / 'proof', provider='qwen', sx_url_env='SX_URL', coordinate_type='absolute',
        experiment='legacy-low35', keyboard_research=True, keyboard_research_config=None)
    verified.prepare(args)
    plan = verified.validate_plan(args.root)
    assert len(calls) == 1 and plan['mini_keyboard_research'] == reference
    assert verified.read(args.root / 'state.json')['vm_starts'] == 0
    (Path(reference['directory']) / 'catalog.json').write_text('{}', encoding='utf-8')
    assert sha(args.root / 'plan.json') == verified.read(args.root / 'plan.sha256.json')['sha256']
    with pytest.raises(ValueError, match='artifact changed'):
        verified.validate_plan(args.root)


def test_missing_credentials_do_not_send_request(monkeypatch, tmp_path):
    monkeypatch.delenv('TASK_KEYBOARD_MISSING_KEY', raising=False)
    config = settings({'model': 'fixture', 'base_url': 'https://fixture.example/v1',
                       'api_key_env': 'TASK_KEYBOARD_MISSING_KEY'})
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('No network request'))) as client:
        with pytest.raises(ValueError, match='is missing'):
            research(TASK, tmp_path / 'missing-key', config, client=client)
    assert not (tmp_path / 'missing-key' / 'manifest.json').exists()
