"""Categorical selection of admitted cards; no weights or numeric priorities.

Earlier layers partition candidates before later layers. A good fit at a
later layer cannot compensate for a worse fit at an earlier one. Complete
records, including their evidence, remain intact; explanations stay local.
"""
from copy import deepcopy
import re

from .guidance_semantics import analyze

VERSION = 'layered_guidance_selection_v1'
LAYERS = ('phase', 'intent_match', 'software_object', 'knowledge_gap')
BRANCHES = {
    'phase': ('current_stage', 'current_prerequisite', 'post_action_check', 'pending_continuation', 'unconstrained'),
    'intent_match': ('requested_reference', 'complete_operation', 'partial_operation', 'execution_dependency', 'goal_support'),
    'software_object': ('explicit_application', 'matching_object_type', 'general_scope'),
    'knowledge_gap': ('fully_covered', 'alternative_covered', 'unspecified'),
}
BINDING_OPS = {
    'copy': {'copy'}, 'cut': {'cut', 'move'}, 'paste': {'paste'}, 'select_text': {'edit'},
    'confirm': {'confirm', 'zoom_value'}, 'dismiss': {'dismiss'}, 'undo': {'undo'},
    'find': {'find'}, 'open': {'open'}, 'save': {'save'}, 'page_down': {'down'}, 'page_up': {'up'},
    'rename': {'rename'}, 'vlc_snapshot': {'capture'}, 'gimp_export': {'export'},
    'maximize': {'maximize'}, 'save_as': {'save_as'},
}


def policy():
    return {'version': VERSION, 'admission': 'applicability_sources_lifetime_then_current_phase',
            'layers': list(LAYERS), 'branches': {k: list(v) for k, v in BRANCHES.items()}, 'tie_break': 'stable_content_id',
            'numeric_priorities': False, 'gap_semantics': 'public_requirements_no_new_capabilities_v1'}


def gap_request(text):
    """Recognize bounded knowledge requirements, not a new action plan."""
    text = text if isinstance(text, str) else ''
    needs = []
    if re.search(r'\b(?:bindings?|shortcuts?|hotkeys?|keys?|keybinding)\b|按键|快捷键|键名', text, re.I):
        needs.append('binding')
    if re.search(r'\b(?:procedures?|workflows?|steps?|sequence|parameters?|arguments?|how)\b|流程|步骤|方法|参数', text, re.I):
        needs.append('procedure')
    if re.search(r'\b(?:checks?|verify|verification|inspect|effect)\b|检查|验证|效果', text, re.I):
        needs.append('result_check')
    return {'requirements': needs, 'operations': analyze(text)['actions'],
            'relation': 'any' if len(needs) > 1 and re.search(r'\b(?:or|either)\b|或者|或', text, re.I) else 'all',
            'workflow_requested': bool(re.search(r'\b(?:workflow|sequence)\b|完整流程|全流程', text, re.I)),
            'provided': bool(text.strip())}


def contract(primary, bindings, *, scope='general_scope', workflow=False):
    binding_ops = set().union(*(BINDING_OPS.get(b, set()) for b in bindings))
    return {'operations': sorted(primary), 'binding_operations': sorted(binding_ops),
            'covered_operations': sorted(set(primary) | binding_ops), 'software_object': scope,
            'workflow': bool(workflow)}


def merge_candidate(candidates, key, value):
    """Reuse identical content and union its provenances instead of choosing a weight."""
    old = candidates.get(key)
    if old is None:
        candidates[key] = value
        value['origins'] = [value['origin']]
        return
    old['origins'] = sorted(set(old['origins']) | {value['origin']})
    refs = {x['ref'] for c in (old, value) for x in c['record']['evidence']}
    old['record']['evidence'] = [{'ref': n} for n in sorted(refs)]
    old['requested_reference'] |= value['requested_reference']
    old['workflow'] |= value['workflow']


def scope_for_guide(entry):
    required = entry.get('requires', [])
    if any(k.startswith('app.') for k in required):
        return 'explicit_application'
    if any(k.startswith('type.') for k in required):
        return 'matching_object_type'
    return 'general_scope'


