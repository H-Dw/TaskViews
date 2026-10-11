"""Blank custom-test initialization inside a reversible VM branch, before APIs."""
import inspect
import textwrap


def geogebra_java(argv):
    """Never match a Python command string, unrelated Java app, or guest server."""
    if not argv or argv[0].rsplit('/', 1)[-1] not in {'java', 'java.bin'}:
        return False
    return any(arg.startswith(('geogebra.GeoGebra', 'org.geogebra.desktop.GeoGebra')) or
               ('/GeoGebra-Linux-Portable-' in arg and arg.casefold().endswith('/geogebra.jar'))
               for arg in argv[1:])


def blank_setup_command(executable, blank):
    # This is fixture setup, never actor context or a substitute for model GUI
    # commands. Whole-VM rollback must already be verified by the calling runner.
    code = textwrap.dedent('''
        import os, subprocess, zipfile, json, signal, time
        def argv(pid):
            try:
                with open('/proc/' + str(pid) + '/cmdline', 'rb') as stream:
                    return stream.read().decode(errors='replace').rstrip(chr(0)).split(chr(0))
            except (OSError, ValueError):
                return []
        def windows():
            rows = subprocess.check_output(['wmctrl', '-lxp'], text=True).splitlines()
            return [row.split(None, 5) for row in rows if len(row.split(None, 5)) == 6
                    and 'geogebra' in row.split(None, 5)[3].casefold()]
        prior = {int(pid): argv(pid) for pid in os.listdir('/proc') if pid.isdigit()
                 and geogebra_java(argv(pid))}
        for pid, original in prior.items():
            if argv(pid) == original:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        until = time.monotonic() + 5
        while time.monotonic() < until and any(argv(pid) == original for pid, original in prior.items()):
            time.sleep(.1)
        for pid, original in prior.items():
            if argv(pid) == original and geogebra_java(original):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        time.sleep(.3)
        if windows():
            raise RuntimeError('Prior GeoGebra windows still present; refuse model requests')
        assert os.path.isfile(executable)
        with zipfile.ZipFile(blank, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('geogebra.xml', '<?xml version="1.0"?><geogebra format="5.0" version="5.4.925.0"><construction/></geogebra>')
        log = open('/tmp/taskviews-quick-launch.log', 'ab')
        child = subprocess.Popen([executable, '--versionCheckAllow=false', blank],
            env=dict(os.environ, DISPLAY=':0'), stdout=log, stderr=log)
        until = time.monotonic() + 20
        current = []
        while time.monotonic() < until:
            current = windows()
            if current:
                break
            time.sleep(.2)
        if len(current) != 1:
            raise RuntimeError('Expected one isolated GeoGebra window; refuse model requests')
        window = current[0][0]
        subprocess.run(['wmctrl', '-ir', window, '-b', 'add,maximized_vert,maximized_horz'], check=True)
        subprocess.run(['wmctrl', '-ia', window], check=True)
        time.sleep(1)
        print(json.dumps({'blank_file': blank, 'pid': child.pid,
            'prior_geogebra_java_pids': sorted(prior), 'prior_windows_removed': True,
            'isolated_window_id': window, 'isolated_window_count': len(current),
            'target_object_precreated': False, 'initialization_only': True}))
    ''')
    return ('executable = ' + repr(executable) + '\nblank = ' + repr(blank) + '\n'
            + inspect.getsource(geogebra_java) + '\n' + code)


def blank_text_setup_command(target, *, input_fixture=False):
    """Initialize an empty GUI only; the actor must type/save all target bytes."""
    return 'target = ' + repr(target) + '\ninput_fixture = ' + repr(input_fixture) + '\n' + textwrap.dedent('''
        import json, os, shutil, subprocess, time, hashlib
        if os.path.exists(target):
            raise RuntimeError('Target text file already exists; refuse a contaminated test')
        names = ('gedit', 'gnome-text-editor', 'mousepad', 'xed')
        choices = [(name, shutil.which(name)) for name in names if shutil.which(name)]
        if not choices:
            raise RuntimeError('No supported text editor installed; no model request made')
        name, executable = choices[0]
        def windows():
            rows = [row.split(None, 5) for row in subprocess.check_output(['wmctrl', '-lxp'], text=True).splitlines()]
            return [row for row in rows if len(row) == 6 and
                any(token in row[3].casefold() for token in ('gedit', 'texteditor', 'text-editor', 'mousepad', 'xed'))]
        if windows():
            raise RuntimeError('Prior text editor window present; do not discard its unsaved document')
        initial_input = None
        if input_fixture:
            with open(target, 'xb'):
                pass
            initial_input = {'path': target, 'bytes': os.path.getsize(target),
                'sha256': hashlib.sha256(b'').hexdigest()}
            assert initial_input['bytes'] == 0
        log = open('/tmp/taskviews-quick-text-launch.log', 'ab')
        child = subprocess.Popen([executable] + ([target] if input_fixture else []),
            env=dict(os.environ, DISPLAY=':0'), stdout=log, stderr=log)
        until = time.monotonic() + 20
        current = []
        while time.monotonic() < until:
            current = windows()
            if current:
                break
            time.sleep(.2)
        if len(current) != 1:
            raise RuntimeError('Expected one blank text editor; refuse model requests')
        window = current[0][0]
        subprocess.run(['wmctrl', '-ir', window, '-b', 'add,maximized_vert,maximized_horz'], check=True)
        subprocess.run(['wmctrl', '-ia', window], check=True)
        time.sleep(1)
        print(json.dumps({'editor': name, 'pid': child.pid, 'isolated_window_count': 1,
            'isolated_window_id': window, 'initialization_only': True, 'target_file_precreated': input_fixture,
            'input_fixture_precreated': input_fixture, 'initial_input': initial_input,
            'requested_answer_precreated': False}))
    ''')
