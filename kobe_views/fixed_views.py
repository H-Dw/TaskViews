"""Three fixed, source-bound projections; no graph or model invocation."""
from copy import deepcopy

from .model import dumps

PROFILE = 'mini_fixed_v1'
MAX_BYTES = 3000
VIEW_IDS = ('current', 'attempts', 'lessons')
SELECTORS = {'current': 'current_frame', 'attempts': 'recent_execution_edges',
             'lessons': 'recorded_errors_and_model_proposals'}


def profile_contract():
    return {'profile': PROFILE, 'view_ids': list(VIEW_IDS), 'selectors': dict(SELECTORS),
            'max_bytes': MAX_BYTES, 'recent_edges': 4, 'extra_role_requests': 0,
            'optional_error_policy': 'whole projection omission',
            'integrity_error_policy': 'pause before next actor', 'strict_native_input': True, 'focus_gate': False}


def materialize(*, episode_id, frame_id, current, attempts, lessons, totals, max_bytes):
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
    packet = {'profile': PROFILE, 'episode_id': episode_id, 'frame_id': frame_id,
              'views': {key: {'selector': SELECTORS[key], 'records': [], 'omitted_records':
                        0 if key == 'current' else totals[key]} for key in VIEW_IDS}}
    packet['views']['current']['records'] = [deepcopy(current)]
    if len(dumps(packet).encode()) > limit:
        return None
    selected = {key: set() for key in rows}

    def admit(key, index, ceiling):
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

    for key, quota in (('attempts', 1200), ('lessons', 1000)):
        for index in range(len(rows[key])):
            admit(key, index, quota)
    for key in rows:
        for index in range(len(rows[key])):
            if index not in selected[key]:
                admit(key, index, limit)
    return packet
