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


def current_frame_content(frame):
    landmarks = ''
    if frame.metadata['coordinate_type'] == 'absolute':
        width, height = frame.metadata['model_size']
        landmarks = (f'\nPixel landmarks for this image: upper-left [0, 0], '
            f'center [{width // 2}, {height // 2}], last pixel [{width - 1}, {height - 1}]. '
            'These are unit examples, never target locations. Locate each UI control visually.')
    return [{'type': 'text', 'text': frame.instruction + landmarks + '\n\n' + POINTER_WORKFLOW}, frame.image]
