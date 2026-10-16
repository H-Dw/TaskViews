"""Intent-indexed key recipes. Display labels, X11 names and tool keys differ."""
from copy import deepcopy
import hashlib
import re

from .model import dumps

VERSION = 'mini_keyboard_v1'
SOURCES = {
    'document': 'https://help.gnome.org/evince/movingaround.html',
    'files': 'https://help.gnome.org/gnome-help/files-copy.html',
    'window': 'https://help.gnome.org/gnome-help/shell-windows-maximize.html',
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
        'recipes': [('cut selected files', ['ctrl', 'x']), ('paste into current folder', ['ctrl', 'v'])]},
    'window': {'scope': 'GNOME active window; maximize is a toggle', 'source': 'window',
        'recipes': [('toggle maximize', ['alt', 'f10'])]},
    'editing': {'scope': 'focused editable field; verify before confirm', 'source': 'backend',
        'recipes': [('select field text', ['ctrl', 'a']), ('confirm', ['return']), ('dismiss', ['escape'])]},
}
PATTERNS = (
    ('zoom', r'zoom|fit.page|缩放|放大|缩小'),
    ('page_navigation', r'page[ _-]?(down|up)|scroll|翻页|滚动'),
    ('file_transfer', r'cut|paste|move.*(file|invoice)|folder|剪切|粘贴|文件夹'),
    ('window', r'maximi[sz]e|window|窗口|最大化'),
)


def select_topic(proposals):
    """Only intent routing, never a claim that an app/focus was detected."""
    for text in proposals:
        if not isinstance(text, str):
            continue
        requests = re.findall(r'<key_lookup>([a-z_]+)</key_lookup>', text)
        if len(requests) == 1 and requests[0] in CATALOG:
            return requests[0], 'same_actor_explicit_lookup'
    for text in proposals:
        for topic, pattern in PATTERNS:
            if isinstance(text, str) and re.search(pattern, text, re.I):
                return topic, 'recent_model_intent_not_visual_detection'
    return 'editing', 'default_key_reference'


def key_topic(keys):
    if any(k in ('pagedown', 'pageup', 'page_down', 'page_up', 'home', 'end') for k in keys):
        return 'page_navigation'
    if 'ctrl' in keys and any(k in ('-', '+', 'minus') for k in keys):
        return 'zoom'
    if 'ctrl' in keys and any(k in ('x', 'v') for k in keys):
        return 'file_transfer'
    if 'alt' in keys and 'f10' in keys:
        return 'window'
    return 'editing'


def record(topic, selection, memories=(), omitted=0):
    catalog = CATALOG[topic]
    return {'version': VERSION, 'grade': 'key_reference_and_episode_evidence',
        'namespace': 'Copy exact keys tokens, independently of action enum spelling.',
        'topic': topic, 'selection': selection, 'scope': catalog['scope'],
        'source': SOURCES[catalog['source']],
        'recipes': [{'intent': intent, 'tool': {'action': 'key', 'keys': keys}}
                    for intent, keys in catalog['recipes']],
        'lookup': '<key_lookup>TOPIC</key_lookup> selects next view: ' + ','.join(CATALOG),
        'check': 'Recheck app/focus and visual effect.',
        'memory': deepcopy(list(memories)), 'memory_omitted': omitted}


def policy():
    return {'version': VERSION, 'topics': list(CATALOG), 'max_key_edges': 32, 'max_memory_rows': 2,
            'catalog_sha256': hashlib.sha256(dumps({'catalog': CATALOG, 'sources': SOURCES}).encode()).hexdigest(),
            'selection': 'explicit same-actor lookup, then recent intent; not visual detection',
            'memory': 'same episode journal; command return/image delta distinct from semantic success'}
