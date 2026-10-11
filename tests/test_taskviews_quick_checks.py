import zipfile

import pytest

from ui_kobe.osworld.quick_checks import GEOGEBRA_POINT, grade_saved_point


def save(path, xml):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('geogebra.xml', xml)


def test_grade_requires_saved_math_object_not_a_receipt_or_visible_title(tmp_path):
    path = tmp_path / 'tv_quick.ggb'
    save(path, '<geogebra><construction><element type="point" label="P1">'
               '<coords x="1" y="2" z="1"/></element></construction></geogebra>')
    assert grade_saved_point(path)['custom_score'] is None
    result = grade_saved_point(path, terminal=True)
    assert result['custom_score'] == 1 and result['official_score'] is None
    assert all(result['checks'].values())
    assert GEOGEBRA_POINT['diagnostic_pause_after_decisions'] < GEOGEBRA_POINT['native_decision_limit']


def test_saved_wrong_point_or_broken_archive_is_a_real_custom_grade_failure(tmp_path):
    path = tmp_path / 'tv_quick.ggb'
    save(path, '<geogebra><construction><element type="point" label="P1">'
               '<coords x="517" y="983" z="1"/></element></construction></geogebra>')
    result = grade_saved_point(path, terminal=True)
    assert result['checks']['saved_file'] and not result['checks']['point_P1'] and result['custom_score'] == 0
    path.write_bytes(b'not a construction')
    assert grade_saved_point(path, cumulative_limit=True)['custom_score'] == 0
    assert grade_saved_point(tmp_path / 'missing.ggb', terminal=True)['custom_score'] == 0


def test_parent_restore_always_stops_cpus_and_does_not_resume_the_agent():
    from scripts.taskviews_quick_live import restore_parent
    class VM:
        def __init__(self, fails=False):
            self.calls, self.fails = [], fails
        def load(self, tag):
            self.calls.append(('load', tag))
            if self.fails:
                raise RuntimeError('snapshot missing')
        def call(self, operation):
            self.calls.append((operation,))
            return {'running': False, 'status': 'paused'}
    vm = VM()
    assert restore_parent(vm, 'parent') == {'running': False, 'status': 'paused'}
    assert vm.calls == [('load', 'parent'), ('stop',), ('query-status',)]
    broken = VM(True)
    with pytest.raises(RuntimeError, match='snapshot missing'):
        restore_parent(broken, 'parent')
    assert broken.calls == [('load', 'parent'), ('stop',)]


def test_blank_initialization_has_no_target_object_or_saving_shortcut():
    import ast
    from scripts.taskviews_quick_live import setup_blank
    class Controller:
        def execute_python_command(self, command):
            self.command = command
            ast.parse(command)
            return {'status': 'success', 'returncode': 0, 'output': ''}
    controller = Controller()
    result = setup_blank(controller, 'fixture-run')
    assert not result['actor_action'] and not result['target_object_precreated']
    assert '<construction/>' in controller.command
    assert 'P1' not in controller.command and 'tv_quick.ggb' not in controller.command
    assert 'wmctrl' in controller.command and 'Prior GeoGebra windows still present' in controller.command
    assert controller.command.index('if windows():') < controller.command.index('subprocess.Popen')


@pytest.mark.parametrize('argv,expected', [
    (['/usr/bin/java', '/home/user/GeoGebra-Linux-Portable-5/geogebra.jar'], True),
    (['java', 'geogebra.GeoGebra3D'], True),
    (['/jre/java.bin', 'org.geogebra.desktop.GeoGebra'], True),
    (['python', '-c', 'java geogebra.GeoGebra3D'], False),
    (['/usr/bin/java', '-jar', '/tmp/unrelated.jar'], False),
    (['/usr/bin/python', '/home/user/server.py'], False),
    (['java', '-Dcaption=geogebra.GeoGebra3D'], False),
])
def test_blank_setup_process_matching_is_limited_to_the_actual_geogebra_java_app(argv, expected):
    from scripts.taskviews_quick_setup import geogebra_java
    assert geogebra_java(argv) is expected


def test_quick_continuation_preserves_history_tool_ids_and_parent_files(tmp_path, monkeypatch):
    from scripts.taskviews_fast_fixture import run_fixture
    from scripts.taskviews_quick_live import restore_quick_actor
    from ui_kobe.osworld.checkpoints import Checkpoints, sha
    from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
    from ui_kobe.api.qwen_native import BASE_URL, MODEL
    from ui_kobe.osworld import telemetry
    original = tmp_path / 'original'
    run_fixture(original)
    source = Checkpoints(original / 'stage', {})
    dest, saved = source.read()
    hashes = {str(p): sha(p) for p in dest.rglob('*') if p.is_file()}
    child = tmp_path / 'child'
    trace = child / 'telemetry'
    trace.mkdir(parents=True)
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR', str(trace))
    monkeypatch.setenv('UI_KOBE_TASK_ID', 'local-feedback-fixture')
    monkeypatch.setenv('UI_KOBE_CHECKPOINT_READS', '1')
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_FEEDBACK_V10', '1')
    monkeypatch.setattr(telemetry, '_root', trace)
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000,
                                    api_key='offline-unused-key', **saved['cua_contract'])
    manager = Checkpoints(child / 'stage', {})
    try:
        restored = restore_quick_actor(manager, actor, original / 'stage', saved['tag'], trace)
        assert restored['completed_steps'] == actor.total_steps == 6
        assert actor.turns == saved['turns'] and actor.pending == saved['pending']
        assert actor.execution_journal.path.is_relative_to(trace)
        assert actor.control.directory.is_relative_to(child / 'stage')
        assert len(actor.modules.modules) == 1
        assert hashes == {str(p): sha(p) for p in dest.rglob('*') if p.is_file()}
    finally:
        actor.close()
        if actor.execution_journal is not None:
            actor.execution_journal.close()
