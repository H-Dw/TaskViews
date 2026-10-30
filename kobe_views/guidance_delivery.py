"""Separate opt-in packer: atomic guidance groups after critical evidence.

Old packers are intentionally untouched. No prefix slices, fabricated padding,
or hidden budget increase. Flat and linked use the same linked-cost admission.
"""
from copy import deepcopy

from . import mini_graph as graph
from .mini_delivery import compact
from .model import dumps
from .keyboard_guidance import SOURCE_ENCODING, model_card
from .guidance_groups import whole
from .artifact_view import COMPACT_REVIEW_SCHEMA, REVIEW_SCHEMA
from .review_presentation import schema as review_schema


def materialize(*, episode_id, index, instruction, graph_mode, packing, selection,
                frame_id, current, attempts, lessons, totals, max_bytes, sources,
                keyboard=None, review_policy=None, finishing=False):
    limit = min(graph.MAX_BYTES, max_bytes)
    if type(limit) is not int or limit < 0:
        raise ValueError('Guidance budget must be a nonnegative integer')
    rows = {'attempts': attempts, 'lessons': lessons}
    if any(type(totals.get(k)) is not int or totals[k] < len(rows[k]) for k in rows):
        raise ValueError('Guidance eligible counts must include all candidates')
    raw = {'profile': graph.PROFILE, 'episode_id': episode_id, 'frame_id': frame_id,
           'sources': sources, 'views': {k: {'records': [], 'omitted_records': totals.get(k, 0)} for k in graph.VIEW_IDS}}
    raw['views']['keyboard']['omitted_records'] = len(selection['groups'])
    literal = deepcopy(current)
    if review_policy:
        # All checks remain unknown; the original per-check payload stays in
        # projection/audit. The validator never reads this compact display.
        literal['artifact']['verification'] = 'all_checks_unknown'
        if 'completion' in literal:
            # Strict terminal format and held-key state are already explicit.
            # Do not repeat the generic save/check checklist on every late turn.
            literal['completion'] = {'remaining_decisions': literal['completion']['remaining_decisions']}
    missing = sorted({need for gap in selection.get('coverage_gaps', []) for need in gap['missing']})
    first = next(iter(selection['groups']), None)
    literal['guidance_status'] = {'card': 'omitted_budget' if first else 'no_match',
        'coverage': 'gap' if missing else 'matched' if first else 'no_match'}
    if missing:
        literal['guidance_status']['missing'] = missing
    raw['views']['current']['records'] = [literal]
    lookup = literal.pop('keyboard_lookup', None)
    optional = {k: literal.pop(k) for k in ('action_conditions', 'reading_progress',
                'recent_repetition', 'interaction_contract') if k in literal}
    if not review_policy:
        for k in optional:
            literal[k + '_omitted'] = True
    selected = {k: set() for k in rows}
    for i, row in enumerate(lessons):
        if row.get('grade') == 'artifact_verification_state':
            # Same unknown checks already live in current.artifact. Preserve
            # the facet and source without repeating their complete payload.
            shared = ({'grade': row['grade'], 'current_ref': row['current_ref'],
                       'state': 'see_current_artifact'} if review_policy else deepcopy(row))
            raw['views']['lessons']['records'].append(shared)
            raw['views']['lessons']['omitted_records'] -= 1
            selected['lessons'].add(i)

    def render(value, *, cost=False):
        if cost and review_policy:
            value = deepcopy(value)
            value['views']['current']['records'][0]['artifact']['review_schema'] = review_schema(
                review_policy, finishing=finishing, cost=True)
        elif cost and value['views']['current']['records'][0].get('artifact', {}).get('review_schema') == COMPACT_REVIEW_SCHEMA:
            value = deepcopy(value)
            value['views']['current']['records'][0]['artifact']['review_schema'] = REVIEW_SCHEMA
        if graph_mode == 'legacy':
            refs = graph.references(value['views'])
            if not {str(r) for r in refs} <= sources.keys():
                raise graph.GraphIntegrityError('Guidance contains an unresolved event reference')
            out = deepcopy(value)
            out['source_encoding'] = SOURCE_ENCODING
            out['sources'] = {str(r): {'kind': sources[str(r)]['kind']} for r in sorted(refs)}
            return out
        packet = graph.normalize(value, index, instruction)
        out = compact(packet) if packing == graph.DELIVERY_PACKING else packet
        # normalize has already checked all original hashes and endpoints.
        # Full hashes/identities remain in the original journal and graph audit.
        out['source_encoding'] = SOURCE_ENCODING
        out['sources'] = {seq: [source['kind']] if packing == graph.DELIVERY_PACKING else {'kind': source['kind']}
                          for seq, source in packet['sources'].items()}
        return out

    def accept(candidate):
        if len(dumps(render(candidate, cost=True)).encode()) > limit:
            return False
        raw.clear()
        raw.update(candidate)
        return True

    if not accept(deepcopy(raw)):
        return None

    def admit(key, i):
        if i in selected[key]:
            return True
        candidate = deepcopy(raw)
        candidate['views'][key]['records'].append(deepcopy(rows[key][i]))
        candidate['views'][key]['records'].sort(key=lambda r: r.get('seq', r.get('ref', 0)))
        candidate['views'][key]['omitted_records'] -= 1
        if not accept(candidate):
            return False
        selected[key].add(i)
        return True

    # Preserve priority and whole factual payloads. Do not use guide space to
    # truncate an error or weaken the original verification protocol.
    if attempts:
        if not admit('attempts', 0) and review_policy:
            return None
    for grade in (('execution_error_record',) if review_policy else ('execution_error_record', 'model_artifact_review')):
        for i, row in enumerate(lessons):
            if row.get('grade') == grade:
                fitted = admit('lessons', i)
                if not fitted and review_policy and grade == 'execution_error_record':
                    return None
                if fitted or grade == 'model_artifact_review':
                    break
    def admit_current(key, value):
        candidate = deepcopy(raw)
        body = candidate['views']['current']['records'][0]
        body.pop(key + '_omitted', None)
        body[key] = deepcopy(value)
        return accept(candidate)

    # Held keys constrain the next dispatched action regardless of the card.
    # Other conditions follow a complete card and one whole reading claim.
    conditions = optional.get('action_conditions', [])
    admitted_conditions = []
    for condition in conditions:
        if condition['kind'] == 'held_modifiers' and admit_current('action_conditions', [condition]):
            admitted_conditions.append(condition)

    # A current explicit strategy has just requested operation knowledge.
    # Admit its recalled attempt/failed preconditions before optional recipes;
    # otherwise retrieval may succeed locally while the actor never sees it.
    if literal.get('strategy'):
        for i, row in enumerate(attempts):
            if row.get('recall'):
                admit('attempts', i)

    # One current-stage card; do not substitute a cheaper, irrelevant candidate
    # if the required group cannot fit. Candidates and rule explanations stay local.
    if first is not None:
        candidate = deepcopy(raw)
        candidate['views']['keyboard']['records'] = [model_card(whole(first['record']))]
        candidate['views']['keyboard']['omitted_records'] -= 1
        candidate['views']['current']['records'][0]['guidance_status']['card'] = 'included'
        accept(candidate)  # Exact parameters, conditions, followups and checks stay atomic.

    if 'reading_progress' in optional:
        if review_policy:
            # Reports live once in Lessons, with Current pointing to the
            # admitted sources only. Whole claims from different observations
            # compete before second claims from the same observation.
            for i, row in enumerate(lessons):
                if row.get('grade') != 'model_reading_proposal':
                    continue
                candidate = deepcopy(raw)
                candidate['views']['lessons']['records'].append(deepcopy(row))
                candidate['views']['lessons']['omitted_records'] -= 1
                body = candidate['views']['current']['records'][0]
                refs = body.setdefault('reading_progress', {'reports': []})['reports']
                if {'ref': row['ref']} not in refs:
                    refs.append({'ref': row['ref']})
                if accept(candidate):
                    selected['lessons'].add(i)
                    break  # First claim before pending effects; remainder below.
        else:
            admit_current('reading_progress', optional['reading_progress'])
    for condition in conditions:
        if condition in admitted_conditions:
            continue
        # Phase card already explains the pending action. Keep its short
        # dispatched value/phase + sources, not a second copy of its advice.
        value = deepcopy(condition)
        cards = raw['views']['keyboard']['records']
        if value.get('kind') == 'zoom_pending' and cards and cards[0]['guide_id'].split(':')[0] in (
                'view.zoom_confirm', 'view.zoom_check'):
            value.pop('constraint', None)
            if {e['ref'] for e in value.get('evidence', [])} <= {e['ref'] for e in cards[0]['evidence']}:
                value['evidence'] = 'see_current_card'
        if admit_current('action_conditions', [*admitted_conditions, value]):
            admitted_conditions.append(value)
    if not conditions and 'recent_repetition' in optional:
        admit_current('recent_repetition', optional['recent_repetition'])
    if review_policy:
        # Reusable source-diverse reports outrank ordinary history. Keep the
        # actual claims atomic, including source, expiry and unknown status.
        for i, row in enumerate(lessons):
            if row.get('grade') != 'model_reading_proposal' or i in selected['lessons']:
                continue
            candidate = deepcopy(raw)
            candidate['views']['lessons']['records'].append(deepcopy(row))
            candidate['views']['lessons']['omitted_records'] -= 1
            refs = candidate['views']['current']['records'][0].setdefault('reading_progress', {'reports': []})['reports']
            if {'ref': row['ref']} not in refs:
                refs.append({'ref': row['ref']})
            if accept(candidate):
                selected['lessons'].add(i)
        # A bounded lexical retrieval complements the mandatory latest action.
        # It is a past attempt with expired coordinates, not an executable plan.
        for i, row in enumerate(attempts):
            if row.get('recall'):
                admit('attempts', i)
    if review_policy and finishing:
        for i, row in enumerate(lessons):
            if row.get('grade') == 'model_artifact_review':
                admit('lessons', i)
                break
    if not review_policy:
        for key in rows:
            for i in range(len(rows[key])):
                admit(key, i)
    # Minimal path does not fill spare bytes with broad catalogs, repeated
    # intent prose or ordinary history. Explicit omissions remain auditable.
    # An unmatched task-specific action is valid. Do not turn an empty result
    # into a broad catalog or a request to look something up before acting.
    if lookup is not None and first is not None and (not review_policy or missing):
        admit_current('keyboard_lookup', lookup)
    if not review_policy and 'interaction_contract' in optional:
        admit_current('interaction_contract', optional['interaction_contract'])
    packet = render(raw)
    if graph_mode == 'flat':
        packet['mode'], packet['links'] = 'flat', []
    return packet
