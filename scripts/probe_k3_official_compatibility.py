"""Two synthetic predict turns; real K3 protocol probe, no VM/GUI or scoring.

This is not a benchmark. All compiled commands remain unexecuted, including
the upstream synthetic history receipt text. No conclusion about effects follows.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(Path.home() / 'osworld2/OSWorld-V2')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=('low-16k', 'max-32k'), default='low-16k')
    parser.add_argument('--cua-config', type=Path)
    args = parser.parse_args()
    from scripts.osworld_native_experiment import require_scope, write, project_snapshot, now
    group = require_scope(128 * 1024**2)
    from ui_kobe.osworld.official_base import verify_official_base, OFFICIAL_COMMIT
    from ui_kobe.osworld.runner import source_snapshot
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.api.kimi import generation_profile
    from ui_kobe.osworld import telemetry
    from ui_kobe.osworld.kimi_official import OfficialK3Agent
    from PIL import Image, ImageDraw
    from io import BytesIO
    repo = Path.home() / 'osworld2/OSWorld-V2'
    verify_official_base(repo)
    before = source_snapshot(repo)
    project_before = project_snapshot()
    contract = CUAContract(**json.loads(args.cua_config.read_text())) if args.cua_config else CUAContract()
    root = args.output.with_suffix('')
    if root.exists() or args.output.exists():
        raise RuntimeError('Use a new compatibility evidence path')
    if not os.environ.get('KIMI_API_KEY'):
        raise RuntimeError('KIMI_API_KEY absent; no live compatibility claim')
    root.mkdir(parents=True)
    os.environ.update(UI_KOBE_GENERATION_PROFILE=args.profile, UI_KOBE_CUA_CONTRACT_JSON=json.dumps(contract.snapshot()),
                      UI_KOBE_TELEMETRY_DIR=str(root), UI_KOBE_TASK_ID='synthetic-compatibility')
    telemetry.install_api(root)
    image = Image.new('RGB', (1920, 1080), 'white')
    ImageDraw.Draw(image).ellipse((90, 90, 110, 110), fill='red')
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    profile = generation_profile(args.profile)
    agent = OfficialK3Agent(model='kimi-k3', base_url='https://api.moonshot.ai/v1', max_tokens=profile.max_completion_tokens)
    turns, error = [], None
    try:
        for number, instruction in enumerate((
            'Protocol test on a synthetic image. Move the mouse to the red marker using computer_use. Commands will not execute.',
            'Protocol test continued on the unchanged synthetic image. Return a single computer_use wait action.'), 1):
            response, commands = agent.predict(instruction, {'screenshot': buffer.getvalue(),
                **({'user_response': 'This is a protocol test; no command was executed.'} if number == 2 else {})})
            turns.append({'step': number, 'response': response, 'commands': commands, 'executed': False,
                          'step_tokens': agent.step_ledger.snapshot()})
        original = deepcopy_message = agent.client.history[agent.responses[0]]
        restored = agent.client.restore_messages([{'role': 'assistant', 'content': agent.responses[0]}])[0]
        history_exact = restored == original
        messages = agent._last_payload['messages']
        history_present = any(m.get('role') == 'assistant' for m in messages)
        same_image = any(p.get('image_url', {}).get('url') == agent.frame.screenshot.data_url
                         for m in messages if isinstance(m.get('content'), list) for p in m['content'])
        compatible = history_exact and history_present and same_image and bool(turns[0]['commands']) and bool(turns[1]['commands'])
    except Exception as exc:
        compatible = False
        error = {'type': type(exc).__name__, 'code': getattr(exc, 'code', None), 'error': telemetry.safe(str(exc))}
        history_exact = history_present = same_image = False
    finally:
        agent.close()
    after = source_snapshot(repo)
    events = [json.loads(line) for path in root.glob('events-*.jsonl') for line in path.read_text().splitlines()]
    if compatible:
        wire = next(e for e in events if e['event'] == 'api_request' and e.get('step') == 2)
        history_exact = any(m == deepcopy_message for m in wire['payload']['messages'] if m.get('role') == 'assistant')
        compatible = compatible and history_exact
    requests = {}
    for event in events:
        if event['event'] == 'request_outcome':
            requests[event['request_id']] = event.get('usage')
    usage = {key: sum((v or {}).get(key, 0) for v in requests.values())
             for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    # Raw SSE/messages/images live under the ignored evidence directory. The
    # tracked report carries hashes and bounded outcomes, never credentials.
    files = {str(p.relative_to(root)): __import__('hashlib').sha256(p.read_bytes()).hexdigest()
             for p in root.rglob('*') if p.is_file()}
    write(args.output, {'time_utc': now(), 'official_commit': OFFICIAL_COMMIT,
        'compatible': compatible and before == after and project_before == project_snapshot(),
        'live_api_called': True, 'gui_operated': False, 'vm_created': False,
        'benchmark_score': None, 'generation_profile': profile.__dict__, 'cua_contract': contract.snapshot(),
        'history_exact': history_exact, 'history_present': history_present, 'same_acting_image': same_image,
        'turns': telemetry.safe(turns), 'error': error, 'usage': usage,
        'unknown_usage_requests': sum(v is None for v in requests.values()), 'settled_requests': len(requests),
        'project_source': project_snapshot(), 'official_source_unchanged': before == after,
        'evidence_dir': str(root), 'evidence_sha256': files, 'scope_limit': 128 * 1024**2,
        'memory_peak': int((group / 'memory.peak').read_text()), 'memory_events': (group / 'memory.events').read_text(),
        'limitation': 'Two synthetic turns only. No action executes. Upstream history success text is synthetic, not a receipt.'})
    print(json.dumps({'compatible': compatible, 'turns': len(turns), 'usage': usage, 'error': error}))
    return 0 if compatible and before == after and project_before == project_snapshot() else 1


if __name__ == '__main__':
    raise SystemExit(main())
