"""Bounded source-bound projections and intent-indexed keyboard reference."""
from copy import deepcopy

from .model import dumps
from .keyboard_view import policy as keyboard_policy

PROFILE = 'mini_fixed_v1'
REVISION = 'mini_keyboard_memory_v3'
MAX_BYTES = 3000
VIEW_IDS = ('current', 'keyboard', 'attempts', 'lessons')
SELECTORS = {'current': 'current_frame', 'attempts': 'recent_execution_edges',
             'lessons': 'recorded_errors_and_model_proposals',
             'keyboard': 'intent_key_lookup_and_episode_keyboard_memory'}


def profile_contract():
    return {'profile': PROFILE, 'implementation_revision': REVISION,
            'frame_input': 'mandatory current-only coordinate units and result-verification guidance',
            'error_selection': 'nonempty error or explicit failed status/nonzero returncode',
            'repeat_feedback': 'literal recent journal evidence, independent of controls',
            'interaction': 'mini_interaction_v1; reject known silent key aliases before dispatch; no rewrite',
            'keyboard': keyboard_policy(),
            'packing_priority': 'current; newest fitting execution error; keyboard; attempts/proposals',
            'view_ids': list(VIEW_IDS), 'selectors': dict(SELECTORS),
            'max_bytes': MAX_BYTES, 'recent_edges': 4, 'extra_role_requests': 0,
            'optional_error_policy': 'whole projection omission',
            'integrity_error_policy': 'pause before next actor', 'strict_native_input': True, 'focus_gate': False}


def materialize(*, episode_id, frame_id, current, attempts, lessons, totals, max_bytes, controls=None, keyboard=None):
    """Select whole original projections; never truncate a value to fit.

    Input lists arrive newest first with their original event seq. Small per-view
    quotas prevent one view from swallowing the other; remaining room is shared.
    Counts include older eligible records outside the fixed retrieval window.
    """
    limit = min(MAX_BYTES, max_bytes)
    if type(limit) is not int or limit < 0:
        raise ValueError('Fixed view budget must be a nonnegative integer')
    rows = {'attempts': attempts, 'lessons': lessons}
    if any(type(totals.get(key)) is not int or totals[key] < len(rows[key]) for key in rows):
        raise ValueError('Fixed view eligible counts must include all candidates')
    view_ids = VIEW_IDS if keyboard is not None else tuple(k for k in VIEW_IDS if k != 'keyboard')
    packet = {'profile': PROFILE, 'episode_id': episode_id, 'frame_id': frame_id,
              'views': {key: {'selector': SELECTORS[key], 'records': [], 'omitted_records':
                        0 if key in ('current', 'keyboard') else totals[key]} for key in view_ids}}
    packet['views']['current']['records'] = [deepcopy(current)]
    if controls is not None:
        packet['extensions'] = {'controls': controls['version']}
        packet['views']['controls'] = {'selector': 'documented_bindings_and_same_actor_notes',
                                      'records': [deepcopy(controls)], 'omitted_records': 0}
        if len(dumps(packet).encode()) > limit and controls.get('previous_note') is not None:
            previous = packet['views']['controls']['records'][0]['previous_note']
            packet['views']['controls']['records'][0]['previous_note'] = {
                'whole_note_omitted': True, 'source_event_id': previous['source_event_id'],
                'source_sha256': previous['source_sha256'], 'note_sha256': previous['note_sha256'],
                'grade': 'model_proposal', 'reobserve_required': True}
        # The new independently declared guidance is either whole or explicitly absent.
        # Historical attempts/lessons cannot evict it. No budget or M0 default changes.
    if len(dumps(packet).encode()) > limit and 'interaction_contract' in packet['views']['current']['records'][0]:
        literal = packet['views']['current']['records'][0]
        del literal['interaction_contract']
        literal['interaction_contract_omitted'] = True
    if len(dumps(packet).encode()) > limit and 'recent_repetition' in packet['views']['current']['records'][0]:
        literal = packet['views']['current']['records'][0]
        del literal['recent_repetition']
        literal['recent_repetition_omitted'] = True
    if len(dumps(packet).encode()) > limit:
        return None
    selected = {key: set() for key in rows}

    def admit(key, index, ceiling):
        if index in selected[key]:
            return True
        candidate = deepcopy(packet)
        view = candidate['views'][key]
        view['records'].append(deepcopy(rows[key][index]))
        view['records'].sort(key=lambda row: row['seq'])
        view['omitted_records'] -= 1
        if (len(dumps(view['records']).encode()) > ceiling
                or len(dumps(candidate).encode()) > limit):
            return False
        packet.clear()
        packet.update(candidate)
        selected[key].add(index)
        return True

    # An actual failure must not be displaced by an attractive key reference
    # or a duplicate attempt. Keep at least the newest fitting error whole.
    for index, row in enumerate(lessons):
        if row.get('grade') == 'execution_error_record' and admit('lessons', index, limit):
            break
    if keyboard is not None:
        candidate = deepcopy(keyboard)
        view = packet['views']['keyboard']
        view['records'] = [candidate]
        while len(dumps(packet).encode()) > limit and candidate['memory']:
            candidate['memory'].pop()
            candidate['memory_omitted'] += 1
        if len(dumps(packet).encode()) > limit:
            view['records'] = []
            view['omitted_records'] = 1
    for key, quota in (('attempts', 1200), ('lessons', 1000)):
        for index in range(len(rows[key])):
            admit(key, index, quota)
    for key in rows:
        for index in range(len(rows[key])):
            if index not in selected[key]:
                admit(key, index, limit)
    return packet
