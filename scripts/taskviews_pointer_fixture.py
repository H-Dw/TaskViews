"""Reversible input fixture. Only physical mouse-release events change progress."""
import inspect
import textwrap

from ui_kobe.osworld.pointer_checks import rectangles, validate_case


def run_canvas(spec, target):
    import json
    import os
    from pathlib import Path
    import time
    import tkinter as tk

    path = Path(target)
    if path.exists():
        raise RuntimeError('Refuse an existing observer log')
    root = tk.Tk()
    root.title('Pointer Lab')
    root.attributes('-fullscreen', True)
    canvas = tk.Canvas(root, bg='#f1f4f8', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    root.update()
    screen = [canvas.winfo_width(), canvas.winfo_height()]
    origin = [canvas.winfo_rootx(), canvas.winfo_rooty()]
    if screen != spec['screen_size'] or origin != [0, 0]:
        raise RuntimeError('Fixture requires the original 1920x1080 global frame')
    state = {'case_id': spec['id'], 'screen_size': screen, 'window_origin': origin,
             'initial_accepted': [], 'accepted': [], 'events': [], 'ready': True}
    status = 'No clicks yet'

    def persist():
        temporary = path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump(state, stream)
            stream.write(chr(10))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def draw():
        canvas.delete('all')
        done = len(state['accepted'])
        next_label = spec['targets'][done] if done < len(spec['targets']) else 'Complete'
        canvas.create_text(45, 28, anchor='w', text='Pointer Lab — mouse controls', font=('Sans', 18, 'bold'), fill='#17253a')
        canvas.create_text(45, 63, anchor='w', text=f'Accepted {done}/{len(spec["targets"])} | Next: {next_label} | {status}', font=('Sans', 15), fill='#17253a')
        for label, box in rectangles(spec, done).items():
            canvas.create_rectangle(*box, fill='#295e91', outline='#153650', width=2)
            canvas.create_text((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, text=label, fill='white', font=('Sans', 16, 'bold'))
        if done == len(spec['targets']):
            canvas.create_text(960, 310, text='All requested clicks accepted', font=('Sans', 22, 'bold'), fill='#116344')

    def released(event):
        nonlocal status
        revision = len(state['accepted'])
        boxes = rectangles(spec, revision)
        point = [event.x_root, event.y_root]
        hits = [label for label, box in boxes.items() if box[0] <= point[0] < box[2] and box[1] <= point[1] < box[3]]
        hit = hits[0] if len(hits) == 1 else None
        expected = spec['targets'][revision] if revision < len(spec['targets']) else None
        accepted = hit is not None and hit == expected
        state['events'].append({'seq': len(state['events']) + 1, 'kind': 'mouse_release', 'button': 1,
            'revision': revision, 'screen_point': point, 'rectangles': boxes,
            'hit': hit, 'accepted': accepted, 'time_monotonic': time.monotonic()})
        if accepted:
            state['accepted'].append(hit)
            status = 'Accepted ' + hit
        else:
            status = 'Missed a control' if hit is None else 'Wrong order: ' + hit
        persist()
        draw()

    canvas.bind('<ButtonRelease-1>', released)
    # Keyboard activation and terminal/application APIs are not wired to progress.
    persist()
    draw()
    root.mainloop()


def pointer_setup_command(spec):
    validate_case(spec)
    program = ('spec = ' + repr(spec) + '\ntarget = ' + repr(spec['expected_guest_artifact'])
               + '\n' + inspect.getsource(rectangles) + '\n' + inspect.getsource(run_canvas)
               + '\nrun_canvas(spec, target)\n')
    command = textwrap.dedent('''
        import importlib.util, json, os, subprocess, time
        if importlib.util.find_spec('tkinter') is None:
            raise RuntimeError('Guest tkinter unavailable; no model request made')
        if os.path.exists(target):
            raise RuntimeError('Existing pointer result would contaminate the fixture')
        script = '/tmp/' + case_id + '.py'
        if os.path.exists(script):
            raise RuntimeError('Pointer fixture script already exists')
        with open(script, 'x') as stream:
            stream.write(program)
        log = open(script + '.log', 'xb')
        child = subprocess.Popen(['/usr/bin/python3', script], env=dict(os.environ, DISPLAY=':0'), stdout=log, stderr=log)
        until = time.monotonic() + 20
        while time.monotonic() < until and not os.path.exists(target):
            if child.poll() is not None:
                raise RuntimeError('Pointer fixture exited before initial readiness')
            time.sleep(.2)
        with open(target) as stream:
            initial = json.load(stream)
        if not initial['ready'] or initial['accepted'] or initial['events']:
            raise RuntimeError('Pointer fixture did not begin with empty mouse state')
        print(json.dumps({'initialization_only': True, 'pid': child.pid,
            'input_fixture_precreated': True, 'target_answer_precreated': False,
            'case_id': case_id, 'screen_size': initial['screen_size'], 'initial_events': 0}))
    ''')
    return ('target = ' + repr(spec['expected_guest_artifact']) + '\ncase_id = ' + repr(spec['id'])
            + '\nprogram = ' + repr(program) + '\n' + command)
