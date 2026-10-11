"""Mandatory current-frame instructions, separate from optional TaskViews data.

This changes actor input only. It never transforms coordinates, chooses a
control, changes the official tool schema, or grants an adviser execution power.
"""

POINTER_WORKFLOW = """Current-frame pointer workflow:
Follow the declared coordinate unit for this image, even if familiar models use
0..1000. In an absolute contract, output image pixels; do not normalize them.
Locate the intended visible control anew in this frame. Old action coordinates
are historical parameters, not a locator for the current control.
When a location or focus is uncertain, make one GUI action and inspect the new
image before dependent typing or submission. A returned command does not prove
focus, text entry, a changed directory, or a completed save. After an unchanged
result, re-ground the control or choose a normal visible keyboard route; avoid
another blind click. A visible window does not prove keyboard focus. Establish
application focus and choose keys appropriate to the visible guest desktop,
not conventions from a different host operating system. For a save dialog, distinguish filename, folder and final
confirmation, verifying each visible effect. Never use terminal or scripting.
This contract belongs to the current image; older frame contracts are history."""


def validate_pointer_strategy(arguments, stalled, *, frame_id, keyboard_recovery=False, stalled_keys=()):
    """Reject an exact failed pointer cycle before dispatch; never move a point.

    The shared native compiler validates first. The original repair loop owns
    retries, complete rejected assistants/tool IDs, output admission and time.
    A batch cannot establish new focus before its dependent operations without
    a fresh image. Changed parameters, keys, captures and termination retain
    their original native validation and commands.
    """
    from kobe_views.model import dumps
    from ui_kobe.api.kimi_stream import StreamProtocolError
    for action in arguments:
        if keyboard_recovery and (len(stalled) >= 2 or stalled_keys) and action.get('action') not in {
                'key', 'wait', 'screenshot', 'terminate', 'user_question'}:
            detail = {'frame_id': frame_id, 'rejected_parameters': action,
                'failed_transition_ids': [identity for row in [*stalled, *stalled_keys]
                                          for identity in row['transition_ids']],
                'grade': 'model_proposal', 'repair':
                    'Prior pointer or keyboard strategies repeatedly failed to establish a state change. '
                    'Establish application focus with an appropriate guest-desktop keyboard operation '
                    'and inspect its effect before a dependent operation. '
                    'Another pointer guess or dependent typing cannot resolve this uncertainty. '
                    'Do not scale/clamp coordinates, open a terminal, or write a script.'}
            raise StreamProtocolError('Keyboard recovery required: ' + dumps(detail),
                code='pointer_keyboard_recovery', retryable=True)
        match = next((row for row in [*stalled, *stalled_keys] if row['parameters'] == action), None)
        if match:
            detail = {'frame_id': frame_id, 'rejected_parameters': action,
                'transition_ids': match['transition_ids'], 'assessments': match['assessments'],
                'grade': 'model_proposal', 'repair':
                    'These exact operation parameters repeatedly failed to establish the intended effect. '
                    'Re-ground the control in the current image or use a normal application keyboard route. '
                    'Choose one operation and observe its effect before dependent input; '
                    'do not scale, clamp, slightly offset a stale guess, or infer focus from a receipt.'}
            prefix = ('Repeated unconfirmed keyboard strategy' if action['action'] == 'key'
                      else 'Repeated unconfirmed pointer strategy')
            raise StreamProtocolError(prefix + ': ' + dumps(detail),
                code='repeated_unconfirmed_keyboard' if action['action'] == 'key' else 'repeated_unconfirmed_pointer',
                retryable=True)


def current_frame_content(frame):
    landmarks = ''
    if frame.metadata['coordinate_type'] == 'absolute':
        width, height = frame.metadata['model_size']
        landmarks = (f'\nPixel landmarks for this image: upper-left [0, 0], '
            f'center [{width // 2}, {height // 2}], last pixel [{width - 1}, {height - 1}]. '
            'These are unit examples, never target locations. Locate each UI control visually.')
    return [{'type': 'text', 'text': frame.instruction + landmarks + '\n\n' + POINTER_WORKFLOW}, frame.image]
