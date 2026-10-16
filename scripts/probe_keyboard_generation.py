"""Matched saved-frame input audit; optional six first-candidate API probes, no GUI.

Each case holds original history/image/schema fixed and varies the supplemental
view. A common intent instruction isolates key-name generation from task planning.
This development probe is not a benchmark, a causal proof, or a launch gate.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def request(root, arm, step):
    for path in sorted((root / arm / 'telemetry').glob('events-*.jsonl')):
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                if row.get('event') == 'api_request' and row.get('step') == step:
                    return row['payload']
    raise ValueError('Saved request missing')


def input_audit(payload):
    counts = {}
    for role in ('system', 'assistant', 'tool', 'user'):
        text = encoded([m for m in payload['messages'] if m['role'] == role]).lower()
        counts[role] = {term: text.count(term) for term in ('page down', 'page_down', 'pagedown', 'minus', 'underscores')}
    current = payload['messages'][-1]['content']
    return {'system_sha256': digest(payload['messages'][0]), 'schema_sha256': digest(payload['tools']),
            'request_messages_sha256': digest(payload['messages']), 'text_term_counts': counts,
            'retained_assistant_turns': sum(m['role'] == 'assistant' for m in payload['messages']),
            'current_text_parts': [p['text'] for p in current if p.get('type') == 'text'],
            'keys_schema': payload['tools'][0]['function']['parameters']['properties']['keys']}


def variant_messages(payload, variant, intent):
    from kobe_views.fixed_views import materialize
    from kobe_views.keyboard_view import record, select_topic
    from ui_kobe.osworld.mini_interaction import KEY_GUIDANCE, interaction_contract
    from ui_kobe.osworld.mini_taskviews_context import LABEL
    from ui_kobe.osworld.mini_taskviews_native import FRAME_CONTRACT_PREFIX

    messages = deepcopy(payload['messages'])
    content = messages[-1]['content']
    old_part = next(p for p in content if p.get('text', '').startswith('Fixed TaskViews'))
    old = json.loads(old_part['text'].split('\n', 1)[1])
    frame_part = next(p for p in content if p.get('text', '').startswith(FRAME_CONTRACT_PREFIX))
    if variant == 'native_history_only':
        content.remove(old_part)
        content.remove(frame_part)
    elif variant == 'mini_keyboard_v3':
        lessons = old['views']['lessons']['records']
        topic, selection = select_topic([r.get('text') for r in reversed(lessons)])
        current = deepcopy(old['views']['current']['records'][0])
        current['interaction_contract'] = interaction_contract()
        packet = materialize(episode_id=old['episode_id'], frame_id=old['frame_id'], current=current,
            attempts=list(reversed(old['views']['attempts']['records'])), lessons=list(reversed(lessons)),
            totals={k: len(old['views'][k]['records']) + old['views'][k]['omitted_records'] for k in ('attempts', 'lessons')},
            max_bytes=3000, keyboard=record(topic, selection))
        assert packet['views']['keyboard']['records']
        old_part['text'] = LABEL + '\n' + encoded(packet)
        frame_part['text'] += ' ' + KEY_GUIDANCE
    content.insert(0, {'type': 'text', 'text': 'Module diagnostic only: ' + intent +
                    ' Return one computer_use key action. It will be inspected without GUI execution.'})
    return messages


def restore_images(messages, telemetry_dir):
    for message in messages:
        if isinstance(message.get('content'), list):
            for part in message['content']:
                if part.get('type') == 'image_url':
                    ref = part['image_url']['url']
                    raw = (telemetry_dir / ref['image']).read_bytes()
                    assert hashlib.sha256(raw).hexdigest() == ref['sha256']
                    part['image_url']['url'] = 'data:image/png;base64,' + base64.b64encode(raw).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    root, out = args.run_dir.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    from scripts.verified_invoice import write, project_identity
    from scripts.osworld_native_experiment import require_scope
    require_scope(2 * 1024**3)
    plan = json.loads((root / 'plan.json').read_text())
    inputs = {f'{arm}-{step}': input_audit(request(root, arm, step))
              for arm, step in [('baseline', 20), ('taskviews', 15), ('taskviews', 21), ('ui_kobe_like', 33)]}
    report = {'kind': 'saved_frame_first_candidate_development_probe', 'inputs': inputs,
              'cases': [], 'complete': False, 'gui_actions': 0, 'official_score': None,
              'common_intent_instruction': True, 'live_requested': args.live,
              'project_source': project_identity(), 'plan_sha256': hashlib.sha256((root/'plan.json').read_bytes()).hexdigest()}
    write(out / 'report.json', report)
    if not args.live:
        return
    from ui_kobe.api.sx_native import SXNativeClient, generation_profile, resolve_base_url
    from ui_kobe.api.qwen_native import QwenTransportBudget
    from ui_kobe.api.kimi_budget import StepLedger
    from ui_kobe.osworld import telemetry
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.osworld.kimi_native import validate_native
    from ui_kobe.osworld.mini_interaction import validate_keys
    from mm_agents.qwen.parser import parse_keys

    assert resolve_base_url('SX_URL_SB') == plan['base_url'] and os.environ.get('SX_QWEN_API_KEY')
    profile = generation_profile(plan['generation_profile']['name'])
    def emit(event, **fields):
        # Retain API timing/usage/outcomes without serializing private prompts or image payloads.
        if event != 'api_request':
            with (out/'events.jsonl').open('a') as stream:
                stream.write(encoded({'event': event, **telemetry.safe(fields)}) + '\n')
    client = SXNativeClient(url_env='SX_URL_SB', profile=profile, budget=QwenTransportBudget(attempts=1),
                            emit=emit, response_dir=out/'responses')
    try:
        for step, intent, expected in [(15, 'Press the Page Down key once in the focused document.', ['pagedown']),
                                      (21, 'Use the keyboard shortcut to zoom out once in this PDF viewer.', ['ctrl', '-'])]:
            payload = request(root, 'taskviews', step)
            ref = next(p['image_url']['url'] for p in payload['messages'][-1]['content'] if p.get('type') == 'image_url')
            frame = CUAContract(**plan['cua_contract']).process((root/'taskviews'/'telemetry'/ref['image']).read_bytes(), step)
            for variant in ('native_history_only', 'mini_v2_original', 'mini_keyboard_v3'):
                messages = variant_messages(payload, variant, intent)
                input_sha = digest(messages)
                restore_images(messages, root/'taskviews'/'telemetry')
                ledger = StepLedger(profile, time.monotonic()+600, emit, actor_repairs=0)
                result = client.create(model=plan['model'], messages=messages, tools=payload['tools'], tool_choice='auto',
                    max_tokens=profile.max_completion_tokens, step_ledger=ledger, budget_role='executor', deadline=ledger.deadline)
                case = {'step': step, 'variant': variant, 'input_sha256': input_sha,
                        'usage': result.model_dump().get('usage'), 'matched_intent': False, 'valid_keys': False}
                try:
                    actions, batch = validate_native(result, frame)
                    case.update(actions=actions, compiled=batch.commands)
                    validate_keys(actions, result)
                    case['valid_keys'] = True
                    case['matched_intent'] = (len(actions) == 1 and actions[0].get('action') == 'key'
                                             and parse_keys(actions[0].get('keys')) == expected)
                except Exception as exc:
                    case['candidate_error'] = {'type': type(exc).__name__, 'code': getattr(exc, 'code', None)}
                report['cases'].append(case)
                write(out/'report.json', report)
                print(encoded(case), flush=True)
        report['complete'] = len(report['cases']) == 6
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': telemetry.safe(str(exc))}
    finally:
        client.close()
        report['source_unchanged'] = project_identity() == report['project_source']
        report['total_usage'] = {k: sum((c.get('usage') or {}).get(k, 0) for c in report['cases'])
                                 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        write(out/'report.json', report)
    return 0 if report['complete'] and report['source_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
