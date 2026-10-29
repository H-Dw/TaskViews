"""Source-bound action conditions and public reading notes, never a planner.

Only original task text, public content and bounded journal facts are used.
Pixel equality and successful receipts never certify a task or a UI target.
"""
import json
import re

from .guidance_semantics import analyze, operations

READ_TTL = 12
NOTE_CHARS = 180
NOTE_GROUP_CHARS = 360
NOTE_LIMIT = 4
EFFECT_TTL = 6
NAVIGATION = {'open', 'window_switch', 'window_locate', 'folder_open', 'url_open', 'file_find'}
POINTER = {'mouse_move', 'left_click', 'right_click', 'middle_click', 'double_click', 'triple_click', 'left_click_drag'}
READ_CLAIM = re.compile(r'\b(?:shows?|reads?|value|total|amount|matches?|differs?|difference|comparison|compared)\b|显示|读数|数值|合计|一致|不符|差异|比对', re.I)
INTENT = re.compile(r"\b(?:let me|i will|i'll|need to|should|going to)\b|接下来|需要|准备|打算", re.I)


def confirmed(event):
    receipts = event.get('controller_receipts') or []
    return (event.get('kind') == 'transition' and event.get('dispatch_observed') is True
            and event.get('command_alignment') == 'matched' and not event.get('gaps') and not event.get('error')
            and bool(receipts) and all(isinstance(r.get('result'), dict)
                and r['result'].get('success') is not False and not r['result'].get('error')
                and r['result'].get('returncode', 0) == 0
                and r['result'].get('status') not in ('error', 'failed', 'failure') for r in receipts))


def keys(args):
    value = args.get('keys', [])
    if isinstance(value, str):
        value = value.lower().split('+')
    return tuple(sorted(value)) if isinstance(value, list) and all(isinstance(k, str) for k in value) else ()


def public(event):
    text = event.get('local_instruction') or event.get('response')
    if isinstance(text, str) and text.lstrip().startswith('{'):
        try:
            text = json.loads(text).get('content')
        except (ValueError, AttributeError):
            return ''
    # In particular, never fall back to reasoning_content.
    return text if isinstance(text, str) else ''


def short_cycle(actions):
    """A repeated command pattern asks for inspection; it does not prove failure.

    Changing-pixel clicks may still cycle. Scroll, text input and clipboard
    operations are excluded; repeated paging/copying is not a failed cycle.
    """
    signatures, refs = [], []
    for seq, event, _ in actions[:6]:
        args = (event.get('tool') or {}).get('arguments', {})
        allowed = args.get('action') in ('left_click', 'right_click', 'double_click', 'triple_click', 'left_click_drag')
        if args.get('action') == 'key':
            allowed = keys(args) in (('delete',), ('backspace',), ('super',), ('win',), ('alt', 'f10'))
        if not allowed or not confirmed(event):
            break
        # A different drag duration is retained in the audit, but cannot repair
        # a missing start position. All other literal parameters are preserved.
        signature = {k: v for k, v in args.items() if not (args.get('action') == 'left_click_drag' and k == 'duration')}
        signatures.append(json.dumps(signature, sort_keys=True, separators=(',', ':')))
        refs.append(seq)
    for period in (1, 2, 3):
        if len(signatures) >= period * 2 and signatures[:period] == signatures[period:period * 2]:
            return {'period': period, 'action_refs': sorted(refs[:period * 2]),
                    'progress': 'unknown', 'basis': 'repeated_commands_not_semantic_failure'}
    return None


def action_intent(seq, event, rows):
    """Use the issuing public decision, never a later or stale global intent."""
    decisions = [(n, e) for n, e, _ in rows if n < seq and e.get('kind') == 'decision'
                 and e.get('instruction') == event.get('instruction')]
    identity = event.get('decision_id')
    matched = [(n, e) for n, e in decisions if identity and e.get('id') == identity]
    if not matched:
        return None
    n, decision = max(matched)
    return n, operations(public(decision))


def zoom_entry(seq, event, rows):
    return zoom_entry_sources(seq, event, rows) is not None


