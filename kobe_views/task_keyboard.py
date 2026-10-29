"""Immutable, task-bound keyboard references; never mutate the shared catalog."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .model import dumps
from .keyboard_selection import task_fields

VERSION = 'task_keyboard_research_v1'
ENV = 'UI_KOBE_TASK_KEYBOARD_RESEARCH'
SLUG = re.compile(r'[a-z][a-z0-9_]{0,39}')
# Conservative subset of the pinned PyAutoGUI key names. Unsupported keys stay in research notes.
KEYS = set('abcdefghijklmnopqrstuvwxyz0123456789`-=[]\\;\',./!@#$%^&*()_+{}|:"<>?~')
KEYS.update(('ctrl', 'shift', 'alt', 'win', 'return', 'enter', 'escape', 'space', 'tab', 'backspace',
             'delete', 'insert', 'home', 'end', 'left', 'right', 'up', 'down', 'pageup', 'pagedown',
             'capslock', 'numlock', 'scrolllock', 'printscreen', 'pause', 'apps'))
KEYS.update('f' + str(n) for n in range(1, 25))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def task_sha(task):
    return hashlib.sha256(dumps(task_fields(task)).encode()).hexdigest()


def instruction_sha(instruction):
    return hashlib.sha256(instruction.encode()).hexdigest()


def url(value):
    text(value, 800)
    parsed = urlsplit(value)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
            or parsed.hostname in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('Research source must be a public HTTP(S) URL')
    return value


def text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError('Invalid or oversized task keyboard text')
    return value


def validate_catalog(catalog):
    if (catalog.get('version') != VERSION or catalog.get('platform') != 'linux'
            or not re.fullmatch(r'[0-9a-f]{32}', catalog.get('scope_id', ''))
            or not re.fullmatch(r'[0-9a-f]{64}', catalog.get('task_input_sha256', ''))
            or not re.fullmatch(r'[0-9a-f]{64}', catalog.get('instruction_sha256', ''))):
        raise ValueError('Invalid task keyboard identity')
    sources, topics = catalog.get('sources'), catalog.get('topics')
    if not isinstance(sources, dict) or not isinstance(topics, dict) or len(topics) > 18:
        raise ValueError('Invalid task keyboard catalog')
    for source in sources.values():
        text(source['title'], 800)
        url(source['url'])
    for name, entry in topics.items():
        if not re.fullmatch(r'task\.[a-z][a-z0-9_]{0,39}\.[a-z][a-z0-9_]{0,39}', name):
            raise ValueError('Temporary recipes must use task.<software>.<topic>')
        text(entry['scope'], 380)
        text(entry['check'], 250)
        refs = entry['sources']
        if not isinstance(refs, list) or not refs or not set(refs) <= sources.keys():
            raise ValueError('Task keyboard topic has no archived source')
        recipes = entry['recipes']
        if not isinstance(recipes, list) or not 1 <= len(recipes) <= 4:
            raise ValueError('Invalid task keyboard recipes')
        for recipe in recipes:
            text(recipe['intent'], 120)
            action = recipe['tool']
            keys = action.get('keys')
            if (set(action) != {'action', 'keys'} or action['action'] != 'key'
                    or not isinstance(keys, list) or not 1 <= len(keys) <= 4
                    or any(not isinstance(key, str) or key not in KEYS for key in keys)
                    or len(keys) != len(set(keys))
                    or sum(key not in {'ctrl', 'shift', 'alt', 'win'} for key in keys) > 1):
                raise ValueError('Invalid native chord; sequences need separate calls')
        if len(dumps(entry).encode()) > 1400:
            raise ValueError('Task keyboard topic exceeds its view budget')
        from .keyboard_view import record
        if len(dumps(record(name, 'same_actor_explicit_lookup', task_catalog=catalog)).encode()) > 1400:
            raise ValueError('Task keyboard reference exceeds its view budget')
    return catalog


def load_bundle(reference, *, task=None):
    """Validate every archived artifact before making references available."""
    if not isinstance(reference, dict) or reference.get('version') != VERSION:
        raise ValueError('Invalid task keyboard research reference')
    root = Path(reference['directory']).resolve()
    manifest_file = root / 'manifest.json'
    if sha(manifest_file) != reference['manifest_sha256']:
        raise ValueError('Task keyboard research manifest changed')
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if (manifest.get('version') != VERSION or manifest.get('status') != 'ready'
            or manifest.get('scope_id') != reference.get('scope_id')
            or manifest.get('request_count') != reference.get('request_count')):
        raise ValueError('Task keyboard research is not ready for this scope')
    files = manifest.get('files', {})
    if not {'catalog.json', 'task.json', 'discovery.json', 'usage.json'} <= files.keys():
        raise ValueError('Task keyboard research artifacts are incomplete')
    for name, digest in files.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path == root or path.is_symlink() or sha(path) != digest:
            raise ValueError('Task keyboard research artifact changed or escaped its directory')
    catalog = validate_catalog(json.loads((root / 'catalog.json').read_text(encoding='utf-8')))
    saved_task = json.loads((root / 'task.json').read_text(encoding='utf-8'))
    if (catalog['scope_id'] != reference['scope_id'] or task_sha(saved_task) != catalog['task_input_sha256']
            or instruction_sha(saved_task['instruction']) != catalog['instruction_sha256']
            or task is not None and task_sha(task) != catalog['task_input_sha256']):
        raise ValueError('Task keyboard research belongs to a different task')
    for entry in catalog['topics'].values():
        for source_id in entry['sources']:
            if catalog['sources'][source_id]['archive'] not in files:
                raise ValueError('Task keyboard source has no frozen Markdown archive')
    catalog['identity'] = {key: reference[key] for key in ('scope_id', 'manifest_sha256')}
    catalog['identity'].update(catalog_sha256=files['catalog.json'], task_input_sha256=catalog['task_input_sha256'])
    return catalog


def validate_plan_research(plan, task):
    reference = plan.get('mini_keyboard_research')
    if reference is not None:
        if plan.get('taskviews_profile') != 'mini_fixed_v1' or 'taskviews' not in plan.get('arms', []):
            raise ValueError('Task keyboard research requires Mini TaskViews')
        load_bundle(reference, task=task)


def environment(plan, *, arm):
    """Always clear inherited temporary catalogs when this plan/arm has none."""
    reference = plan.get('mini_keyboard_research') if arm == 'taskviews' else None
    from .keyboard_guidance import ENV as GUIDANCE_ENV
    guidance = plan.get('mini_guidance') if arm == 'taskviews' else None
    return {ENV: json.dumps(reference) if reference else '',
            GUIDANCE_ENV: json.dumps(guidance) if guidance else ''}
