"""Bounded, source-checked attempt references, never executable saved routes.

Both operation and navigation retrieval use this gate. Public object/control
descriptions are scope hints, not confirmation of a window, focus or effect.
"""
import re

from .guidance_semantics import analyze, immediate_actions, operations
from .keyboard_view import DATA
from .operation_support import INTENT, NAVIGATION, READ_TTL, intent_excerpt, keys, public

VERSION = 'eligible_attempt_retrieval_v2'
STOP = set(('the this that with from into then again please would should want need will let open switch window '
            'application app document file folder read review check compare back return copy cut paste move '
            'select selected selection click visible current menu control text content use').split())
ZOOM = re.compile(r'\b(?:zoom|scale)\b|缩放|比例', re.I)
REPEAT = re.compile(r'\b(?:again|reopen|back to|return to|switch back)\b|重新打开|再次打开|切回|返回', re.I)
FILES = re.compile(r'(?<![\w.])(?:[\w~.-]+[/\\])*[\w-]+\.[a-zA-Z]{2,8}\b')
QUOTED = re.compile(r'["“`]([^"”`\n]+)["”`]')
CONTROLS = re.compile(r'\b((?:[\w-]+\s+){1,3})(?:field|box|control)\b', re.I)


def policy():
    return {'version': VERSION, 'sources': ['operation_overlap', 'navigation_repeat'],
            'query_ttl': 2, 'attempt_ttl': READ_TTL, 'scope': 'same_task_episode_bounded_journal',
            'filters': ['complete_sources', 'public_object', 'phase', 'later_parameters'],
            'packing': 'after_critical_evidence_before_optional_keyboard',
            'parameters': 'historical_only_rebuild_current', 'effect': 'unknown'}


def terms(text):
    words = {w.casefold() for w in re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{2,}', text)} - STOP
    words |= {s[i:i+2] for s in re.findall(r'[\u4e00-\u9fff]+', text) for i in range(len(s)-1)} - {
        '复制', '剪切', '粘贴', '打开', '返回', '文本', '文字', '当前', '窗口', '文件', '目录', '再次', '需要'}
    return words


def operation_text(text):
    # Prefer an explicit public action over an earlier "I can read ..." report.
    sentences = re.split(r'\n+|(?<=[.!?。！？])\s+', text or '')
    intended = [s for s in sentences if INTENT.search(s) and operations(s)]
    return intent_excerpt(' '.join(intended)) if intended else intent_excerpt(text)


def identifiers(text):
    # Numeric values and generic control names are not object identities.
    apps = {key for key, aliases in DATA['task_aliases'].items() if key.startswith('app.')
            and any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text, re.I) for alias in aliases)}
    controls = {' '.join(w for w in words.casefold().split() if w not in STOP)
                for words in CONTROLS.findall(text)} - {''}
    return {'apps': apps, 'controls': controls, 'files': set(FILES.findall(text)), 'quoted': {
        s.casefold() for s in QUOTED.findall(text) if re.search(r'[a-zA-Z\u4e00-\u9fff]', s)}}


def object_conflict(left, right):
    a, b = identifiers(left), identifiers(right)
    return any(a[k] and b[k] and a[k].isdisjoint(b[k]) for k in a)


def dispatch(event):
    return (event.get('kind') == 'transition' and event.get('dispatch_observed') is True
            and event.get('command_alignment') == 'matched' and not event.get('gaps')
            and bool(event.get('controller_receipts'))
            and all(isinstance(r, dict) and isinstance(r.get('result'), dict)
                    for r in event['controller_receipts']))


def failed(event):
    return bool(event.get('error')) or any(r['result'].get('success') is False
        or r['result'].get('error') or r['result'].get('returncode', 0) != 0
        or r['result'].get('status') in ('error', 'failed', 'failure')
        for r in event['controller_receipts'])


def family(text, args):
    if args.get('action') == 'key' and keys(args) in (('c', 'ctrl'), ('ctrl', 'x'), ('ctrl', 'v')):
        return 'clipboard'
    if ZOOM.search(text):
        return 'zoom'
    return 'other'