def zoom_entry_sources(seq, event, rows):
    """Numeric input needs a source-bound zoom context, not a number heuristic.

    A tool-only decision may continue an immediately preceding explicit zoom
    field intention. Intervening content/navigation commands invalidate that
    context. Neither the old intention nor the receipt certifies focus.
    """
    args = (event.get('tool') or {}).get('arguments', {})
    intent = action_intent(seq, event, rows)
    if (not confirmed(event) or args.get('action') != 'type' or not intent
            or not re.fullmatch(r'\s*\d+(?:\.\d+)?\s*%?\s*', str(args.get('text', '')))):
        return None
    if intent[1] & {'zoom_in', 'zoom_out', 'zoom_value'}:
        return {'refs': [intent[0], seq], 'basis': 'issuing_public_zoom_intent'}
    issuer = next(e for n, e, _ in rows if n == intent[0])
    if public(issuer).strip():
        return None
    observations = {e.get('id'): n for n, e, _ in rows if e.get('kind') == 'observation'}
    for n, decision, _ in sorted(rows, reverse=True):
        if (n >= intent[0] or decision.get('kind') != 'decision'
                or decision.get('instruction') != event.get('instruction')
                or not 0 <= event['step'] - decision.get('step', -3) <= 2):
            continue
        text = public(decision)
        if not text.strip():
            continue
        obs_ref = observations.get(decision.get('source'))
        is_zoom = ('zoom_value' in operations(text) or re.search(
            r'\b(?:focus|select|click)\b[^.;\n]{0,24}\bzoom (?:field|box|control)\b|(?:聚焦|选中|点击)缩放(?:框|输入框)', text, re.I))
        if not is_zoom or obs_ref is None or obs_ref >= n:
            return None
        intervening = [(r, e) for r, e, _ in rows if n < r < seq and e.get('kind') == 'transition']
        for _, e in intervening:
            a = (e.get('tool') or {}).get('arguments', {})
            allowed = a.get('action') in ('mouse_move', 'left_click', 'double_click', 'triple_click', 'screenshot', 'wait')
            allowed |= a.get('action') == 'key' and keys(a) == ('a', 'ctrl')
            if e.get('instruction') != event.get('instruction') or not confirmed(e) or not allowed:
                return None
        return {'refs': sorted({obs_ref, n, intent[0], seq, *(r for r, _ in intervening)}),
                'basis': 'prior_public_zoom_context_focus_unconfirmed'}
    return None


def readability_report(rows, instruction, step):
    observations = {e.get('id'): n for n, e, _ in rows if e.get('kind') == 'observation'}
    for seq, event, _ in sorted(rows, reverse=True):
        if (event.get('kind') != 'decision' or event.get('instruction') != instruction
                or not 0 <= step - event.get('step', -3) <= 2):
            continue
        source = observations.get(event.get('source'))
        states = [s for s in analyze(public(event))['states'] if s['kind'] in ('readable', 'unreadable')]
        if source is None or source >= seq or not states:
            continue
        if any(n > source and e.get('kind') == 'transition' and
               (e.get('tool') or {}).get('arguments', {}).get('action') not in ('screenshot', 'wait') for n, e, _ in rows):
            return None  # A changed viewport/content needs a fresh report.
        return {'ref': seq, 'before': source, 'state': states[-1]['kind'],
                'grade': 'model_readability_proposal', 'expires_step': event['step'] + 2,
                'verification': 'unknown'}
    return None


def mixed_view_cycle(actions, rows):
    """Two literal focus/input/scroll rounds; no pixel or success inference.

    Require source-bound zoom input and the same focus coordinates. Changed
    numeric values are retained locally, not mistaken for progress. Paging
    alone, ordinary editing and clipboard sequences cannot trigger this.
    """
    recent = list(reversed(actions[:16]))
    rounds, group = [], []
    for seq, event, digest in recent:
        a = (event.get('tool') or {}).get('arguments', {})
        action = a.get('action')
        if not confirmed(event):
            rounds, group = [], []
        elif action in ('left_click', 'double_click', 'triple_click'):
            group = [(seq, event, digest)]
        elif group and action == 'type' and zoom_entry(seq, event, rows):
            group.append((seq, event, digest))
        elif group and action == 'scroll' and any((e['tool']['arguments']['action'] == 'type') for _, e, _ in group):
            group.append((seq, event, digest))
            rounds.append(group)
            group = []
        elif action not in ('screenshot', 'wait', 'mouse_move') and not (
                action == 'key' and keys(a) in (('a', 'ctrl'), ('enter',), ('return',))):
            rounds, group = [], []
    if len(rounds) < 2:
        return None
    a, b = rounds[-2:]
    if a[0][1]['tool']['arguments'].get('coordinate') != b[0][1]['tool']['arguments'].get('coordinate'):
        return None
    return {'action_refs': [n for r in (a, b) for n, _, _ in r], 'progress': 'unknown',
            'basis': 'repeated_focus_numeric_zoom_scroll',
            'entered_values': [e['tool']['arguments']['text'] for r in (a, b) for _, e, _ in r
                               if e['tool']['arguments']['action'] == 'type']}


