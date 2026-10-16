"""Replay saved baseline observations/calls through Mini without GUI or API access.

This is a deterministic module test, not a new agent rollout or success score.
Recorded replies are injected; no model is asked to predict the next action.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backend_probe():
    """Execute only installed backend function ASTs with all I/O replaced by spies."""
    package = Path(importlib.util.find_spec('pyautogui').origin).parent
    public = ast.parse((package / '__init__.py').read_text())
    keys = next(ast.literal_eval(n.value) for n in public.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'KEY_NAMES' for t in n.targets))
    backend = package / '_pyautogui_x11.py'
    tree = ast.parse(backend.read_text())
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('_keyDown', '_keyUp', '_vscroll')]
    events = []
    namespace = {'keyboardMapping': {k: k for k in keys},
        'fake_input': lambda *a: events.append(a[1:]),
        '_display': SimpleNamespace(sync=lambda: None),
        'X': SimpleNamespace(KeyPress='press', KeyRelease='release'),
        'pyautogui': SimpleNamespace(isShiftCharacter=lambda k: False),
        '_click': lambda *a, **kw: events.append(kw)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(backend), 'exec'), namespace)
    counts = {}
    for key in ('page_down', 'pagedown', 'page_up', 'pageup', 'minus', '-'):
        events.clear()
        namespace['_keyDown'](key)
        namespace['_keyUp'](key)
        counts[key] = len(events)
    scroll = {}
    for amount in (-5, -300, -600):
        events.clear()
        namespace['_vscroll'](amount)
        scroll[str(amount)] = len(events)
    assert counts == {'page_down': 0, 'pagedown': 2, 'page_up': 0, 'pageup': 2, 'minus': 0, '-': 2}
    assert scroll == {'-5': 5, '-300': 300, '-600': 600}
    return {'source': str(backend), 'sha256': sha(backend), 'key_events': counts,
            'wheel_events': scroll, 'display_connected': False,
            'limitation': 'installed X11 function logic with fake I/O; not a fresh guest integration test'}


def journal_events(folder):
    path = next((folder / 'telemetry' / 'transitions').glob('*.sqlite'))
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        events = [json.loads(row[0]) for row in db.execute('SELECT payload FROM events ORDER BY seq')]
    return path, events


class RecordedTransport:
    last_timing = {}

    def __init__(self):
        self.message = None
        self.requests = 0
        self.last_messages = None

    def create(self, **kwargs):
        from ui_kobe.api.kimi_stream import Completion
        self.requests += 1
        self.last_messages = deepcopy(kwargs['messages'])
        return Completion({'choices': [{'finish_reason': 'tool_calls', 'message': self.message}]})

    def close(self):
        pass


def replay(root, output):
    from ui_kobe.api.kimi_stream import Completion, StreamProtocolError
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.osworld.kimi_native import official_compile
    from ui_kobe.osworld.mini_interaction import validate_keys
    from ui_kobe.osworld.sx_native import SXMiniTaskViewsNativeAgent, SXNativeProvider
    from ui_kobe.osworld.transitions import TransitionJournal, decision_tools
    from scripts.verified_invoice import project_identity, sources
    from scripts.osworld_native_experiment import require_scope

    require_scope(2 * 1024**3)
    assert json.loads((root / 'state.json').read_text())['status'] == 'completed'
    output.mkdir(parents=True, exist_ok=False)
    plan = json.loads((root / 'plan.json').read_text())
    before = project_identity()
    report = {'mode': 'offline_recorded_response_replay', 'run': str(root),
              'plan_sha256': sha(root / 'plan.json'), 'model_requests': 0, 'gui_actions': 0,
              'official_evaluations': 0, 'official_score': None, 'passed': False,
              'backend': backend_probe(), 'arms': {}, 'baseline_mini_replay': []}
    contract = CUAContract(**plan['cua_contract'])
    # Compare the exact recorded native arguments to all original dispatched commands.
    for arm in plan['arms']:
        path, events = journal_events(root / arm)
        index = {e['id']: e for e in events}
        decisions = [e for e in events if e['kind'] == 'decision']
        rejected = []
        commands = 0
        for d in decisions:
            source = index[d['source']]
            image = Path(source['images']['original']['ref'])
            assert sha(image) == source['images']['original']['sha256']
            frame = contract.process(image.read_bytes(), d['step'])
            arguments = [tool['arguments'] for tool in d['tools']]
            compiled = official_compile(arguments, frame).commands
            assert compiled == d['commands']
            commands += len(compiled)
            try:
                validate_keys(arguments, Completion({'choices': [{'finish_reason': 'tool_calls',
                                                                 'message': {'role': 'assistant'}}]}))
            except StreamProtocolError as exc:
                rejected.append({'step': d['step'], 'code': exc.code, 'commands': compiled})
        report['arms'][arm] = {'journal_sha256': sha(path), 'decisions_matched': len(decisions),
                              'commands_matched': commands, 'now_rejected_keys': rejected}
    path, events = journal_events(root / 'baseline')
    index = {e['id']: e for e in events}
    decisions = [e for e in events if e['kind'] == 'decision']
    transitions = {d['id']: [e for e in events if e['kind'] == 'transition' and e['decision_id'] == d['id']]
                   for d in decisions}
    transport = RecordedTransport()
    environment = {'SX_QWEN_API_KEY': 'offline-placeholder', 'SX_URL_SB': plan['base_url'],
        'UI_KOBE_SX_URL_ENV': 'SX_URL_SB', 'UI_KOBE_GENERATION_PROFILE': plan['generation_profile']['name'],
        'UI_KOBE_CUA_CONTRACT_JSON': json.dumps(contract.snapshot()),
        'UI_KOBE_TELEMETRY_DIR': str(output / 'telemetry'),
        'UI_KOBE_TASKVIEWS_PROFILE': 'mini_fixed_v1', 'UI_KOBE_TASKVIEWS_FEEDBACK_V10': '0',
        'UI_KOBE_MINI_CONTROLS_VIEW': 'disabled'}
    with patch.dict(os.environ, environment), patch.object(SXNativeProvider, 'provider_transport', lambda *a: transport):
        actor = SXMiniTaskViewsNativeAgent(model=plan['model'], base_url=plan['base_url'], temperature=0,
                                         max_tokens=plan['generation_profile']['max_completion_tokens'])
        actor.execution_journal = TransitionJournal(output / 'journal', task_id='offline-replay',
            run_id='saved-baseline-module-test', contract=contract)
        try:
            for d in decisions:
                source = index[d['source']]
                obs = {'screenshot': Path(source['images']['original']['ref']).read_bytes()}
                original = d['response']
                if original.lstrip().startswith('{'):
                    original = json.loads(original).get('content') or ''
                transport.message = {'role': 'assistant', 'content': original, 'tool_calls': [
                    {'id': t['id'], 'type': 'function', 'function': {'name': 'computer_use',
                        'arguments': json.dumps(t['arguments'])}} for t in d['tools']]}
                actor.flush_execution()
                actor.execution_journal.begin(d['instruction'], obs, step=d['step'])
                response, compiled = actor.predict(d['instruction'], obs)
                assert compiled == d['commands']
                actor.execution_journal.decide(response, compiled, step=d['step'], tools=decision_tools(actor))
                for command, transition in zip(compiled, transitions[d['id']], strict=True):
                    assert transition['action'] == command
                    target = index[transition['target']]
                    after = {'screenshot': Path(target['images']['original']['ref']).read_bytes()}
                    assert hashlib.sha256(after['screenshot']).hexdigest() == target['images']['original']['sha256']
                    receipt = transition.get('controller_receipts')
                    error = transition.get('error')
                    actor.execution_journal.result(command, step=d['step'], observation=after, receipts=receipt, error=error)
                    actor.record_execution(command, receipts=receipt, error=error)
                view = actor.mini_context.trace
                assert view['delivered'] and view['packet_bytes'] <= 3000
                report['baseline_mini_replay'].append({'step': d['step'], 'commands': compiled,
                    'view_bytes': view['packet_bytes'], 'source_screenshot_sha256': source['images']['original']['sha256']})
            actor.flush_execution()
        finally:
            actor.close()
    assert transport.requests == len(decisions) == 40
    report['recorded_responses_consumed'] = transport.requests
    report['source_unchanged_during_test'] = before == project_identity()
    report['upstream_unchanged'] = sources(Path(plan['sources']['benchmark']['repo']),
                                          Path(plan['sources']['actor_compiler']['repo'])) == plan['sources']
    report['passed'] = report['source_unchanged_during_test'] and report['upstream_unchanged']
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('baseline_mini_replay', 'backend')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    replay(args.run_dir.resolve(), args.output.resolve())
