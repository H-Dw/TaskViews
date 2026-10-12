"""Source-backed keyboard knowledge plus fallible, frame-bound control notes.

No desktop probe, model call, action substitution or focus/success gate lives here.
"""
import hashlib
import json

from .model import dumps

VERSION = 'mini_controls_v1'
SOURCES = {
    'windows': 'https://help.gnome.org/gnome-help/shell-windows-maximize.html',
    'navigation': 'https://help.gnome.org/gnome-help/keyboard-nav.html',
    'switch': 'https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html',
    'resize': 'https://help.gnome.org/gnome-help/shell-windows-states.html',
}
BINDINGS = [
    {'id': 'window.switch', 'keys': ['win', 'tab'], 'source': 'switch'},
    {'id': 'window.maximize', 'keys': ['alt', 'f10'], 'toggle': True, 'source': 'windows'},
    {'id': 'window.move', 'keys': ['alt', 'f7'], 'source': 'resize'},
    {'id': 'window.resize', 'keys': ['alt', 'f8'], 'source': 'resize'},
    {'id': 'menu.open', 'keys': ['f10'], 'source': 'navigation'},
    {'id': 'control.next', 'keys': ['tab'], 'source': 'navigation'},
    {'id': 'control.activate', 'keys': ['space'], 'source': 'navigation'},
    {'id': 'popup.dismiss', 'keys': ['esc'], 'source': 'navigation'},
]
GUIDANCE = (
    'Read target/enabled/focus on the current image. Use matching bindings for window/menu recovery instead '
    'of ineffective clicks; defaults need confirmation. Read menu accelerators on screen. Establish uncertain '
    'focus and observe before typing/submit; verify next image. Optional same-response <controls> JSON: '
    'items(max4){label,role(button/menu/input/window/other),shortcut(string/null),enabled,focused '
    '(observed/absent/unknown)},selected_binding(id/null),expected(text). </controls> '
    'Notes are proposals, returned is not success. Move/resize: arrows then Return confirm/Esc cancel. '
    'win means GNOME Super. Use native tools.'
)


def policy():
    return {'version': VERSION, 'catalog_sha256': hashlib.sha256(dumps(
                {'bindings': BINDINGS, 'sources': SOURCES, 'guidance': GUIDANCE}).encode()).hexdigest(),
            'sources': dict(SOURCES), 'extra_role_requests': 0, 'focus_gate': False,
            'notes_policy': 'same actor, whole optional proposal, reobserve every frame',
            'max_packet_bytes': 3000}


def parse_note(text):
    """Optional annotation failure never rejects an otherwise legal native action."""
    if not isinstance(text, str) or text.count('<controls>') != 1 or text.count('</controls>') != 1:
        return None
    raw = text.split('<controls>', 1)[1].split('</controls>', 1)[0]
    if len(raw.encode()) > 900:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if (not isinstance(value, dict) or set(value) != {'items', 'selected_binding', 'expected'}
            or not isinstance(value['items'], list) or len(value['items']) > 4
            or value['selected_binding'] not in [None, *(b['id'] for b in BINDINGS)]
            or not isinstance(value['expected'], str) or len(value['expected'].encode()) > 200):
        return None
    for row in value['items']:
        if (not isinstance(row, dict) or set(row) != {'label', 'role', 'shortcut', 'enabled', 'focused'}
                or not isinstance(row['label'], str) or not 1 <= len(row['label'].encode()) <= 100
                or row['role'] not in ('button', 'menu', 'input', 'window', 'other')
                or (row['shortcut'] is not None and (not isinstance(row['shortcut'], str)
                    or len(row['shortcut'].encode()) > 40))
                or row['enabled'] not in ('observed', 'absent', 'unknown')
                or row['focused'] not in ('observed', 'absent', 'unknown')):
            return None
    return {'note': value, 'note_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'grade': 'model_proposal', 'current_truth': False}


def record(frame_id, previous=None):
    value = {'version': VERSION, 'frame_id': frame_id, 'grade': 'documented_defaults',
             'scope': 'GNOME; verify applicability in current screenshot',
             'sources': SOURCES, 'bindings': BINDINGS, 'guidance': GUIDANCE,
             'current_focus': 'unknown', 'accessibility_tree': 'not_collected',
             'previous_note': previous}
    return value


def matched_bindings(arguments):
    """Log exact native key use, without changing parameters or choosing a key."""
    return [b['id'] for action in arguments if action.get('action') == 'key'
            for b in BINDINGS if action.get('keys') == b['keys']]