def pending_effect(rows, instruction, step):
    """Rebuild a bounded pending effect from the journal; no GUI replay.

    Dispatch is known, zoom intent is a model proposal, UI effect is unknown.
    Clicks and new screenshots do not erase a pending confirmation. A source-
    bound later public observation can retire it as *reported*, never verified.
    """
    state, audit = None, []
    observations = {e.get('id'): n for n, e, _ in rows if e.get('kind') == 'observation'}
    for seq, event, _ in sorted(rows):
        if event.get('instruction') != instruction:
            continue
        if state and event.get('step', step) > state['expires_step']:
            audit.append({'ref': state['ref'], 'reason': 'expiry'})
            state = None
        if event.get('kind') == 'decision' and state:
            text = public(event)
            if (observations.get(event.get('source'), 0) > state['ref'] and not INTENT.search(text)
                    and not re.search(r'\b(?:not|unchanged|unclear|failed)\b|未生效|没有|不确定|未变', text, re.I)
                    and re.search(r'(?:zoom|scale|缩放|比例).{0,24}(?:shows?|is|now|显示|为|已).{0,12}\d+(?:\.\d+)?\s*%', text, re.I)):
                audit.append({'ref': seq, 'reason': 'public_zoom_report_not_certification', 'action_ref': state['ref']})
                state = None
        if event.get('kind') != 'transition':
            continue
        args = (event.get('tool') or {}).get('arguments', {})
        if not confirmed(event):
            if state:
                audit.append({'ref': seq, 'reason': 'uncertain_dispatch_invalidates_pending_scope'})
                state = None
            continue
        entry = zoom_entry_sources(seq, event, rows)
        if entry:
            repeats = state['entries'] + 1 if state else 1
            state = {'ref': seq, 'refs': entry['refs'], 'basis': entry['basis'], 'phase': 'confirm_once',
                     'entered': args['text'], 'entries': repeats,
                     'expires_step': event['step'] + EFFECT_TTL, 'effect': 'unknown'}
        elif state and args.get('action') == 'key' and keys(args) in (('enter',), ('return',)):
            state['phase'] = 'inspect_effect'
            state['refs'] = sorted(set([*state['refs'], seq]))
        elif state and (args.get('action') == 'type' or args.get('action') == 'key' and keys(args) in
                       (('esc',), ('escape',), ('alt', 'tab'), ('ctrl', 'l'), ('ctrl', 'o'),
                        ('ctrl', 'v'), ('ctrl', 'x'), ('ctrl', 'z'))):
            audit.append({'ref': seq, 'reason': 'scope_or_content_change'})
            state = None
    if state and step > state['expires_step']:
        audit.append({'ref': state['ref'], 'reason': 'expiry'})
        state = None
    return state, audit