def phase(text, args=None):
    args = args or {}
    if args.get('action') == 'type':
        return 'input'
    if args.get('action') == 'key' and keys(args) in (('enter',), ('return',)):
        return 'confirm'
    ops = immediate_actions(analyze(text))
    if 'confirm' in ops or re.search(r'\b(?:press|hit)\s+(?:enter|return)\b|按(?:下)?回车', text, re.I):
        return 'confirm'
    if ops & {'edit', 'zoom_value'} or ZOOM.search(text) and re.search(r'\b(?:type|enter)\b|输入', text, re.I):
        return 'input'
    if ops & {'reading', 'readability'} and not ops & {'zoom_in', 'zoom_out', 'maximize'}:
        return 'inspect'
    return 'operation'


def evidence_reason(seq, event, observations, decisions, episode):
    if not dispatch(event):
        return 'incomplete_dispatch'
    issuer = decisions.get(event.get('decision_id'))
    before, after = observations.get(event.get('source')), observations.get(event.get('target'))
    origin = observations.get(issuer[1].get('source')) if issuer else None
    if not issuer or not before or not after or not origin:
        return 'missing_sources'
    if not origin[0] < issuer[0] < after[0] < seq or not before[0] < after[0]:
        return 'source_order'
    if episode is not None and any(e.get('episode_id', episode) != episode
                                  for e in (event, issuer[1], before[1], after[1], origin[1])):
        return 'episode_mismatch'
    return None


def superseded(seq, event, text, rows, decisions, observations, episode):
    args = (event.get('tool') or {}).get('arguments', {})
    group = family(text, args)
    for n, later, _ in sorted(rows):
        if (n <= seq or later.get('instruction') != event.get('instruction')
                or evidence_reason(n, later, observations, decisions, episode) is not None):
            continue
        a = (later.get('tool') or {}).get('arguments', {})
        issuer = decisions.get(later.get('decision_id'))
        later_text = operation_text(public(issuer[1])) if issuer else ''
        if group == 'clipboard' and a.get('action') == 'key':
            if keys(a) in (('c', 'ctrl'), ('ctrl', 'x')):
                return ('later_attempt_failed' if failed(later) else 'clipboard_replaced'), n
            if keys(args) in (('c', 'ctrl'), ('ctrl', 'x')) and keys(a) == ('ctrl', 'v'):
                return ('later_attempt_failed' if failed(later) else 'phase_advanced'), n
        if object_conflict(text, later_text):
            continue
        same = (group == 'zoom' and family(later_text, a) == 'zoom'
                or bool(terms(text) & terms(later_text)) and group == family(later_text, a))
        if args.get('action') == 'type' and a.get('action') == 'type' and same:
            return ('later_attempt_failed' if failed(later) else 'parameters_superseded'), n
        if group == 'zoom' and phase(text, args) != 'confirm':
            if a.get('action') == 'type' and same:
                return ('later_attempt_failed' if failed(later) else 'phase_advanced'), n
            if a.get('action') == 'key' and keys(a) in (('enter',), ('return',)):
                # Scope must have remained continuous since this zoom attempt.
                return ('later_attempt_failed' if failed(later) else 'phase_advanced'), n
        if operations(later_text) & (NAVIGATION | {'window_switch'}) and group == 'zoom':
            return 'scope_changed', n
    return None, None