@pytest.mark.parametrize('body, expected', [
    (b'TaskViews quick check', 1), (b'TaskViews quick check\n', 1),
    (b'TaskViews quick check\r\n', 1), (b'TaskViews quick check\n\n', 0),
    (b'TaskViews quick check ', 0), (b'TaskViews quick checks', 0),
    (b'\xff\xfe', 0), (b'x' * 4097, 0)])
def test_text_artifact_exact_content_after_real_terminal(tmp_path, body, expected):
    from ui_kobe.osworld.quick_checks import grade_saved_text
    path = tmp_path / 'delivered.txt'
    path.write_bytes(body)
    assert grade_saved_text(path)['custom_score'] is None
    result = grade_saved_text(path, terminal=True)
    assert result['custom_score'] == expected and result['official_score'] is None


def test_text_setup_neither_types_the_answer_nor_writes_target_file():
    import ast
    from scripts.taskviews_quick_setup import blank_text_setup_command
    source = blank_text_setup_command('/home/user/Desktop/tv_quick.txt')
    ast.parse(source)
    assert 'TaskViews quick check' not in source and 'pyautogui' not in source
    assert 'write_text' not in source and 'write_bytes' not in source
    assert source.index('os.path.exists(target)') < source.index('subprocess.Popen')
    assert 'target_file_precreated' in source and 'Prior text editor window present' in source


def test_relative_launch_directory_is_absolute_for_worker_and_logs(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from scripts import taskviews_quick_live as quick
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / 'quick folder'
    directory.mkdir()
    plan = {'run_id': 'offline-relative-launch', 'parent_stage': str(tmp_path / 'parent'),
            'parent_files_sha256': {'saved': 'original'}}
    (directory / 'plan.json').write_text(json.dumps(plan))
    monkeypatch.setattr(quick, 'require_scope', lambda limit: None)
    monkeypatch.setattr(quick, 'verify_source', lambda plan: None)
    monkeypatch.setattr(quick, 'parent_files', lambda parent: {'saved': 'original'})
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    calls = []
    monkeypatch.setattr(quick.subprocess, 'run', lambda args, **kwargs: calls.append(args))
    quick.launch(Path('quick folder'))
    service = (directory / 'service.unit').read_text()
    assert str(directory.resolve()) in service.split('ExecStart=', 1)[1].splitlines()[0]
    assert f'StandardOutput=append:{directory.resolve()}/console.log' in service
    assert f'StandardError=append:{directory.resolve()}/console.log' in service
    assert calls == [['systemctl', '--user', 'daemon-reload'],
                     ['systemctl', '--user', 'start', 'offline-relative-launch.service']]


def test_keyboard_case_declares_its_narrow_scope_without_precreating_answer():
    import json
    from ui_kobe.osworld.quick_checks import TEXT_KEYBOARD_SAVE, TEXT_SAVE
    from scripts.taskviews_quick_live import setup_task
    from scripts.taskviews_quick_setup import blank_text_setup_command
    assert TEXT_KEYBOARD_SAVE['id'] != TEXT_SAVE['id']
    assert 'only keyboard' in TEXT_KEYBOARD_SAVE['instruction']
    assert 'excludes pointer localization' in TEXT_KEYBOARD_SAVE['module_under_test']
    command = blank_text_setup_command(TEXT_KEYBOARD_SAVE['expected_guest_artifact'])
    assert 'TaskViews quick check' not in command and 'write_text' not in command
    class Controller:
        def execute_python_command(self, source):
            assert source == command
            return {'status': 'success', 'returncode': 0, 'output': '{"initialization_only":true,"target_file_precreated":false}'}
    result = setup_task(Controller(), {'task': TEXT_KEYBOARD_SAVE})
    assert not result['actor_action'] and not result['target_file_precreated']
    assert json.loads(result['receipt']['output'])['initialization_only']


def test_existing_document_case_starts_with_empty_input_that_cannot_pass_grader(tmp_path):
    import ast
    from scripts.taskviews_quick_setup import blank_text_setup_command
    from ui_kobe.osworld.quick_checks import TEXT_EDIT_SAVE, TEXT_SAVE, grade_saved_text
    assert TEXT_EDIT_SAVE['id'] != TEXT_SAVE['id'] and TEXT_EDIT_SAVE['initial_input_expected_bytes'] == 0
    assert 'current document' in TEXT_EDIT_SAVE['instruction'] and 'excludes Save As' in TEXT_EDIT_SAVE['module_under_test']
    command = blank_text_setup_command(TEXT_EDIT_SAVE['expected_guest_artifact'], input_fixture=True)
    ast.parse(command)
    assert "input_fixture = True" in command and "open(target, 'xb')" in command
    assert 'TaskViews quick check' not in command and 'pyautogui' not in command
    assert 'requested_answer_precreated' in command and 'initial_input' in command
    before = tmp_path / 'tv_input.txt'
    before.write_bytes(b'')
    assert grade_saved_text(before, terminal=True)['custom_score'] == 0
    before.write_text('TaskViews quick check', encoding='utf-8')
    assert grade_saved_text(before, terminal=True)['custom_score'] == 1
