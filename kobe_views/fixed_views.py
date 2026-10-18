"""Bounded source-bound projections and intent-indexed keyboard reference."""
from copy import deepcopy

from .model import dumps
from .keyboard_view import policy as keyboard_policy
from .artifact_view import policy as artifact_policy

PROFILE = 'mini_fixed_v1'
REVISION = 'mini_artifact_protocol_v6'
MAX_BYTES = 3000
VIEW_IDS = ('current', 'keyboard', 'attempts', 'lessons')
SELECTORS = {'current': 'current_frame_and_artifact_checks', 'attempts': 'active_operations_with_followup_observations',
             'lessons': 'unresolved_checks_errors_and_unverified_reviews',
             'keyboard': 'intent_key_lookup_and_episode_keyboard_memory'}


def profile_contract():
    return {'profile': PROFILE, 'implementation_revision': REVISION,
            'frame_input': 'mandatory current-only coordinate units and result-verification guidance',
            'error_selection': 'nonempty error or explicit failed status/nonzero returncode',
            'repeat_feedback': 'literal recent journal evidence, independent of controls',
            'interaction': 'mini_interaction_v1; reject known silent key aliases before dispatch; no rewrite',
            'keyboard': keyboard_policy(),
            'artifact': artifact_policy(),
            'packing_priority': 'current/checks/full review protocol; active operation+followup; unresolved error/review; relevant keyboard; other history; generic reminders',
            'packet_metadata': 'selectors/control source URLs in profile; current geometry in native frame contract; image hash via current ref',
            'view_ids': list(VIEW_IDS), 'selectors': dict(SELECTORS),
            'max_bytes': MAX_BYTES, 'recent_edges': 4, 'extra_role_requests': 0,
            'optional_error_policy': 'whole projection omission',
            'integrity_error_policy': 'pause before next actor', 'strict_native_input': True, 'focus_gate': False}


def materialize(*, episode_id, frame_id, current, attempts, lessons, totals, max_bytes, controls=None, keyboard=None, sources=None):
    """Select whole original projections; never truncate a value to fit.

    Input lists arrive newest first. Critical records precede optional reminders
    and key references. Event hashes live once in the selected source table;
    episode+seq resolves the full original UUID from the immutable journal.
    Counts include older eligible records outside the bounded retrieval window.
    """
    limit = min(MAX_BYTES, max_bytes)
    if type(limit) is not int or limit < 0:
        raise ValueError('Fixed view budget must be a nonnegative integer')
    rows = {'attempts': attempts, 'lessons': lessons}
    if any(type(totals.get(key)) is not int or totals[key] < len(rows[key]) for key in rows):
        raise ValueError('Fixed view eligible counts must include all candidates')
    view_ids = VIEW_IDS if controls is None else tuple(k for k in VIEW_IDS if k != 'keyboard')
    packet = {'profile': PROFILE, 'episode_id': episode_id, 'frame_id': frame_id,
              'views': {key: {'records': [], 'omitted_records':
                        0 if key in ('current', 'keyboard') else totals[key]} for key in view_ids}}
    packet['views']['current']['records'] = [deepcopy(current)]
    selected = {key: set() for key in rows}
    # Reserve mandatory unknown state before admitting any optional extension.
    for index, row in enumerate(lessons):
        if row.get('grade') == 'artifact_verification_state':
            packet['views']['lessons']['records'].append(deepcopy(row))
            packet['views']['lessons']['omitted_records'] -= 1
            selected['lessons'].add(index)
    lookup = packet['views']['current']['records'][0].pop('keyboard_lookup', None)
    optional_current = {}
    for key in ('recent_repetition', 'interaction_contract'):
        literal = packet['views']['current']['records'][0]
        if key in literal:
            optional_current[key] = literal.pop(key)
            literal[key + '_omitted'] = True
    if sources is not None:
        packet['sources'] = {}

    def bind_sources(candidate):
        if sources is None:
            return
        needed = set()
        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ('ref', 'before', 'after', 'current_ref', 'review_ref') and type(child) is int:
                        needed.add(str(child))
                    elif key not in ('sources', 'tool'):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(candidate)
        if not needed <= sources.keys():
            raise ValueError('Selected Mini record has an unresolved source reference')
        # episode_id + immutable journal seq identify the event. Its original
        # UUID is inside the hashed payload; repeating it here wastes 40 bytes.
        candidate['sources'] = {key: {field: sources[key][field] for field in ('sha256', 'kind')}
                                for key in sorted(needed, key=int)}

    bind_sources(packet)
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
    if len(dumps(packet).encode()) > limit:
        return None

    def admit(key, index, ceiling):
        if index in selected[key]:
            return True
        candidate = deepcopy(packet)
        view = candidate['views'][key]
        view['records'].append(deepcopy(rows[key][index]))
        view['records'].sort(key=lambda row: row.get('seq', row.get('ref', 0)))
        view['omitted_records'] -= 1
        bind_sources(candidate)
        if (len(dumps(view['records']).encode()) > ceiling
                or len(dumps(candidate).encode()) > limit):
            return False
        packet.clear()
        packet.update(candidate)
        selected[key].add(index)
        return True

    # A meaningful operation and unresolved verification precede key references.
    if attempts:
        admit('attempts', 0, limit)
    for index, row in enumerate(lessons):
        if row.get('grade') == 'execution_error_record' and admit('lessons', index, limit):
            break
    for index, row in enumerate(lessons):
        if row.get('grade') == 'model_artifact_review':
            admit('lessons', index, limit)
            break
    if keyboard is not None and 'keyboard' in packet['views']:
        candidate = deepcopy(keyboard)
        proposed = deepcopy(packet)
        view = proposed['views']['keyboard']
        view['records'] = [candidate]
        bind_sources(proposed)
        while len(dumps(proposed).encode()) > limit and candidate['memory']:
            candidate['memory'].pop()
            candidate['memory_omitted'] += 1
            bind_sources(proposed)
        if len(dumps(proposed).encode()) <= limit:
            packet.clear()
            packet.update(proposed)
        else:
            packet['views']['keyboard']['omitted_records'] = 1
    # Only literal repetition evidence precedes other journal records. Generic
    # interaction reminders must not evict a useful operation or review.
    def admit_current(key, value):
        proposed = deepcopy(packet)
        literal = proposed['views']['current']['records'][0]
        literal.pop(key + '_omitted')
        literal[key] = deepcopy(value)
        bind_sources(proposed)
        if len(dumps(proposed).encode()) <= limit:
            packet.clear()
            packet.update(proposed)
    if 'recent_repetition' in optional_current:
        admit_current('recent_repetition', optional_current['recent_repetition'])
    for key, quota in (('attempts', 1200), ('lessons', 1000)):
        for index in range(len(rows[key])):
            admit(key, index, quota)
    for key in rows:
        for index in range(len(rows[key])):
            if index not in selected[key]:
                admit(key, index, limit)
    if 'interaction_contract' in optional_current:
        admit_current('interaction_contract', optional_current['interaction_contract'])
    # Catalog discovery is the lowest priority: it must never evict journal
    # evidence, key memory or model intent. Omission is recorded by the caller.
    if lookup is not None:
        proposed = deepcopy(packet)
        proposed['views']['current']['records'][0]['keyboard_lookup'] = deepcopy(lookup)
        if len(dumps(proposed).encode()) <= limit:
            packet = proposed
    return packet