def retrieve(rows, instruction, proposals, step, *, navigation_only=False):
    """Same eligibility for either entrypoint; rejection details stay local.

    The result does not assert that a target is current or a past action worked.
    No images, private reasoning, evaluator data or cross-task memory are read.
    """
    audit = {'version': VERSION, 'query': None, 'candidates': [], 'selected_ref': None}
    result = {'selected': None, 'audit': audit}
    boundary = max((n for n, e, _ in rows if e.get('kind') == 'task_input'
                    and e.get('instruction') != instruction), default=0)
    rows = [r for r in rows if r[0] > boundary]
    by_seq = {n: e for n, e, _ in rows}
    proposals = sorted((p for p in proposals if p[0] > boundary and 0 <= step - p[2] <= 2), reverse=True)
    if not proposals:
        audit['reason'] = 'no_fresh_public_demand'
        return result
    qref, full_query, when = proposals[0]
    query_event = by_seq.get(qref, {})
    original_query = (query_event.get('query') or {}).get('intent') if query_event.get('kind') == 'knowledge_query' else public(query_event)
    if (not full_query or full_query.strip() != (original_query or '').strip()
            or query_event.get('instruction') != instruction or query_event.get('step') != when):
        audit['reason'] = 'unbound_or_empty_query'
        return result
    query = operation_text(full_query)
    query_ops = immediate_actions(analyze(query))
    navigation = bool(query_ops & NAVIGATION and REPEAT.search(query))
    audit['query'] = {'ref': qref, 'origin': query_event.get('kind'), 'step': when, 'text': query}
    if not query_ops:
        audit['reason'] = 'no_public_operation'
        return result
    if navigation_only and not navigation:
        audit['reason'] = 'no_navigation_repeat'
        return result
    observations = {e.get('id'): (n, e) for n, e, _ in rows if e.get('kind') == 'observation'}
    decisions = {e.get('id'): (n, e) for n, e, _ in rows if e.get('kind') == 'decision'
                 and e.get('instruction') == instruction}
    query_source = observations.get(query_event.get('source'))
    if not query_source or query_source[0] >= qref or query_event.get('kind') not in ('decision', 'knowledge_query'):
        audit['reason'] = 'missing_query_observation'
        return result
    if query_event.get('kind') == 'knowledge_query' and when != step:
        audit['reason'] = 'stale_knowledge_query'
        return result
    episode = query_event.get('episode_id')
    if episode is not None and query_source[1].get('episode_id', episode) != episode:
        audit['reason'] = 'query_episode_mismatch'
        return result
    eligible = []
    for seq, event, _ in sorted(rows):
        if seq >= qref or event.get('kind') != 'transition' or event.get('instruction') != instruction:
            continue
        issuer = decisions.get(event.get('decision_id'))
        text = operation_text(public(issuer[1])) if issuer else ''
        overlap = terms(query) & terms(text)
        same_zoom = family(query, {}) == family(text, (event.get('tool') or {}).get('arguments', {})) == 'zoom'
        if not (query_ops & operations(text) or same_zoom) or not overlap:
            continue
        row = {'ref': seq, 'intent_ref': issuer[0], 'origins': ['operation_overlap']}
        if navigation and operations(text) & NAVIGATION:
            row['origins'].append('navigation_repeat')
        if navigation_only and 'navigation_repeat' not in row['origins']:
            continue
        reason = evidence_reason(seq, event, observations, decisions, episode)
        args = (event.get('tool') or {}).get('arguments', {})
        if reason is None and not 0 <= step - event.get('step', -99) <= READ_TTL:
            reason = 'expired'
        if reason is None and args.get('action') in ('screenshot', 'wait', 'key_down', 'key_up'):
            reason = 'passive_or_partial_action'
        if reason is None and object_conflict(query, text):
            reason = 'object_mismatch'
        if reason is None:
            reason, later_ref = superseded(seq, event, text, rows, decisions, observations, episode)
            if later_ref is not None:
                row['superseding_ref'] = later_ref
        query_phase, candidate_phase = phase(query), phase(text, args)
        if reason is None and (candidate_phase in ('input', 'confirm') and candidate_phase != query_phase
                or family(text, args) == 'zoom' and query_phase in ('confirm', 'inspect')
                    and candidate_phase != query_phase):
            reason = 'phase_mismatch'
        if reason is None and args.get('action') == 'type' and family(query, args) == 'zoom':
            ratios = re.findall(r'(?<![\w.])\d+(?:\.\d+)?(?![\w.])', FILES.sub('', query))
            if ratios and str(args.get('text', '')).strip().rstrip('%').strip() != ratios[-1]:
                reason = 'requested_parameters_differ'
        row['status'], row['reason'] = ('rejected', reason) if reason else ('eligible', None)
        audit['candidates'].append(row)
        if reason is not None:
            continue
        selected = {'ref': seq, 'query_ref': qref, 'intent_ref': issuer[0], 'text': text,
                    'matched_terms': sorted(overlap), 'basis': 'eligible_attempt_reference_not_success',
                    'purpose': 'avoid_repeat' if failed(event) else 'procedure_reference',
                    'parameters': 'historical_only_rebuild_current'}
        # Named eligibility rules precede chronological tie-breaking. No score.
        eligible.append((seq, str(event.get('id', '')), selected))
    if eligible:
        result['selected'] = max(eligible, key=lambda x: x[:2])[2]
        audit['selected_ref'] = result['selected']['ref']
    audit['reason'] = 'selected' if eligible else 'no_eligible_attempt'
    return result
