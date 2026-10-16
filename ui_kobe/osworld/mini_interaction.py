"""Mini-only guidance for the pinned compiler/backend boundary.

No command rewriting, GUI inspection, task answers or additional model calls.
Only known silent key aliases are rejected; unknown names retain official policy.
"""
from ui_kobe.api.kimi_stream import StreamProtocolError


VERSION = 'mini_interaction_v1'
SILENT_KEY_ALIASES = {'page_down': 'pagedown', 'page_up': 'pageup', 'minus': '-'}
KEY_GUIDANCE = ('Keyboard view maps intent to exact keys tokens (e.g. pagedown, "-"). '
                'Action-name underscores do not define key names. ')
WORKFLOW_GUIDANCE = (
    'Keep the requested deliverable in view. Revisit resolved reads only for a specific uncertainty. '
    'Typing a name does not confirm a dialog or move a file. Confirm creation, the selected source '
    'and the destination, then verify the result. Batch only predictable actions with established '
    'focus; observe again after layout/window changes.'
)
SCROLL_GUIDANCE = (
    'The pinned compiler passes scroll.pixels directly as wheel ticks, not screen pixels, '
    'and ignores its coordinate. Move the pointer into the target pane first; start with '
    '3-5 ticks and observe before increasing. A blank page alone is not a rendering failure.'
)


def validate_keys(arguments, response):
    from mm_agents.qwen.parser import parse_keys

    for value in arguments:
        if value.get('action') in ('key', 'key_down', 'key_up'):
            for key in parse_keys(value.get('keys')):
                if key in SILENT_KEY_ALIASES:
                    raise StreamProtocolError(
                        f'Key {key!r} is silently ignored by the pinned PyAutoGUI backend; '
                        f'use {SILENT_KEY_ALIASES[key]!r}. Entire batch was not executed.',
                        code='mini_silent_key_alias', observed_response=response.model_dump(), retryable=True)


def interaction_contract():
    return {'version': VERSION, 'grade': 'adapter_semantics_and_workflow_guidance',
            'scroll': 'scroll.pixels = wheel ticks, ignores its coordinate; move pointer first, try 3-5 then observe.',
            'deliverable': 'Typing a name does not confirm a dialog or move a file. Verify the requested final artifact.',
            'visual_effect': 'unknown; controller success only confirms command return'}
