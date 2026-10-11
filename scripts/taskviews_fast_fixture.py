"""Offline complete TaskViews feedback loop; NOT a live model/OSWorld score.

Use the pinned official compiler with a deterministic local UI model and an
httpx MockTransport. No VM, credential, real provider request or guest reset.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


class FixtureUI:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.focus, self.text, self.objects, self.saved = 'canvas', '', [], False

    def screenshot(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (1920, 1080), 'white')
        draw = ImageDraw.Draw(image)
        for index, text in enumerate(self.visible()):
            draw.text((60, 60 + index * 50), text, fill='black')
        buffer = BytesIO()
        image.save(buffer, 'PNG')
        return buffer.getvalue()

    def visible(self):
        return [f'Focus: {self.focus}', f'Input: {self.text}',
                'Objects: ' + (', '.join(self.objects) or 'none'), 'Saved' if self.saved else 'Unsaved']

    def dispatch(self, arguments):
        """Simulate only fixture-native actions, keeping the full compiled command."""
        action = arguments['action']
        if action == 'left_click':
            if arguments['coordinate'] == [200, 900]:
                self.focus = 'input'
            elif arguments['coordinate'] == [1700, 80]:
                self.saved = bool(self.objects)
                if self.saved:
                    (self.directory / 'saved.json').write_text(json.dumps({'objects': self.objects}) + '\n')
            else:
                self.focus = 'canvas'
        elif action == 'type' and self.focus == 'input':
            self.text = arguments['text']
        elif action == 'key' and arguments['keys'] == 'Return' and self.focus == 'input':
            if self.text == 'P1 = (1, 2)':
                self.objects = ['P1 = (1, 2)']
                self.text = ''
        return {'returncode': 0, 'fixture_controller': True}


class FixtureSnapshots:
    """A QMP test double. Its save/load is NOT whole-guest checkpoint validation."""
    def __init__(self, ui):
        self.ui, self.states = ui, {}

    def save(self, tag):
        self.states[tag] = deepcopy({k: getattr(self.ui, k) for k in ('focus', 'text', 'objects', 'saved')})

    def load(self, tag):
        for key, value in self.states[tag].items():
            setattr(self.ui, key, deepcopy(value))

    def hmp(self, command):
        if command.startswith('delvm '):
            self.states.pop(command[6:], None)

    def call(self, command):
        return {'status': 'paused' if command == 'stop' else 'running'}


def run_fixture(directory, *, bad_action_binding=False, null_subgoal_review=False, bad_perception_envelopes=0):
    import httpx
    from ui_kobe.api.qwen_native import MODEL, BASE_URL, QwenNativeClient
    from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
    from ui_kobe.osworld.checkpoints import Checkpoints, ReadAnomaly
    from ui_kobe.osworld.kimi_native import official_compile
    from ui_kobe.osworld.transitions import TransitionJournal, decision_tools
    from ui_kobe.osworld import telemetry
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    trace = directory / 'telemetry'
    old_env = {key: os.environ.get(key) for key in ('QWEN_API_KEY', 'UI_KOBE_TELEMETRY_DIR',
               'UI_KOBE_TASK_ID', 'UI_KOBE_CHECKPOINT_READS', 'UI_KOBE_TASKVIEWS_FEEDBACK_V10')}
    old_root = telemetry._root
    os.environ.update(QWEN_API_KEY='offline-fixture-key', UI_KOBE_TELEMETRY_DIR=str(trace),
        UI_KOBE_TASK_ID='local-feedback-fixture', UI_KOBE_CHECKPOINT_READS='1', UI_KOBE_TASKVIEWS_FEEDBACK_V10='1')
    telemetry._root = trace
    trace.mkdir()
    actor = QwenTaskViewsNativeAgent(model=MODEL, base_url=BASE_URL, temperature=0, max_tokens=16000,
        history_n=20, image_max=1, fold_size=1, context_max_text_chars=32000,
        context_reserve_chars=10000, taskviews_context_bytes=8000)
    ui = FixtureUI(directory)
    script = [{'action': 'left_click', 'coordinate': [200, 200]},
              {'action': 'left_click', 'coordinate': [200, 200]},
              {'action': 'left_click', 'coordinate': [200, 900]},
              {'action': 'type', 'text': 'P1 = (1, 2)'},
              {'action': 'key', 'keys': 'Return'},
              {'action': 'left_click', 'coordinate': [1700, 80]},
              {'action': 'terminate', 'status': 'success'}]
    requests, actor_packets, roles, native_index = [], [], Counter(), 0
    first_plan = True
    envelope_failures = 0

    def handler(request):
        nonlocal native_index, first_plan, envelope_failures
        payload = json.loads(request.content)
        requests.append(payload)
        system = payload['messages'][0]['content']
        body = {'id': 'fixture-response-' + str(len(requests)), 'model': MODEL,
            'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': None}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}}
        message = body['choices'][0]['message']
        if payload.get('tools'):
            roles['executor'] += 1
            args = script[native_index]
            message['content'] = ('Focus the input control', 'Focus the input control',
                'Focus the input control', 'Type the requested text', 'Submit the requested object',
                'Save the requested result', 'Finish after the saved result is visible')[native_index]
            native_index += 1
            body['choices'][0]['finish_reason'] = 'tool_calls'
            message['tool_calls'] = [{'id': 'fixture-native-' + str(native_index), 'type': 'function',
                'function': {'name': 'computer_use', 'arguments': json.dumps(args)}}]
            prefix = actor.context_label + '\n'
            supplements = [part['text'][len(prefix):] for part in payload['messages'][-1]['content']
                           if part.get('type') == 'text' and part['text'].startswith(prefix)]
            actor_packets.append(json.loads(supplements[0]) if supplements else None)
        else:
            context = json.loads(payload['messages'][1]['content'][0]['text'])
            if 'Extract visible evidence' in system:
                roles['perception'] += 1
                last = context['last_action']
                check = None
                if last:
                    kind = last['expected_change']['kind']
                    observed = (ui.focus == 'input' if kind == 'focus' else bool(ui.text) if kind == 'text'
                                else bool(ui.objects) if kind == 'submission' else ui.saved)
                    # The Save button is a state action; the fixture reader checks
                    # the visible save result instead of declaring a task grade.
                    if ui.saved:
                        kind, observed = 'state', True
                    assessment = 'observed' if observed else 'not_observed'
                    check = {'transition_id': 'wrong-binding' if bad_action_binding else last['transition_id'],
                        'target_observation_id': last['target'], 'frame_id': context['frame']['frame_id'],
                        'assessment': assessment,
                        'checks': [{'kind': kind, 'assessment': assessment, 'quotes': [ui.visible()[0] if kind == 'focus'
                            else ui.visible()[1] if kind == 'text' else ui.visible()[2] if kind == 'submission'
                            else ui.visible()[3]]}]}
                    if ui.saved:
                        check['checks'].append({'kind': 'focus', 'assessment': 'observed', 'quotes': [ui.visible()[0]]})
                    elif kind == 'text':
                        check['checks'].append({'kind': 'focus', 'assessment': 'observed', 'quotes': [ui.visible()[0]]})
                    elif kind == 'submission':
                        check['checks'].append({'kind': 'object', 'assessment': assessment, 'quotes': [ui.visible()[2]]})
                    if last.get('actor_intent'):
                        key = 'saved' if ui.saved else {'focus': 'focus', 'text': 'input',
                            'submission': 'objects', 'state': 'saved'}[kind]
                        check['checks'].append({'kind': 'intent', 'assessment': assessment,
                            'quotes': check['checks'][0]['quotes'], 'state_keys': [key]})
                value = {'summary': 'Fixture visible fields only',
                    'elements': [{'text': text, 'role': 'text', 'bbox': [60, 60 + i * 50, 1000, 100 + i * 50]}
                                 for i, text in enumerate(ui.visible())],
                    'semantics': {'entities': [], 'claims': []}, 'action_check': check,
                    'ui_state': {'page_id': 'fixture-editor', 'fields': {'focus': ui.focus, 'input': ui.text,
                        'objects': ','.join(ui.objects), 'saved': ui.saved}}}
                if null_subgoal_review:
                    value['subgoal_review'] = None
                if envelope_failures < bad_perception_envelopes:
                    value = {'action': 'click', 'coordinate': [200, 200]} if envelope_failures == 0 else context
                    envelope_failures += 1
            elif 'task controller' in system:
                roles['view_controller'] += 1
                value = {'stage': 'work', 'subgoal_id': 'create-save',
                    'needs': [{'id': role, 'consumer': role, 'purpose': 'Create the requested object then save',
                               'anchors': ['task'], 'focus_predicates': ['*'], 'max_hops': 1}
                              for role in ('executor', 'planner')]}
                if first_plan:
                    value['subgoals'] = [{'id': 'create-save', 'label': 'Create requested object and save', 'dependencies': []}]
                    first_plan = False
            else:
                roles['planner'] += 1
                value = {'advice': 'Confirm the visible input focus and text, then submit and check the object/save result.',
                         'needed_evidence': ['Input focus and exact text']}
            message['content'] = json.dumps(value)
        return httpx.Response(200, json=body)

    actor.transport.close()
    actor.transport = actor.client.transport = QwenNativeClient(api_key='offline-fixture-key', budget=actor.budget,
        profile=actor.profile, emit=telemetry.emit, response_dir=trace / 'responses',
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    actor.execution_journal = journal = TransitionJournal(trace / 'transitions', task_id='local-feedback-fixture',
        run_id='offline-fixture', contract=actor.contract)
    manager = Checkpoints(directory / 'stage', {}, qmp=FixtureSnapshots(ui))
    manager.vm = {'container': 'offline-fixture-NO-REAL-VM'}
    instruction = 'In the fixture editor create P1 = (1, 2), save the result, verify it is saved, then finish.'
    started, terminal, paused, compiler_checks, step_counts = time.monotonic(), False, False, 0, []
    try:
        for step in range(1, 9):
            obs = {'screenshot': ui.screenshot()}
            manager.save(actor, instruction, obs)
            journal.begin(instruction, obs, step=step)
            try:
                response, commands = actor.predict(instruction, obs)
            except ReadAnomaly as error:
                manager.pause(error)
                paused = True
                break
            args = actor.last_trace['native_actions']
            assert official_compile(args, actor.frame).commands == commands
            compiler_checks += 1
            journal.decide(response, commands, step=step, tools=decision_tools(actor))
            step_counts.append({'actor': actor.step_ledger.snapshot(), 'analysis': actor.advisory_ledger.snapshot()})
            if commands == ['DONE']:
                terminal = True
                break
            assert len(args) == len(commands) == 1
            receipt = ui.dispatch(args[0])
            after = {'screenshot': ui.screenshot()}
            actor.record_execution(commands[0], receipts=[receipt])
            journal.result(commands[0], step=step, observation=after, receipts=[receipt])
            actor.sync_execution()
        score = None
        if terminal:
            saved = directory / 'saved.json'
            score = float(saved.exists() and json.loads(saved.read_text()) == {'objects': ['P1 = (1, 2)']})
        _, latest = manager.read(metadata_only=True)
        result = {'test_kind': 'offline_fixture_with_mock_provider_controller_and_QMP',
            'official_score': None, 'fixture_score': score, 'model_ability_measured': False,
            'terminal': terminal, 'paused': paused, 'duration_s': round(time.monotonic() - started, 3),
            'native_decisions': native_index, 'controller_actions': journal.db.execute(
                "SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='transition'").fetchone()[0],
            'requests': len(requests), 'roles': dict(roles), 'compiler_checks': compiler_checks,
            'all_actor_packets_delivered': all(packet is not None for packet in actor_packets),
            'all_actor_packets_local': all(packet and packet.get('execution_boundary')
                and 'current_visible_evidence' in packet and 'active_subgoal' in packet
                and 'assigned_views' not in packet and 'advisers' not in packet
                and all('bbox' not in item for item in packet['current_visible_evidence']['elements'])
                and packet['role_evidence']['execution_modules']['modules'] == []
                for packet in actor_packets),
            'recent_feedback_packets': sum(bool(packet and packet['role_evidence']['execution_modules']['recent_transitions'])
                                           for packet in actor_packets),
            'module_count': len(actor.modules.modules) if actor.modules else 0,
            'latest_checkpoint': {'tag': latest['tag'], 'completed_steps': latest['completed_steps'],
                                  'command_count': latest['command_count']},
            'pool_checks': step_counts, 'output': str(directory / 'saved.json')}
        (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        return result
    finally:
        actor.close()
        telemetry._root = old_root
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    import argparse
    from scripts.osworld_native_experiment import require_scope
    require_scope(128 * 1024**2)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    result = run_fixture(args.directory)
    print(json.dumps({k: result[k] for k in ('test_kind', 'official_score', 'fixture_score', 'terminal',
        'requests', 'roles', 'controller_actions', 'all_actor_packets_delivered', 'duration_s')}))
    return 0 if result['terminal'] and result['fixture_score'] == 1 and result['all_actor_packets_delivered'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