def partition_order(candidates, layers=LAYERS):
    """Stable ordered partitions: not a sum, ordinal tuple, or hidden score."""
    if not layers:
        return sorted(candidates, key=lambda c: c['record']['guide_id'])
    layer, *rest = layers
    if any(c['criteria'][layer] not in BRANCHES[layer] for c in candidates):
        raise ValueError('Unknown guidance selection branch: ' + layer)
    return [c for branch in BRANCHES[layer]
            for c in partition_order([x for x in candidates if x['criteria'][layer] == branch], rest)]


def select(candidates, *, current_ops, phase, gap, frozen):
    """Apply named phase roles, demand matching and declared gap coverage."""
    chosen, rejected = [], []
    reading = {'reading', 'readability'}
    explicit_origins = {'public_proposal', 'public_knowledge_request', 'explicit_lookup'}
    prerequisite = any(set(c['origins']) & explicit_origins and 'executed_workflow' not in c['origins']
                       for c in candidates)
    for item in candidates:
        c = deepcopy(item)
        info, record = c['contract'], c['record']
        primary, covered = set(info['operations']), set(info['covered_operations'])
        if phase['allowed'] is not None:
            phase_role = 'current_stage'
        elif 'executed_workflow' in c['origins']:
            phase_role = 'post_action_check' if phase['kind'] == 'clipboard_verify' else 'pending_continuation'
        elif phase['kind'] == 'clipboard_pending_paste' and prerequisite and set(c['origins']) & explicit_origins:
            phase_role = 'current_prerequisite'
        else:
            phase_role = 'unconstrained'
        if c['requested_reference']:
            match = 'requested_reference'
        elif primary <= reading and current_ops - reading:
            match = 'goal_support'
        elif current_ops and current_ops <= covered:
            match = 'complete_operation'
        elif primary & current_ops:
            match = 'partial_operation'
        elif phase_role != 'unconstrained':
            match = 'execution_dependency'
        else:
            match = 'goal_support'
        requirements, requested_ops = gap['requirements'], set(gap['operations'])
        binding_targets = requested_ops or current_ops or primary
        signals = {
            'binding': bool(set(info['binding_operations']) & binding_targets),
            'procedure': bool(record.get('steps')) and (not gap['workflow_requested'] or info['workflow']),
            'result_check': bool(re.search(r'\b(?:inspect|check|verify|observe|reopen)\b|检查|验证', record.get('steps', ''), re.I)),
        }
        missing = [need for need in requirements if not signals[need]]
        ops_missing = requested_ops - covered
        frozen_missing = requested_ops - set(frozen)
        if frozen_missing or ops_missing or (requirements and (len(missing) == len(requirements)
                if gap['relation'] == 'any' else bool(missing))):
            rejected.append({'guide': record['guide_id'], 'reason': 'knowledge_gap_not_covered',
                'missing': sorted(set(missing) | ops_missing | frozen_missing),
                'evidence': deepcopy(record['evidence'])})
            continue
        coverage = ('unspecified' if not requirements and not requested_ops else
                    'alternative_covered' if missing else 'fully_covered')
        c['criteria'] = {'phase': phase_role, 'intent_match': match,
                         'software_object': info['software_object'], 'knowledge_gap': coverage}
        c['gap_coverage'] = {'requirements': {k: signals[k] for k in requirements},
                             'requested_operations': sorted(requested_ops), 'status': coverage}
        chosen.append(c)
    ordered = partition_order(chosen)
    comparisons = []
    if ordered:
        best = ordered[0]
        for other in ordered[1:]:
            layer = next((k for k in LAYERS if best['criteria'][k] != other['criteria'][k]), 'stable_content_id')
            comparisons.append({'preferred': best['record']['guide_id'], 'alternative': other['record']['guide_id'],
                'deciding_layer': layer, 'preferred_branch': best['criteria'].get(layer),
                'alternative_branch': other['criteria'].get(layer)})
    return ordered, rejected, {'policy': VERSION, 'phase': deepcopy(phase), 'knowledge_request': deepcopy(gap),
        'winner': ordered[0]['record']['guide_id'] if ordered else None,
        'winner_criteria': deepcopy(ordered[0]['criteria']) if ordered else None,
        'comparisons': comparisons}
