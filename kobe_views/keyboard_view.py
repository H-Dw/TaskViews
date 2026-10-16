"""Intent-indexed key recipes. Display labels, X11 names and tool keys differ."""
from copy import deepcopy
import hashlib
import re

from .model import dumps

VERSION = 'mini_keyboard_v2'
SOURCES = {
    'document': 'https://help.gnome.org/evince/movingaround.html',
    'files': 'https://help.gnome.org/gnome-help/files-copy.html',
    'window': 'https://help.gnome.org/gnome-help/shell-windows-maximize.html',
    'navigation': 'https://help.gnome.org/gnome-help/keyboard-nav.html',
    'rename': 'https://help.gnome.org/gnome-help/files-rename.html',
    'backend': 'PyAutoGUI 0.9.54 KEY_NAMES and _pyautogui_x11.py; pinned qwen parser/actions',
}
CATALOG = {
    'page_navigation': {'scope': 'focused document pane', 'source': 'document',
        'recipes': [('Page Down / scroll one viewport', ['pagedown']),
                    ('Page Up / scroll one viewport', ['pageup']),
                    ('Evince next PDF page', ['ctrl', 'pagedown'])]},
    'zoom': {'scope': 'Evince document viewer', 'source': 'document',
        'recipes': [('zoom out', ['ctrl', '-']), ('zoom in', ['ctrl', '+'])]},
    'file_transfer': {'scope': 'GNOME Files; select source, cut, navigate destination, paste', 'source': 'files',
        'recipes': [('cut selected files', ['ctrl', 'x']), ('copy selected files', ['ctrl', 'c']),
                    ('paste into current folder', ['ctrl', 'v'])]},
    'window_maximize': {'scope': 'GNOME active window; maximize is a toggle', 'source': 'window',
        'recipes': [('toggle maximize', ['alt', 'f10'])]},
    'window_minimize': {'scope': 'GNOME active window; Super is the backend win key', 'source': 'navigation',
        'recipes': [('minimize active window', ['win', 'h'])]},
    'window_switch': {'scope': 'GNOME applications; Super is the backend win key; recheck focus', 'source': 'navigation',
        'recipes': [('switch application', ['win', 'tab'])]},
    'rename': {'scope': 'GNOME Files; selected file, then editable basename or complete name', 'source': 'rename',
        'recipes': [('rename selected file', ['f2'])],
        'check': 'Observe which text is selected: basename or full name. Preserve the extension exactly once; verify after confirm.'},
    'editing': {'scope': 'focused editable field; verify before confirm', 'source': 'backend',
        'recipes': [('select field text', ['ctrl', 'a']), ('confirm', ['return']), ('dismiss', ['escape'])]},
}
PATTERNS = (
    ('window_minimize', r'\bminimi[sz]e\b|\bhide (?:the |this |active )?window\b|最小化|隐藏窗口'),
    ('window_maximize', r'\b(?:maximi[sz]e|unmaximi[sz]e)\b|最大化'),
    ('window_switch', r'\bswitch\b.*\b(?:window|app|application)s?\b|切换.*(?:窗口|应用)'),
    ('rename', r'\brename\b|\bbasename\b|重命名|扩展名'),
    ('zoom', r'zoom|fit.page|缩放|放大|缩小'),
    ('page_navigation', r'page[ _-]?(down|up)|scroll|翻页|滚动'),
    ('file_transfer', r'\b(?:cut|copy|paste)\b|\bmove\b.*\b(?:file|folder)\b|剪切|粘贴|复制|移动文件'),
    ('editing', r'\b(?:type|edit|confirm|dismiss)\b|输入|编辑|确认|取消'),
)


def select_topic(proposals):
    """Only intent routing, never a claim that an app/focus was detected."""
    proposals = [text for text in proposals if isinstance(text, str)]
    # Only the newest intent routes automatically. An old plan must not keep a
    # window/file recipe alive through unrelated later observations.
    for text in proposals[:1]:
        if not isinstance(text, str):
            continue
        requests = re.findall(r'<key_lookup>([a-z_]+)</key_lookup>', text)
        if len(requests) == 1 and requests[0] in CATALOG:
            return requests[0], 'same_actor_explicit_lookup'
        if '<key_lookup' in text:
            return None, 'invalid_lookup'
    for text in proposals[:1]:
        for topic, pattern in PATTERNS:
            if isinstance(text, str) and re.search(pattern, text, re.I):
                return topic, 'recent_model_intent_not_visual_detection'
    return None, 'no_matching_intent'


def key_topic(keys):
    if any(k in ('pagedown', 'pageup', 'page_down', 'page_up', 'home', 'end') for k in keys):
        return 'page_navigation'
    if 'ctrl' in keys and any(k in ('-', '+', 'minus') for k in keys):
        return 'zoom'
    if 'ctrl' in keys and any(k in ('x', 'c', 'v') for k in keys):
        return 'file_transfer'
    if 'alt' in keys and 'f10' in keys:
        return 'window_maximize'
    if 'win' in keys and 'h' in keys:
        return 'window_minimize'
    if 'win' in keys and 'tab' in keys:
        return 'window_switch'
    if 'f2' in keys:
        return 'rename'
    return 'editing'


def record(topic, selection, memories=(), omitted=0):
    catalog = CATALOG[topic]
    return {'version': VERSION, 'grade': 'key_reference_and_episode_evidence',
        'topic': topic, 'selection': selection, 'scope': catalog['scope'],
        'source': SOURCES[catalog['source']],
        'recipes': [{'intent': intent, 'tool': {'action': 'key', 'keys': keys}}
                    for intent, keys in catalog['recipes']],
        'check': catalog.get('check', 'Recheck app/focus and visual effect.'),
        'memory': deepcopy(list(memories)), 'memory_omitted': omitted}


def policy():
    return {'version': VERSION, 'topics': list(CATALOG), 'max_key_edges': 32, 'max_memory_rows': 2,
            'catalog_sha256': hashlib.sha256(dumps({'catalog': CATALOG, 'sources': SOURCES}).encode()).hexdigest(),
            'selection': 'newest explicit concrete lookup or matching operation; otherwise omit; not visual detection',
            'memory': 'same episode journal; command return/image delta distinct from semantic success'}
