"""Deterministic task capabilities and source-bound, conditional operation guidance.

Only public task fields, public actor text and confirmed journal events enter
the router. No evaluator, filename heuristics, screenshots-as-text, or model
calls. Receipt success means dispatch returned, never business success.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .model import dumps
from .guidance_semantics import PATTERNS, VERSION as SEMANTICS_VERSION, analyze, capabilities, immediate_actions
from .guidance_semantics import operations as operations
from .guidance_groups import catalog_alternatives, model_structure, structure, validate_library
from .decision_flow import policy as decision_flow_policy
from . import guidance_selection as selection
from .guidance_eligibility import (VERSION as ELIGIBILITY_VERSION, catalog_operation,
                                  contextual_reason, guide_reason, owner, software_reason)

VERSION = 'capability_guidance_v10'
ENV = 'UI_KOBE_MINI_GUIDANCE'
LIBRARY = json.loads((Path(__file__).parent / 'key_tools/guidance.json').read_text(encoding='utf-8'))
validate_library(LIBRARY)
PACKING = 'layered_guidance_v10'
SOURCE_ENCODING = 'journal_seq_local_audit_v1'
HISTORY = 96
TTL = 6
VERIFY_TTL = 2

REFERENCE_INTENTS = {'zoom_in': 'zoom in', 'zoom_out': 'zoom out', 'actual_pixels': 'actual pixels', 'play': 'toggle playback',
                     'stop': 'stop playback', 'fullscreen': 'toggle full screen',
                     'seek_forward': 'short seek forward', 'seek_backward': 'short seek backward',
                     'window_switch': 'switch window or application', 'focus_next': 'next control',
                     'context_menu': 'open focused item context menu'}


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def policy(fields, enabled, *, review_prompt='full', decision_limit=None,
           review_timing='stage', review_budget='refill'):
    from .review_presentation import validate as validate_presentation
    validate_presentation(review_timing, review_budget)
    if review_prompt not in ('full', 'compact'):
        raise ValueError('Unknown Mini review prompt mode')
    if decision_limit is not None and (type(decision_limit) is not int or not 1 <= decision_limit <= 500):
        raise ValueError('Mini guidance decision limit must match the frozen runner limit')
    return {'version': VERSION, 'library_sha256': digest(LIBRARY), 'packing': PACKING,
            'semantics': SEMANTICS_VERSION,
            'execution_support': 'source_bound_reading_support_v6',
            'reading_progress': 'observation_diverse_public_reports_v3',
            'review_prompt': review_prompt, 'decision_limit': decision_limit,
            'review_timing': review_timing, 'review_budget': review_budget,
            'review_budget_selection': 'independent_presentation_and_refill_v1',
            'source_encoding': SOURCE_ENCODING,
            'instruction_sha256': hashlib.sha256(fields['instruction'].encode()).hexdigest(),
            'task_input_sha256': digest(fields), 'capabilities': capabilities(fields['instruction']),
            'enabled_toolsets': sorted(set(enabled)), 'history_events': HISTORY,
            'pending_decision_ttl': TTL, 'verification_decision_ttl': VERIFY_TTL,
            'extra_model_calls': 'zero_automatic_at_most_one_optional_knowledge_roundtrip',
            'decision_flow': decision_flow_policy(), 'focus_confirmation': 'required_not_inferred',
            'intent_sources': ['original_task', 'bounded_public_proposals', 'current_public_knowledge_request',
                               'executed_actions', 'original_observation_refs'],
            'workflow_invalidations': ['task_change', 'expiry', 'dismissal', 'unconfirmed_or_partial_key', 'later_clipboard_write'],
            'eligibility': ELIGIBILITY_VERSION,
            'usage': 'optional_reference_not_action_requirement',
            'unmatched': 'empty_keyboard_native_actor_decides',
            'selection': selection.policy(),
            'group_semantics': 'atomic_dependencies_alternatives_are_explicit',
            'need_measurement': 'router_estimate_not_ground_truth'}


def validate(value, toolsets):
    if value is None:
        return
    fixed = policy({'instruction': '', 'related_apps': []}, ['general', *toolsets],
                   review_prompt=value.get('review_prompt') if isinstance(value, dict) else None,
                   review_timing=value.get('review_timing') if isinstance(value, dict) else None,
                   review_budget=value.get('review_budget') if isinstance(value, dict) else None,
                   decision_limit=value.get('decision_limit') if isinstance(value, dict) else None)
    variable = {'instruction_sha256', 'task_input_sha256', 'capabilities'}
    if (not isinstance(value, dict) or set(value) != set(fixed)
            or any(value[k] != fixed[k] for k in fixed.keys() - variable)
            or any(not re.fullmatch(r'[0-9a-f]{64}', str(value[k])) for k in variable - {'capabilities'})
            or not isinstance(value['capabilities'], list)
            or value['capabilities'] != sorted(set(value['capabilities']))
            or not set(value['capabilities']) <= set(PATTERNS) | {'file_operations'}):
        raise ValueError('Mini guidance differs from its frozen policy/library')


def chord(event):
    """Only a whole, dispatched key action without failed receipts qualifies."""
    if (event.get('kind') != 'transition' or not event.get('dispatch_observed')
            or event.get('command_alignment') != 'matched' or event.get('gaps') or event.get('error')):
        return None
    receipts = event.get('controller_receipts') or []
    if not receipts:
        return None
    for receipt in receipts:
        result = receipt.get('result')
        if (not isinstance(result, dict) or result.get('success') is False or result.get('error')
                or result.get('status') in ('error', 'failed', 'failure') or result.get('returncode', 0) != 0):
            return None
    args = (event.get('tool') or {}).get('arguments', {})
    if set(args) != {'action', 'keys'} or args['action'] != 'key':
        return None
    keys = args['keys']
    if isinstance(keys, str):
        keys = keys.lower().split('+')
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys) or len(set(keys)) != len(keys):
        return None
    return tuple(sorted(keys))


def workflow(rows, instruction, step):
    """Rebuild from the bounded same-episode journal, never replay actions.

    step counts actor decisions (including empty decisions). Task changes,
    Escape, failed clipboard calls, later clipboard writes and TTL invalidate
    state. Unobserved application changes remain conditional, not invented.
    """
    state = None
    invalidations = []
    for seq, event, _ in sorted(rows):
        if event.get('kind') == 'task_input' and event.get('instruction') != instruction:
            state = None
            invalidations.append({'ref': seq, 'reason': 'task_changed'})
            continue
        if event.get('instruction') != instruction:
            continue
        key = chord(event)
        raw = (event.get('tool') or {}).get('arguments', {})
        if raw.get('action') in ('key', 'key_down', 'key_up') and key is None:
            if state:
                invalidations.append({'ref': seq, 'reason': 'unconfirmed_or_partial_key'})
            state = None  # Conservative: modifier/clipboard state may have changed.
        if key == ('escape',):
            state = None
            invalidations.append({'ref': seq, 'reason': 'dismissed'})
        if key in (('c', 'ctrl'), ('ctrl', 'x'), ('ctrl', 'v')):
            phase = 'verify' if key == ('ctrl', 'v') else 'pending_paste'
            state = {'phase': phase, 'ref': seq, 'started_step': event['step'],
                     'expires_step': event['step'] + (VERIFY_TTL if phase == 'verify' else TTL),
                     'effect_status': 'unknown'}
    if state and step > state['expires_step']:
        invalidations.append({'ref': state['ref'], 'reason': 'expired'})
        state = None
    return state, invalidations


def guide(name, evidence, *, library=LIBRARY):
    entry = library['guides'][name]
    recipes = [{'id': 'k-' + digest({'platform': library['platform'], 'scope': entry['scope'],
                'source': library['sources'][entry['source']], **library['bindings'][binding]})[:12],
                'tool': {'action': 'key', 'keys': library['bindings'][binding]['keys']},
                'intent': library['bindings'][binding]['intent']} for binding in entry['bindings']]
    identity = digest({'name': name, 'entry': entry, 'recipes': recipes,
                       'source': library['sources'][entry['source']], 'platform': library['platform']})
    return {'grade': 'operation_guidance', 'guide_id': name + ':' + identity[:12],
            'scope': entry['scope'], 'recipes': recipes, 'steps': entry['steps'],
            **model_structure(structure(entry)),
            'source': library['sources'][entry['source']], 'evidence': [{'ref': n} for n in sorted(set(evidence))],
            'applicability': 'conditional_verify_app_and_focus', **(
                {'alternatives': entry['alternatives']} if 'alternatives' in entry else {})}


def model_card(record):
    """Keep every actionable field; source URL and ranking stay in local audit."""
    result = {k: deepcopy(v) for k, v in record.items() if k not in ('source', 'basis', 'applicability')}
    result['source_ref'] = 's-' + digest(record['source'])[:12]
    # A short precondition replaces the verbose internal applicability enum.
    result['when'] = 'Verify app, scope and focus in the current image.'
    return result


def repeated_cycle(actions, observations):
    """A short exact action-and-image cycle; no semantic failure classifier.

    Two cycles of 1..3 actions must have the same parameters and before/after
    pixels. Clipboard, typing and changing-page scrolls cannot trigger it.
    """
    signatures, refs = [], []
    for seq, event in actions[:6]:
        args = (event.get('tool') or {}).get('arguments', {})
        allowed = args.get('action') in ('left_click', 'double_click', 'triple_click', 'scroll')
        if args.get('action') == 'key':
            allowed = chord(event) in (('super',), ('win',), ('alt', 'f10'))
        receipts = event.get('controller_receipts') or []
        if (not allowed or not event.get('dispatch_observed') or event.get('command_alignment') != 'matched'
                or event.get('gaps') or event.get('error') or not receipts
                or any(not isinstance(r.get('result'), dict) or r['result'].get('success') is False
                       or r['result'].get('error') or r['result'].get('returncode', 0) != 0
                       or r['result'].get('status') in ('failed', 'error', 'failure') for r in receipts)):
            break
        pair = [observations.get(event.get(k)) for k in ('source', 'target')]
        if not all(pair):
            break
        hashes = [p[1].get('images', {}).get('original', {}).get('sha256') for p in pair]
        if not all(isinstance(h, str) and re.fullmatch('[a-f0-9]{64}', h) for h in hashes):
            break
        signatures.append((dumps(args), *hashes))
        refs.append(seq)
    for period in range(1, 4):
        if len(signatures) >= 2 * period and signatures[:period] == signatures[period:2*period]:
            return {'period': period, 'action_refs': sorted(refs[:2*period]), 'effect_status': 'unknown',
                    'basis': 'exact_parameters_and_original_pixels'}
    return None


def route(*, instruction, enabled, rows, proposals, step, observation_ref, library=LIBRARY, task_catalog=None,
          frozen_capabilities=None, pending_effect=None, readability=None, adjustment_chain=None,
          proposal_origin='public_proposal', missing_knowledge=None):
    """Rank complete cards, not catalog prefixes. Returns reproducible audit data.

    needed_groups are router estimates, not an oracle for the actual next GUI
    action. All scopes stay conditional unless independently observed elsewhere.
    """
    state, invalidations = workflow(rows, instruction, step)
    boundary = max((seq for seq, e, _ in rows if e.get('kind') == 'task_input'
                    and e.get('instruction') != instruction), default=0)
    task_semantics = analyze(instruction)
    task_ops = set(task_semantics['actions'])
    reading_goal = bool(task_ops & {'reading', 'readability'}) and not task_ops & {'zoom_value', 'image_edit'}
    frozen = set(capabilities(instruction) if frozen_capabilities is None else frozen_capabilities)
    candidates, excluded = {}, []
    gaps, semantic_audit = [], [{'origin': 'original_task', **task_semantics}]
    knowledge = selection.gap_request(missing_knowledge)

    def live_state(value, kind):
        if not value:
            return value
        expiry = value.get('expires_step')
        refs = set(value.get('refs', [])) | {e['ref'] for e in value.get('evidence', [])}
        refs |= {value[k] for k in ('ref', 'before') if type(value.get(k)) is int}
        if (expiry is not None and (type(expiry) is not int or step > expiry)) or any(r <= boundary for r in refs):
            excluded.append({'guide': kind, 'reason': 'expired_or_outside_task_state', 'missing': [],
                             'evidence': [{'ref': r} for r in sorted(refs)]})
            return None
        return value

    pending_effect = live_state(pending_effect, 'pending_effect')
    readability = live_state(readability, 'readability_report')
    adjustment_chain = live_state(adjustment_chain, 'adjustment_chain')
    observations = {e.get('id'): (seq, e) for seq, e, _ in rows if e.get('kind') == 'observation' and e.get('id')}
    observed = []
    actions = [(seq, e) for seq, e, _ in sorted(rows, reverse=True)
               if seq > boundary and e.get('kind') == 'transition' and e.get('instruction') == instruction]
    for seq, event in actions[:2]:
        pair = [observations.get(event.get(key)) for key in ('source', 'target')]
        if all(pair):
            hashes = [item[1].get('images', {}).get('original', {}).get('sha256') for item in pair]
            if all(isinstance(h, str) and re.fullmatch(r'[a-f0-9]{64}', h) for h in hashes):
                observed.append({'ref': seq, 'before': pair[0][0], 'after': pair[1][0],
                                 'pixels': 'same' if hashes[0] == hashes[1] else 'different',
                                 'effect_status': 'unknown'})
    from .keyboard_view import active_catalog, SOURCES, DATA
    catalog = active_catalog([key for key in enabled if key != 'general'], task_catalog)
    context = {'ops': set(), 'text': '', 'phase': None}

    def reject(name, reason, refs=(), missing=()):
        value = {'guide': name, 'reason': reason, 'missing': sorted(missing),
                 'evidence': [{'ref': n} for n in sorted({observation_ref, *refs})]}
        excluded.append(value)
        if reason in ('capability_not_frozen', 'directory_not_frozen', 'no_audited_operation_contract',
                      'software_target_not_established', 'temporary_catalog_requires_audited_contract'):
            gaps.append(value)

    def catalog_card(topic, selected, origin, refs, *, requested=False):
        reason = software_reason(owner(topic), context['text'], DATA)
        if reason:
            reject('catalog.' + topic, reason, refs)
            return
        applicable = []
        for recipe in selected:
            op = catalog_operation(recipe)
            if op is None:
                reject('catalog.' + topic, 'no_audited_operation_contract', refs, ['catalog_binding'])
            elif op not in context['ops']:
                reject('catalog.' + topic, 'operation_mismatch', refs)
            elif op not in frozen:
                reject('catalog.' + topic, 'capability_not_frozen', refs, [op])
            elif contextual_reason({op}, context['text']):
                reject('catalog.' + topic, contextual_reason({op}, context['text']), refs)
            else:
                applicable.append(recipe)
        selected = applicable
        if not selected:
            return
        entry = catalog[topic]
        namespace = task_catalog['identity'] if topic.startswith('task.') else 'permanent'
        sources = ([task_catalog['sources'][k]['url'] for k in entry['sources']] if topic.startswith('task.')
                   else [SOURCES[k] for k in entry['sources']])
        # Independent catalog bindings are alternative operations. Workflow
        # groups are explicitly authored above, never guessed from proximity.
        recipes = catalog_alternatives([{'id': 'k-' + digest({'topic': topic, 'scope': entry['scope'],
                           'platform': library['platform'], 'namespace': namespace,
                           'sources': sources, **r})[:12], **deepcopy(r)} for r in selected])
        body = {'grade': 'operation_guidance', 'scope': entry['scope'], 'recipes': recipes,
                'group_kind': 'alternatives' if len(recipes) > 1 else 'single_operation',
                'steps': 'Choose the applicable binding; do not execute alternatives as a sequence. ' + entry['check'],
                'source': sources, 'evidence': [{'ref': n} for n in sorted({observation_ref, *refs})],
                'applicability': 'conditional_verify_app_and_focus'}
        if selected and all(r['intent'].casefold() in ('zoom in', 'zoom out') for r in selected):
            body['steps'] = ('If already readable, read. Otherwise verify app/focus, use ONE applicable binding once, '
                             'then inspect readability/bounds. Do not chase an arbitrary percentage. ' + entry['check'])
        identity = 'catalog.' + topic + ':' + digest({k: v for k, v in body.items() if k != 'evidence'})[:12]
        body['guide_id'] = identity
        body['basis'] = origin
        topic_owner = owner(topic)
        scope = ('explicit_application' if topic_owner.startswith('app.') else
                 'matching_object_type' if topic_owner.startswith('type.') else 'general_scope')
        ops = sorted({catalog_operation(recipe) for recipe in selected})
        info = selection.contract(ops, [], scope=scope)
        info['binding_operations'] = ops
        selection.merge_candidate(candidates, identity, {'record': body, 'origin': origin, 'workflow': False,
            'contract': info, 'requested_reference': requested})

    def add(name, origin, refs=(), *, requested=False):
        entry = library['guides'][name]
        reason, missing = guide_reason(name, entry, ops=context['ops'], frozen=frozen,
            enabled=enabled, text=context['text'], origin=origin, data=DATA, phase=context['phase'])
        if reason:
            reject(name, reason, refs, missing)
            return False
        value = {'record': guide(name, [observation_ref, *refs], library=library),
                 'origin': origin, 'workflow': bool(entry.get('workflow')) or origin == 'executed_workflow',
                 'contract': selection.contract(entry['operations'], entry['bindings'],
                    scope=selection.scope_for_guide(entry), workflow=entry.get('workflow')),
                 'requested_reference': requested}
        value['record']['basis'] = origin
        selection.merge_candidate(candidates, name, value)
        return True

    def choose(ops, origin, refs=(), file_task=False, text=''):
        context.update(ops=set(ops), text=text, phase=None)
        missing = ops - frozen
        if missing:
            reject(origin, 'capability_not_frozen', refs, missing)
            ops = ops - missing
            context['ops'] = ops
        if 'copy' in ops and ops & {'cut', 'move'}:
            add('files.transfer' if file_task else 'clipboard.transfer', origin, refs)
            ops = ops - {'copy', 'cut', 'move', 'paste', 'transfer'}
        elif 'paste' in ops and ops & {'copy', 'cut', 'move'}:
            moving = bool(ops & {'cut', 'move'})
            name = ('files.move' if moving else 'files.copy') if file_task else (
                'clipboard.move_paste' if moving else 'clipboard.copy_paste')
            add(name, origin, refs)
            ops = ops - {'copy', 'cut', 'move', 'paste', 'transfer'}
        if {'edit', 'confirm'} <= ops:
            add('text.replace_confirm', origin, refs)
            ops = ops - {'edit', 'confirm'}
        # A concrete knowledge gap can request dependencies of this operation,
        # but cannot introduce an unrelated operation or expand frozen scope.
        if 'paste' in knowledge['operations'] or knowledge['workflow_requested']:
            if 'copy' in ops:
                add('files.copy' if file_task else 'clipboard.copy_paste', origin, refs)
            if ops & {'cut', 'move'}:
                add('files.move' if file_task else 'clipboard.move_paste', origin, refs)
        if 'edit' in ops and 'confirm' in knowledge['operations']:
            add('text.replace_confirm', origin, refs)
        for op in sorted(ops):
            names = {'copy': 'files.copy' if file_task else 'clipboard.copy',
                     'cut': 'files.move' if file_task else 'clipboard.cut',
                     'move': 'files.move' if file_task else None,
                     'transfer': 'files.transfer' if file_task else None,
                     'paste': 'clipboard.paste', 'rename': 'files.rename',
                     'capture': 'vlc.capture' if 'app.vlc' in enabled else 'capture.image',
                     'export': 'gimp.export' if 'app.gimp' in enabled else 'export.file',
                     'edit': 'text.edit', 'confirm': 'text.confirm', 'dismiss': 'ui.dismiss',
                     'undo': 'history.undo', 'find': 'document.find', 'open': 'document.open',
                     'save': 'document.save', 'save_as': 'document.save_as', 'down': 'navigation.down', 'up': 'navigation.up',
                     'menu_open': 'menu.open', 'reading': 'document.read', 'maximize': 'window.maximize',
                     'readability': 'view.readability',
                     'horizontal_scroll': 'navigation.horizontal', 'zoom_value': 'view.zoom_value',
                     'zoom_in': 'view.zoom_in', 'zoom_out': 'view.zoom_out',
                     'image_edit': 'image.edit', 'drag': 'pointer.drag',
                     'window_locate': 'window.locate', 'folder_open': 'folder.open',
                     'url_open': 'url.open', 'file_find': 'files.find'}
            # Enabled software is not the current software. Specific export
            # and capture bindings must establish their own target contract.
            if op in ('capture', 'export'):
                add('capture.image' if op == 'capture' else 'export.file', origin, refs)
            if names.get(op):
                add(names[op], origin, refs)
            matched = False
            if op in REFERENCE_INTENTS:
                for topic, entry in sorted(catalog.items()):
                    selected = [r for r in entry['recipes'] if r['intent'].casefold() == REFERENCE_INTENTS[op]]
                    if selected:
                        catalog_card(topic, selected, origin, refs)
                        matched = True
            if not names.get(op) and not matched:
                gaps.append({'reason': 'no_enabled_recipe', 'missing': [op],
                             'evidence': [{'ref': n} for n in sorted({observation_ref, *refs})]})

    fresh = []
    for seq, text, ds in sorted(proposals, reverse=True):
        if seq <= boundary or not 0 <= step - ds <= 2:
            reject('public_proposal', 'outside_task_boundary' if seq <= boundary else 'expired_public_intention', [seq])
        else:
            fresh.append((seq, text, ds))
    # Original goals freeze the capability universe; fresh public prose picks
    # the immediate need. Older intentions cannot compete with the newest one.
    if not fresh:
        initial = immediate_actions(task_semantics)
        # An unordered multi-stage task establishes capabilities, not which
        # stage is visible. Do not break that ambiguity by directory ordering.
        families = [set('copy cut paste move transfer rename folder_open file_find'.split()),
                    set('reading readability zoom_in zoom_out zoom_value maximize down up horizontal_scroll'.split()),
                    {'capture'}, {'export', 'save', 'save_as'}, {'image_edit', 'undo'},
                    {'open', 'window_locate', 'url_open', 'window_switch'}, {'edit', 'confirm'}]
        if sum(bool(initial & family) for family in families) > 1:
            gaps.append({'reason': 'current_phase_unspecified', 'missing': ['current_phase'],
                         'evidence': [{'ref': observation_ref}]})
        else:
            choose(initial, 'original_task', file_task=task_semantics['file_context'], text=instruction)
    current_semantics = analyze(fresh[0][1]) if fresh else task_semantics
    current_ops = immediate_actions(current_semantics)
    current_text = current_semantics['text'] or instruction
    reading_ops = {'reading', 'readability', 'zoom_in', 'zoom_out', 'zoom_value', 'maximize', 'down', 'up', 'horizontal_scroll'}
    readable_now = (readability and readability['state'] == 'readable' and 'zoom_value' not in task_ops
                    and not (current_ops - reading_ops))
    for position, (seq, text, decision_step) in enumerate(fresh):
        if seq <= boundary or not 0 <= step - decision_step <= 2:
            continue
        parsed = analyze(text)
        semantic_audit.append({'origin': proposal_origin, 'ref': seq, **parsed})
        if position:
            reject('public_proposal', 'superseded_public_intention', [seq])
            continue
        choose(immediate_actions(parsed), proposal_origin, [seq],
               file_task=parsed['file_context'], text=parsed['text'])
        if any(item['kind'] in ('non_clipboard_expression', 'unreadable') for item in parsed['states']):
            context['ops'] = {'readability'}
            add('view.readability', 'reported_clipping_unverified', [seq])
            context['ops'] = immediate_actions(parsed)
        if position == 0:
            lookup = re.findall(r'<key_lookup>([a-z0-9_.]+)</key_lookup>', text or '')
            if (len(lookup) == 1 and (text or '').count('<key_lookup') == 1
                    and (text or '').count('</key_lookup>') == 1):
                name = lookup[0]
                if name in library['guides']:
                    add(name, 'explicit_lookup', [seq], requested=True)
                elif name.removeprefix('catalog.') in catalog:
                    topic = name.removeprefix('catalog.')
                    if topic in ('file_transfer', 'type.file_manager.file_transfer'):
                        add('files.transfer', 'explicit_lookup', [seq], requested=True)
                    else:
                        requested = {REFERENCE_INTENTS[op] for op in context['ops'] if op in REFERENCE_INTENTS}
                        recipes = catalog[topic]['recipes']
                        matching = [r for r in recipes if r['intent'].casefold() in requested]
                        if requested and not matching:
                            gaps.append({'reason': 'lookup_binding_unavailable', 'topic': topic,
                                'missing': sorted(op for op in parsed['actions'] if op in REFERENCE_INTENTS),
                                'evidence': [{'ref': seq}]})
                        else:
                            catalog_card(topic, matching or recipes, 'explicit_lookup', [seq], requested=True)
                else:
                    gaps.append({'reason': 'lookup_not_enabled_or_unknown', 'missing': ['lookup_unavailable'], 'topic': name,
                                 'evidence': [{'ref': seq}]})
    # Existing image hashes can expose literal repetition without an OCR or
    # semantic app detector. Do not treat unchanged copy/cut images as failure.
    cycle = repeated_cycle(actions, observations)
    # Literal repetition stays in the audit. It does not establish a keyboard
    # need and must not manufacture a generic refocusing card. Source-bound
    # execution conditions, where present, are delivered through Current.
    # A concrete pending action takes priority over a generic re-grounding
    # card. Its focus remains conditional and its exact provenance is audited.
    if pending_effect:
        name = 'view.zoom_confirm' if pending_effect['phase'] == 'confirm_once' else 'view.zoom_check'
        context.update(ops={'zoom_value'}, text=current_text, phase=pending_effect['phase'])
        add(name, 'executed_zoom_effect_unconfirmed', pending_effect['refs'])
    elif reading_goal:
        # A model's chosen percentage does not make it a user requirement.
        # Keep the proposal locally, but first inspect whether adjustment is
        # needed. Explicit precise-ratio tasks and image editing are excluded.
        if 'view.zoom_value' in candidates:
            old = candidates.pop('view.zoom_value')
            refs = [e['ref'] for e in old['record']['evidence']]
            context.update(ops={'readability'}, phase=None)
            add('view.readability', 'readability_before_proposed_ratio', refs)
            excluded.append({'guide': 'view.zoom_value', 'reason': 'proposed_ratio_not_task_requirement'})
        if adjustment_chain:
            context.update(ops={'readability'}, phase=None)
            add('view.readability', 'reading_adjustment_effect_unconfirmed',
                [e['ref'] for e in adjustment_chain['evidence']])
    # A source-bound readability report is conditional advice, not visual
    # certification. It can retire an arbitrary zoom target, never a task's
    # explicitly required precise ratio. Pending input stays in local audit.
    if readable_now:
        context.update(ops={'reading'}, phase=None)
        add('document.read', 'public_readability_report_unverified',
            [readability['ref'], readability['before']])
    if pending_effect:
        # Neither stale prose nor an explicit lookup may restart a completed
        # entry stage; retain excluded candidates in audit for diagnosis.
        for key, value in list(candidates.items()):
            if key in ('view.zoom_value', 'view.zoom_in', 'view.zoom_out') or (
                    value['record']['guide_id'].startswith('catalog.') and value['record']['recipes']
                    and all(r['intent'].casefold() in ('zoom in', 'zoom out') for r in value['record']['recipes'])):
                del candidates[key]
                excluded.append({'guide': key, 'reason': 'superseded_by_pending_zoom_phase'})
    if state:
        needs = {'paste'} if state['phase'] == 'pending_paste' else set()
        if needs - frozen:
            gaps.append({'reason': 'executed_need_not_frozen', 'missing': sorted(needs - frozen),
                         'evidence': [{'ref': state['ref']}]})
        # Old copy/paste prose no longer describes the next phase. A genuinely
        # new clipboard action starts a new state at the next journal boundary.
        for name in ('clipboard.copy', 'clipboard.cut', 'clipboard.paste', 'files.copy', 'files.move', 'files.transfer',
                     'clipboard.copy_paste', 'clipboard.move_paste', 'clipboard.transfer'):
            if name in candidates:
                del candidates[name]
                excluded.append({'guide': name, 'reason': 'superseded_by_execution_phase'})
        name = 'clipboard.verify' if state['phase'] == 'verify' else 'clipboard.paste'
        # Explicit legacy clipboard lookups also cannot revive the earlier
        # phase. Other catalog lookups remain available as supplemental advice.
        for key, value in list(candidates.items()):
            if value['record']['guide_id'].startswith('catalog.clipboard:'):
                del candidates[key]
                excluded.append({'guide': key, 'reason': 'superseded_by_execution_phase'})
        # A destination-entry/dismissal proposal can be more immediate than
        # paste; keep paste as a candidate without pretending focus is ready.
        context.update(ops={'paste'}, text=current_text, phase=state['phase'])
        if add(name, 'executed_workflow', [state['ref']]):
            candidates[name]['record']['workflow'] = {k: v for k, v in state.items() if k != 'started_step'}
    # Phase compatibility is a named rule, never a numeric preference.
    phase_names = None
    phase_kind = 'clipboard_' + state['phase'] if state else 'unconstrained'
    if readable_now:
        phase_names = {'document.read'}
        phase_kind = 'readable_report'
    elif pending_effect:
        phase_names = {'view.zoom_confirm' if pending_effect['phase'] == 'confirm_once' else 'view.zoom_check'}
        phase_kind = 'zoom_' + pending_effect['phase']
    elif adjustment_chain and reading_goal:
        phase_names = {'view.readability'}
        phase_kind = 'view_adjustment_inspection'
    if phase_names:
        for key in list(candidates):
            if key not in phase_names:
                del candidates[key]
                reject(key, 'incompatible_with_current_phase')
    phase = {'kind': phase_kind, 'allowed': sorted(phase_names) if phase_names is not None else None,
             'readability_is': 'unverified_public_report', 'effect_status': 'unknown'}
    ordered, uncovered, explanation = selection.select(list(candidates.values()), current_ops=current_ops,
        phase=phase, gap=knowledge, frozen=frozen)
    excluded.extend(uncovered)
    if knowledge['provided'] and not ordered:
        gaps.append({'reason': 'knowledge_gap_not_covered',
            'missing': sorted(set(knowledge['requirements']) | set(knowledge['operations'])) or ['knowledge_gap'],
            'evidence': [{'ref': n} for n in sorted({observation_ref, *(p[0] for p in fresh[:1])})]})
    sources = {}
    for candidate in ordered:
        alias, source = model_card(candidate['record'])['source_ref'], candidate['record']['source']
        if alias in sources and sources[alias] != source:
            raise ValueError('Guidance short source identity collision')
        sources[alias] = source
    return {'version': VERSION, 'groups': ordered, 'workflow': state, 'invalidations': invalidations,
            'excluded': excluded, 'needed_groups': [ordered[0]['record']['guide_id']] if ordered else [],
            'selection_status': 'matched' if ordered else 'no_match',
            'selection_explanation': explanation,
            'coverage_gaps': gaps, 'semantic_audit': semantic_audit, 'guide_sources': sources, 'literal_cycle': cycle,
            'need_basis': 'deterministic_router_estimate_not_ground_truth',
            'enabled_directories': sorted(set(enabled)), 'observation_ref': observation_ref,
            'observed_deltas': observed}


def delivery_audit(selection, records, directory_visible, delivered=False):
    by_id = {r['guide_id']: r for r in records}
    needed = [c for c in selection['groups'] if c['record']['guide_id'] in selection['needed_groups']]
    expected_recipes = {r['id']: r for c in needed for r in c['record']['recipes']}
    needed_recipes = set(expected_recipes)
    sent_recipes = {r['id'] for c in records for r in c['recipes']
                    if expected_recipes.get(r['id']) == r} if delivered else set()
    def equal(actual, expected):
        return actual == expected or actual == model_card(expected)
    completed = [c['record']['guide_id'] for c in needed if delivered and equal(by_id.get(c['record']['guide_id']), c['record'])]
    workflows = [c['record']['guide_id'] for c in needed if c['workflow'] or c['origin'] == 'executed_workflow']
    eligible = {c['record']['guide_id']: c['record'] for c in selection['groups']}
    invalid = sum(r['guide_id'] not in eligible or not equal(r, eligible[r['guide_id']]) for r in records) if delivered else 0
    return {'packet_delivered': delivered, 'directory_visible': delivered and directory_visible,
            'selection_status': selection.get('selection_status', 'matched' if selection['groups'] else 'no_match'),
            'matching_group_count': len(selection['groups']),
            'coverage_gap_count': len(selection.get('coverage_gaps', [])),
            'needed_recipe_count': len(needed_recipes), 'needed_recipes_delivered': len(needed_recipes & sent_recipes),
            'needed_group_count': len(needed), 'needed_groups_delivered': len(completed),
            'workflow_group_count': len(workflows), 'complete_workflow_groups': len(set(workflows) & set(completed)),
            'delivered_group_ids': sorted(by_id) if delivered else [],
            'needed_recipe_delivery_rate': len(needed_recipes & sent_recipes) / len(needed_recipes) if needed_recipes else None,
            'workflow_completeness_rate': len(set(workflows) & set(completed)) / len(workflows) if workflows else None,
            'known_stale_or_inapplicable_rate': invalid / len(records) if delivered and records else None,
            'applicability_unknown_groups': len(records) - invalid if delivered else 0,
            'known_stale_or_inapplicable_groups': invalid, 'semantic_inapplicability_rate': None,
            'need_basis': selection['need_basis'], 'adoption': 'unknown_parameter_match_is_not_use'}