def public_reading_block(text):
    """A verbatim observed-data heading and complete short numeric list.

    Never extract anonymous numbers from a plan, private reasoning or a list
    without a public observation claim. Oversized blocks are omitted whole.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        heading = re.split(r'(?<=[.!?。！？])\s+', line.strip())[0]
        observed = re.search(r'\bI (?:now )?have\b.{0,80}\b(?:data|values|numbers|readings)\b', heading, re.I)
        observed = observed or READ_CLAIM.search(heading)
        if not observed or INTENT.search(heading) or re.search(r'\b(?:if|whether|maybe|perhaps)\b|[?？]|如果|是否|可能', heading, re.I):
            continue
        block = []
        for next_line in lines[i + 1:]:
            if not next_line.strip() and not block:
                continue
            if not re.match(r'\s*(?:[-*•]|\d+[.)])\s+', next_line):
                break
            # Numeric, labeled report rows; do not turn arbitrary bullet plans
            # or numeric keyboard targets into stored reading conclusions.
            if (not re.search(r'\d', next_line) or not re.search(r'[a-zA-Z\u4e00-\u9fff]', next_line)
                    or INTENT.search(next_line) or operations(next_line) & (NAVIGATION | {'edit', 'zoom_value', 'save', 'save_as', 'export'})):
                block = []
                break
            block.append(next_line.strip())
        if block:
            value = '\n'.join([heading, *block])
            return value if len(value) <= NOTE_GROUP_CHARS else None
    return None


def reading_notes(rows, instruction, step):
    """Whole short public statements, retained as proposals with original sources.

    Edits/undo, task boundaries, expiry and explicit corrections invalidate
    older claims. View changes alone do not certify or refute a reading.
    """
    boundary = max((n for n, e, _ in rows if e.get('kind') == 'task_input'
                    and e.get('instruction') != instruction), default=0)
    context_rows = [r for r in rows if r[0] > boundary]
    relevant = [(n, e, h) for n, e, h in rows if n > boundary and e.get('instruction') == instruction]
    invalidations = []
    for seq, e, _ in relevant:
        args = (e.get('tool') or {}).get('arguments', {})
        if zoom_entry(seq, e, context_rows):
            invalidations.append({'ref': seq, 'reason': 'view_adjustment_intent_not_content_edit',
                                  'focus_confirmed': False})
        elif confirmed(e) and (args.get('action') == 'type'
                or args.get('action') == 'key' and keys(args) in
                (('delete',), ('backspace',), ('ctrl', 'v'), ('ctrl', 'x'), ('ctrl', 'z'))):
            boundary = max(boundary, seq)
            invalidations.append({'ref': seq, 'reason': 'possible_content_change'})
        if e.get('kind') == 'decision' and re.search(r'\b(?:misread|correction|mistaken)\b|读错|更正|纠正', public(e), re.I):
            boundary = max(boundary, seq)
            invalidations.append({'ref': seq, 'reason': 'public_correction_requires_new_observation'})
    observations = {e.get('id'): (n, e) for n, e, _ in rows if e.get('kind') == 'observation'}
    notes, excluded, seen = [], [], set()
    for seq, e, _ in sorted(relevant, reverse=True):
        if seq <= boundary or e.get('kind') != 'decision' or not 0 <= step - e.get('step', -READ_TTL) <= READ_TTL:
            continue
        origin = observations.get(e.get('source'))
        if origin is None or origin[0] <= boundary or origin[0] >= seq:
            continue
        text = re.sub(r'<(artifact_review|key_lookup)>.*?</\1>', '', public(e), flags=re.S)
        # Split at sentence boundaries, never truncate a long claim mid-value.
        block = public_reading_block(text)
        claims = re.split(r'\n+|(?<=[.!?。！？])\s+', text)
        if block:
            claims = [block, *(c for c in claims if c.strip() not in block)]
        for claim in claims:
            claim = claim.strip()
            if ((claim != block and not READ_CLAIM.search(claim)) or INTENT.search(claim) or claim in seen or claim.endswith((':', '：'))
                    or '?' in claim or '？' in claim
                    or re.search(r'\b(?:if|whether|perhaps|maybe)\b|如果|是否|可能', claim, re.I)):
                continue
            if len(claim) > (NOTE_GROUP_CHARS if claim == block else NOTE_CHARS):
                excluded.append({'ref': seq, 'reason': 'whole_claim_too_long'})
                continue
            seen.add(claim)
            existing = next((n for n in notes if n['ref'] == seq), None)
            if existing is not None:
                if len(existing['text']) + 1 + len(claim) <= NOTE_GROUP_CHARS:
                    existing['text'] += '\n' + claim
                else:
                    excluded.append({'ref': seq, 'reason': 'whole_claim_group_budget'})
            else:
                notes.append({'grade': 'model_reading_proposal', 'ref': seq, 'before': origin[0],
                              'text': claim, 'expires_step': e['step'] + READ_TTL,
                              'verification': 'unknown'})
    # Give each original observation one turn before admitting a second claim
    # from the same image. This is provenance diversity, NOT document identity.
    groups = {}
    for note in notes:
        groups.setdefault(note['before'], []).append(note)
    diverse = []
    while groups and len(diverse) < NOTE_LIMIT:
        for source in list(groups):
            diverse.append(groups[source].pop(0))
            if not groups[source]:
                del groups[source]
            if len(diverse) == NOTE_LIMIT:
                break
    return diverse, {'invalidations': invalidations, 'excluded': excluded,
                     'eligible_claims': len(notes), 'bounded_claims_omitted': len(notes) - len(diverse)}


def adjustment_chain(rows, instruction, step):
    """Different view commands under a public reading goal, not GUI failure.

    Source-bound decisions and returned actions prove only an adjustment was
    attempted. Navigation, editing, failed receipts and a new reading report
    reset the chain. No window identity or pixel semantics are invented.
    """
    goal = operations(instruction)
    if not goal & {'reading', 'readability'} or goal & {'zoom_value', 'image_edit'}:
        return None
    observations = {e.get('id'): n for n, e, _ in rows if e.get('kind') == 'observation'}
    decisions, chain = {}, []
    view_ops = {'zoom_in', 'zoom_out', 'zoom_value', 'readability', 'maximize'}
    for seq, event, _ in sorted(rows):
        if event.get('instruction') != instruction or not 0 <= step - event.get('step', -99) <= EFFECT_TTL:
            continue
        if event.get('kind') == 'decision':
            text = public(event)
            ops = operations(text)
            origin = observations.get(event.get('source'))
            if origin is None or origin >= seq:
                chain = []
                continue
            decisions[event.get('id')] = (seq, origin, ops, text)
            if (ops & (NAVIGATION | {'edit', 'image_edit', 'save', 'save_as', 'export'})
                    or READ_CLAIM.search(text) and not INTENT.search(text) and not ops & view_ops):
                chain = []
        if event.get('kind') != 'transition':
            continue
        args = (event.get('tool') or {}).get('arguments', {})
        if args.get('action') in ('screenshot', 'wait', 'mouse_move'):
            continue
        issuer = decisions.get(event.get('decision_id'))
        if not confirmed(event) or not issuer:
            chain = []
            continue
        n, origin, ops, text = issuer
        related = ops & view_ops
        if 'menu_open' in ops and re.search(r'\b(?:zoom|view)\b|缩放|视图', text, re.I):
            related = related | {'menu_open'}
        if chain and not related and ops & {'reading', 'readability'} and re.search(
                r'\b(?:select|choose)\s+\d+(?:\.\d+)?\s*%|选择\s*\d+(?:\.\d+)?\s*%', text, re.I):
            # Continue only an already sourced zoom/menu chain; a percentage
            # anywhere in the task is insufficient. It remains proposed intent.
            if set(chain[-1]['operations']) & {'zoom_in', 'zoom_out', 'zoom_value', 'menu_open'}:
                related = {'zoom_value'}
        allowed = args.get('action') in ('left_click', 'double_click', 'triple_click')
        allowed |= args.get('action') == 'type' and zoom_entry(seq, event, rows)
        allowed |= args.get('action') == 'key' and keys(args) in (
            ('a', 'ctrl'), ('return',), ('enter',), ('alt', 'f10'), ('ctrl', '+'), ('ctrl', '-'))
        if not related or not allowed:
            chain = []
            continue
        chain.append({'ref': seq, 'decision': n, 'before': origin, 'operations': sorted(related), 'step': event['step']})
    if (len({x['decision'] for x in chain}) < 2 or step - chain[-1]['step'] > 2
            or not set().union(*(set(x['operations']) for x in chain)) & view_ops):
        return None
    return {'ref': chain[-1]['ref'], 'evidence': [{'ref': n} for n in sorted(
        {x[k] for x in chain for k in ('ref', 'decision', 'before')})],
        'adjustments': chain, 'effect': 'unknown', 'basis': 'public_reading_goal_view_adjustments'}


def intent_excerpt(text):
    """A whole public action sentence, never a sliced thought or private reasoning."""
    clean = re.sub(r'<(artifact_review|key_lookup)>.*?</\1>', '', text or '', flags=re.S)
    sentences = [s.strip() for s in re.split(r'\n+|(?<=[.!?。！？])\s+', clean) if s.strip()]
    return next((s for s in sentences if len(s.encode()) <= 160 and operations(s)),
                next((s for s in sentences if len(s.encode()) <= 160), ''))


def navigation_recall(rows, instruction, proposals, step):
    """At most one lexical match to a prior navigation intention.

    It is an index into an attempted action, never a saved coordinate macro.
    Ambiguous scores tie by latest seq; task boundaries are applied by caller.
    """
    navigation = NAVIGATION
    stop = set('the this that with from into then again please would should want need will let open '
               'switch window application app document file folder read review check compare back return'.split())
    def terms(text):
        return {w.casefold() for w in re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{2,}', text)} - stop
    query = next(((n, text) for n, text, when in proposals if 0 <= step - when <= 2
                  and operations(text) & navigation and re.search(
                      r'\b(?:again|reopen|back to|return to|switch back)\b|重新打开|再次打开|切回|返回', text, re.I)), None)
    if not query:
        return None
    observations = {e.get('id'): n for n, e, _ in rows if e.get('kind') == 'observation'}
    decisions = {e.get('id'): (n, e) for n, e, _ in rows if e.get('kind') == 'decision'
                 and e.get('instruction') == instruction}
    found = []
    for seq, event, _ in rows:
        if (seq >= query[0] or event.get('instruction') != instruction or not confirmed(event)
                or not 0 <= step - event.get('step', -99) <= READ_TTL):
            continue
        issuer = decisions.get(event.get('decision_id'))
        if not issuer or issuer[0] >= seq or observations.get(issuer[1].get('source'), seq) >= issuer[0]:
            continue
        text = intent_excerpt(public(issuer[1]))
        overlap = terms(query[1]) & terms(text)
        if operations(text) & navigation and overlap:
            found.append((len(overlap), seq, {'ref': seq, 'query_ref': query[0],
                'intent_ref': issuer[0], 'text': text, 'matched_terms': sorted(overlap),
                'basis': 'public_text_match_not_target_or_success'}))
    return max(found, key=lambda x: x[:2])[2] if found else None


def build(*, rows, instruction, proposals, step, observation_ref, decision_limit=None):
    boundary = max((n for n, e, _ in rows if e.get('kind') == 'task_input'
                    and e.get('instruction') != instruction), default=0)
    rows = [r for r in rows if r[0] > boundary]
    actions = [(n, e, h) for n, e, h in sorted(rows, reverse=True) if n > boundary
               and e.get('instruction') == instruction and e.get('kind') == 'transition']
    latest = actions[0] if actions else None
    recent_ops = set().union(*(operations(text) for n, text, when in proposals
                              if n > boundary and 0 <= step - when <= 2))
    feedback, audit = [], {}
    pending, pending_audit = pending_effect([r for r in rows if r[0] > boundary], instruction, step)
    audit['pending_effect'] = {'state': pending, 'retired': pending_audit}

    def add(kind, constraint, ref=None, **data):
        feedback.append({'kind': kind, 'ref': ref or observation_ref, 'constraint': constraint,
                         'effect': 'unknown', **data})

    held = {}
    for seq, event, _ in reversed(actions):
        args = (event.get('tool') or {}).get('arguments', {})
        if args.get('action') in ('key_down', 'key_up'):
            if not confirmed(event):
                held.clear()  # Unknown receipt never establishes held state.
                continue
            for key in keys(args):
                if args['action'] == 'key_down':
                    held[key] = seq
                else:
                    held.pop(key, None)
    if held:
        add('held_modifiers', 'Keep held keys only for the intended modified action; then key_up. Release before typing or finishing.',
            max(held.values()), keys=sorted(held))
    if pending:
        instruction_text = ('Zoom entry dispatched; focus/effect unknown. Confirm once only in that field, then inspect. Do not retype.'
                            if pending['phase'] == 'confirm_once' else
            'Enter was dispatched after zoom entry. Inspect scale/readability; do not re-enter. Return is not proof of zoom.')
        add('zoom_pending', instruction_text, pending['ref'],
            evidence=[{'ref': n} for n in pending['refs']], entered=pending['entered'],
            phase=pending['phase'], expires_step=pending['expires_step'])
    chain = adjustment_chain(rows, instruction, step)
    audit['adjustment_chain'] = chain
    if chain and not pending:
        add('view_adjustment_chain',
            'View adjustments already dispatched. Inspect readability now: readable -> read; otherwise identify the still-unreadable region before ONE new adjustment. No arbitrary percentage target.',
            chain['ref'], evidence=chain['evidence'])
    if latest and confirmed(latest[1]) and 0 <= step - latest[1].get('step', -3) <= 2:
        seq, event, _ = latest
        args = (event.get('tool') or {}).get('arguments', {})
        if args.get('action') == 'left_click_drag':
            previous = next(((n, e) for n, e, _ in actions[1:] if confirmed(e)
                and (e.get('tool') or {}).get('arguments', {}).get('action') in POINTER), None)
            audit['drag'] = {'ref': seq, 'previous_pointer_ref': previous[0] if previous else None,
                             'semantic_source_confirmed': False}
            add('drag_start', 'Drag coordinate is the destination; start is the current pointer. Ground the source first (mouse_move), then drag; duration cannot fix a wrong start. Check the result.', seq)
        if not pending and not chain and recent_ops & {'zoom_in', 'zoom_out', 'zoom_value'}:
            message = ('Typing alone does not confirm zoom: if the zoom field is still focused, confirm once; inspect the displayed scale before reading.'
                       if args.get('action') == 'type' else
                       'Inspect the displayed zoom and readable content. A click or returned command is not proof of zoom; re-identify the zoom control before repeating.')
            add('zoom_effect', message, seq)
    mixed = mixed_view_cycle(actions, rows) if latest and 0 <= step - latest[1].get('step', -3) <= 2 else None
    if mixed:
        add('mixed_view_cycle', 'Focus, numeric entry and scroll repeated. Inspect readability now; if readable, read. Otherwise finish only the pending confirmation/effect check before another adjustment.',
            latest[0], evidence=[{'ref': n} for n in mixed['action_refs']])
        audit['mixed_view_cycle'] = mixed
    cycle = short_cycle(actions) if latest and 0 <= step - latest[1].get('step', -3) <= 2 else None
    if cycle:
        window_cycle = any(keys((e.get('tool') or {}).get('arguments', {})) in
                           (('super',), ('win',), ('alt', 'f10')) for _, e, _ in actions[:cycle['period']])
        constraint = ('A window toggle pattern repeated. Identify the visible target window/title first; do not toggle again until the intended window is visible. Receipt success does not identify the window.'
                      if window_cycle else
                      'A command pattern repeated. Compare visible target/selection and effect; change the unmet precondition before repeating. Repetition alone is not failure.')
        add('command_cycle', constraint,
            latest[0], period=cycle['period'], evidence=[{'ref': n} for n in cycle['action_refs']])
        audit['cycle'] = cycle
    remaining = max(0, decision_limit - step + 1) if decision_limit is not None else None
    save_actions = [seq for seq, event, _ in actions if confirmed(event)
                    and 0 <= step - event.get('step', -3) <= 2
                    and (event.get('tool') or {}).get('arguments', {}).get('action') == 'key'
                    and keys(event['tool']['arguments']) in (('ctrl', 's'), ('ctrl', 's', 'shift'),
                                                             ('ctrl', 'e', 'shift'))]
    finishing = (bool(recent_ops & {'save', 'save_as', 'export'} or save_actions) or remaining is not None and remaining <= 6
                 or any(re.search(r'\b(?:task (?:is )?complete|ready to (?:finish|terminate)|final check)\b|任务完成|最终检查',
                                  text or '', re.I) for n, text, when in proposals
                        if n > boundary and 0 <= step - when <= 2))
    completion = {'remaining_decisions': remaining, 'status': 'unverified'}
    if finishing:
        completion['check'] = ('Finish pending dialogs and release held keys; verify the public goal. Save/export only if required; inspect actual content/location. Budget expiry is not success.')
    notes, note_audit = reading_notes(rows, instruction, step)
    audit['reading'] = note_audit
    # The complete audit preserves all detections. Current context carries at
    # most two distinct constraints; neither instruction nor claim is cut.
    audit['finishing_action_refs'] = save_actions
    recall = navigation_recall(rows, instruction, proposals, step)
    audit['navigation_recall'] = recall
    return {'version': 'source_bound_reading_support_v6', 'feedback': feedback[:2],
            'feedback_omitted': max(0, len(feedback) - 2), 'completion': completion,
            'finishing': finishing, 'pending_effect': pending, 'adjustment_chain': chain,
            'navigation_recall': recall,
            'readability': readability_report([r for r in rows if r[0] > boundary], instruction, step),
            'reading_progress': notes, 'audit': audit,
            'reading_condition': 'Reuse Lessons reports only for the same unchanged content. Re-read missing, conflicting or expired information; old coordinates are not reusable.'}
