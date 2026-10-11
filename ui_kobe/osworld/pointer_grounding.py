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
another blind click. For a save dialog, distinguish filename, folder and final
confirmation, verifying each visible effect. Never use terminal or scripting.
This contract belongs to the current image; older frame contracts are history."""


def validate_pointer_strategy(arguments, stalled, *, frame_id):
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
        match = next((row for row in stalled if row['parameters'] == action), None)
        if match:
            detail = {'frame_id': frame_id, 'rejected_parameters': action,
                'transition_ids': match['transition_ids'], 'assessments': match['assessments'],
                'grade': 'model_proposal', 'repair':
                    'These exact pointer parameters repeatedly failed to establish the intended effect. '
                    'Re-ground the control in the current image or use a normal application keyboard route. '
                    'Choose one operation and observe its effect before dependent input; '
                    'do not scale, clamp, slightly offset a stale guess, or infer focus from a receipt.'}
            raise StreamProtocolError('Repeated unconfirmed pointer strategy: ' + dumps(detail),
                code='repeated_unconfirmed_pointer', retryable=True)


def current_frame_content(frame):
    landmarks = ''
    if frame.metadata['coordinate_type'] == 'absolute':
        width, height = frame.metadata['model_size']
        landmarks = (f'\nPixel landmarks for this image: upper-left [0, 0], '
            f'center [{width // 2}, {height // 2}], last pixel [{width - 1}, {height - 1}]. '
            'These are unit examples, never target locations. Locate each UI control visually.')
    return [{'type': 'text', 'text': frame.instruction + landmarks + '\n\n' + POINTER_WORKFLOW}, frame.image]
