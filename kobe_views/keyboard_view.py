"""Scoped, source-backed key references. Only general controls route by default."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .model import dumps

CATALOG_PATH = Path(__file__).with_name('key_tools') / 'catalog.json'
DATA = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
VERSION = DATA['version']
SOURCES = {key: value['url'] for key, value in DATA['sources'].items()}
TOOLSETS = DATA['toolsets']
CATALOG = TOOLSETS['general']['topics']
CATALOG_SHA256 = hashlib.sha256(dumps(DATA).encode()).hexdigest()
PATTERNS = (
    ('window_switch', r'\bswitch\b.*\b(?:window|app|application)s?\b|切换.*(?:窗口|应用)'),
    ('page_navigation', r'page[ _-]?(down|up)|scroll|翻页|滚动'),
    ('clipboard', r'\b(?:cut|copy|paste)\b|\bmove\b.*\b(?:file|folder)\b|剪切|粘贴|复制|移动文件'),
    ('undo', r'\bundo\b|撤销'),
    ('focus_navigation', r'\b(?:next|previous) (?:control|field)\b|焦点遍历|下一个控件'),
    ('context_menu', r'\bcontext menu\b|上下文菜单|右键菜单'),
    ('popup_dismiss', r'\bdismiss\b|\bcancel\b|取消|关闭弹窗'),
    ('editing', r'\b(?:type|edit|confirm)\b|输入|编辑|确认'),
)
# Intent is never app detection; these operations need a named toolset.
SCOPED_INTENT = r'\b(?:rename|maximi[sz]e|unmaximi[sz]e|minimi[sz]e|zoom)\b|fit.page|重命名|扩展名|最大化|最小化|缩放|放大|缩小'


def normalize_toolsets(toolsets=()):
    """The current actor is pinned to Linux/X11; foreign backends are references."""
    if not isinstance(toolsets, (list, tuple)) or any(not isinstance(key, str) for key in toolsets):
        raise ValueError('Keyboard toolsets must be a list of exact catalog IDs')
    if len(set(toolsets)) != len(toolsets):
        raise ValueError('Duplicate keyboard toolset')
    for key in toolsets:
        if key == 'general' or key not in TOOLSETS:
            raise ValueError('Unknown or redundant keyboard toolset: ' + key)
        entry = TOOLSETS[key]
        if entry['reference_only'] or not entry['topics'] or DATA['runtime_platform'] not in entry['platforms']:
            raise ValueError('Keyboard toolset is incompatible with the Linux/X11 actor: ' + key)
    return tuple(sorted(toolsets))


def active_catalog(toolsets=()):
    active = dict(CATALOG)
    for key in normalize_toolsets(toolsets):
        for name, entry in TOOLSETS[key]['topics'].items():
            active[key + '.' + name] = entry
    return active


def select_topic(proposals, toolsets=()):
    """Newest intent only. Scoped references require both opt-in and exact lookup."""
    active = active_catalog(toolsets)
    # An empty newest intent must not revive an older request.
    text = proposals[0] if proposals and isinstance(proposals[0], str) else ''
    if '<key_lookup' in text or '</key_lookup' in text:
        requests = re.findall(r'<key_lookup>([a-z0-9_.]+)</key_lookup>', text)
        if (text.count('<key_lookup>') == text.count('</key_lookup>') == 1
                and text.count('<key_lookup') == 1 and len(requests) == 1):
            if requests[0] in active:
                return requests[0], 'same_actor_explicit_lookup'
            if any(requests[0].startswith(key + '.') for key in TOOLSETS if key != 'general'):
                return None, 'disabled_or_unknown_scoped_lookup'
        return None, 'invalid_lookup'
    if re.search(SCOPED_INTENT, text, re.I):
        return None, 'scoped_intent_requires_explicit_toolset_and_lookup'
    for topic, pattern in PATTERNS:
        if re.search(pattern, text, re.I):
            return topic, 'recent_model_intent_not_visual_detection'
    return None, 'no_matching_intent'


def key_topic(keys, topic=None, toolsets=()):
    """Exact chords only; unknown keys never become editing evidence."""
    active = active_catalog(toolsets)
    if topic is not None:
        row = active.get(topic)
        return topic if row and any(r['tool']['keys'] == keys for r in row['recipes']) else None
    matches = [name for name, entry in active.items() if any(r['tool']['keys'] == keys for r in entry['recipes'])]
    return matches[0] if len(matches) == 1 else None


def record(topic, selection, memories=(), omitted=0, *, toolsets=()):
    catalog = active_catalog(toolsets)[topic]
    group_id = topic.rsplit('.', 1)[0] if '.' in topic else 'general'
    return {'version': VERSION, 'grade': 'key_reference_and_episode_evidence',
        'topic': topic, 'selection': selection, 'toolset': group_id, 'scope': catalog['scope'],
        'source': SOURCES[catalog['sources'][0]],
        'recipes': deepcopy(catalog['recipes']), 'check': catalog['check'],
        'memory': deepcopy(list(memories)), 'memory_omitted': omitted}


def lookup_guide(toolsets=()):
    return {'format': '<key_lookup>topic</key_lookup>', 'topics': list(active_catalog(toolsets)),
            'check': 'Scoped topics need exact lookup; verify current app/focus.'}


def policy(toolsets=()):
    enabled = normalize_toolsets(toolsets)
    return {'version': VERSION, 'platform': DATA['runtime_platform'],
            'enabled_toolsets': ['general', *enabled], 'topics': list(active_catalog(enabled)),
            'max_key_edges': 32, 'max_memory_rows': 2,
            'catalog_sha256': CATALOG_SHA256,
            'selection': 'general newest intent; scoped exact lookup only after explicit opt-in; no app detection',
            'memory': 'same episode exact chord evidence; applicability and semantic success remain unknown'}
