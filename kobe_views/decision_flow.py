"""Single-actor evidence use and bounded, public operation-knowledge requests."""
from .attempt_retrieval import policy as attempt_policy, retrieve

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
            'attempt_retrieval': attempt_policy()}


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
    """Compatibility entrypoint; the navigation path uses the same gate."""
    return retrieve(rows, instruction, proposals, step)['selected']
