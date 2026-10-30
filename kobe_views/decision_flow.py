"""Single-actor evidence use and bounded, public operation-knowledge requests."""
import re

from .guidance_semantics import operations
from .operation_support import READ_TTL, intent_excerpt, public

VERSION = 'source_linked_five_stage_v1'
TOOL = 'keyboard_lookup'
MAX_LOOKUPS = 1
MAX_QUERY_BYTES = 480
PROMPT = (
    'Use one decision flow: (1) Plan from the goal, Current image/state and Lessons; reports are unverified. '
    '(2) Check Attempts for reusable steps, results and failed conditions; re-ground old coordinates. '
    '(3) Keyboard is optional: reuse known bindings; fill only a concrete operation-knowledge gap. If needed, call keyboard_lookup alone '
    'and wait for its result before GUI actions; no match means decide directly. '
    '(4) Ground exact native parameters in the Current image, including app, scope and focus. '
    '(5) Dispatch validated native actions; inspect their feedback before continuing. '
    'Readable -> read; otherwise adjust once/check. Reuse unchanged-content reports; re-read missing/conflicting/expired facts. '
    'Do not narrate five reasoning sections. State only brief useful public findings. '
    'source_ref resolves local guidance audit; enabled directories do not confirm focus. '
    'Prefetched cards are references, not a route; use them only if they fit the chosen strategy.')


def policy():
    return {'version': VERSION, 'stages': ['route', 'attempt_reuse', 'optional_knowledge', 'ground', 'feedback'],
            'actor': 'same_native_actor', 'lookup_tool': TOOL, 'max_lookups_per_predict': MAX_LOOKUPS,
            'max_query_utf8_bytes': MAX_QUERY_BYTES, 'lookup_budget': 'shared_actor_deadline_and_output',
            'dispatch': 'lookup_and_gui_are_separate', 'empty_keyboard': 'native_actor_decides',
            'prefetched_cards': 'optional_not_a_route_current_query_overrides',
            'knowledge_gap_usage': 'operation_knowledge_only_v2',
            'attempt_retrieval': 'same_task_public_object_operation_overlap_v1'}


def tool_schema():
    return {'type': 'function', 'function': {'name': TOOL,
        'description': ('Optional local operation reference lookup after choosing a strategy. Use only for a missing '
            'binding or procedure, never to ask for a task solution. Call alone before computer_use; at most once '
            'per decision. No match is allowed; then act from the current image. No GUI action is executed.'),
        'parameters': {'type': 'object', 'properties': {
            'intent': {'type': 'string', 'minLength': 1, 'maxLength': 160,
                       'description': 'Brief intended operation, target app/object and stage; no private reasoning.'},
            'missing_knowledge': {'type': 'string', 'minLength': 1, 'maxLength': 120,
                                 'description': 'The specific operation binding or procedure needed; state required followups. Task/result verification belongs to Current and execution feedback.'}},
            'required': ['intent', 'missing_knowledge'], 'additionalProperties': False}}}


def validate_query(value):
    if (not isinstance(value, dict) or set(value) != {'intent', 'missing_knowledge'}
            or any(not isinstance(value[k], str) or not value[k].strip() or len(value[k]) > limit
                   or any(c in value[k] for c in '<>\x00')
                   for k, limit in [('intent', 160), ('missing_knowledge', 120)])
            or sum(len(v.encode('utf-8')) for v in value.values()) > MAX_QUERY_BYTES):
        raise ValueError('keyboard_lookup needs a brief intent and a specific missing_knowledge; no tags or extra fields')
    return dict(value)


def attempt_recall(rows, instruction, proposals, step):
    """One relevant dispatched attempt, including errors; never a success path.

    Match operation AND non-generic object terms, not just a repeated verb.
    Complete sources must exist. No cross-task or long-term memory is searched.
    """
    boundary = max((n for n, e, _ in rows if e.get('kind') == 'task_input'
                    and e.get('instruction') != instruction), default=0)
    rows = [r for r in rows if r[0] > boundary]
    fresh = sorted((p for p in proposals if p[0] > boundary and 0 <= step - p[2] <= 2), reverse=True)
    if not fresh or not fresh[0][1]:
        return None
    qref, query, _ = fresh[0]
    query_ops = operations(query)
    stop = set(('the this that with from into then again please would should want need will let open switch window '
                'application app document file folder read review check compare back return copy cut paste move '
                'select selected selection click visible current menu control text content use').split())

    def terms(text):
        words = {w.casefold() for w in re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{2,}', text)} - stop
        # Bigrams support ordinary Chinese object names without task-specific rules.
        words |= {s[i:i+2] for s in re.findall(r'[\u4e00-\u9fff]+', text) for i in range(len(s)-1)} - {
            '复制', '剪切', '粘贴', '打开', '返回', '文本', '文字', '当前', '窗口', '文件', '目录', '再次', '需要'}
        return words

    observations = {e.get('id'): n for n, e, _ in rows if e.get('kind') == 'observation'}
    decisions = {e.get('id'): (n, e) for n, e, _ in rows if e.get('kind') == 'decision'
                 and e.get('instruction') == instruction}
    found = []
    for seq, event, _ in rows:
        if (seq >= qref or event.get('kind') != 'transition' or event.get('instruction') != instruction
                or event.get('dispatch_observed') is not True or event.get('command_alignment') != 'matched'
                or event.get('gaps') or not event.get('controller_receipts')
                or not 0 <= step - event.get('step', -99) <= READ_TTL
                or any(event.get(k) not in observations for k in ('source', 'target'))):
            continue
        if (event.get('tool') or {}).get('arguments', {}).get('action') in ('screenshot', 'wait'):
            continue
        issuer = decisions.get(event.get('decision_id'))
        if not issuer or not observations.get(issuer[1].get('source'), seq) < issuer[0] < seq:
            continue
        text = intent_excerpt(public(issuer[1]))
        overlap = terms(query) & terms(text)
        if query_ops & operations(text) and overlap:
            found.append((len(overlap), seq, {'ref': seq, 'query_ref': qref, 'intent_ref': issuer[0],
                'text': text, 'matched_terms': sorted(overlap), 'basis': 'public_object_operation_match_not_success'}))
    return max(found, key=lambda x: x[:2])[2] if found else None
