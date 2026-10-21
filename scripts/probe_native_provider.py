"""Bounded live provider checks, using synthetic pixels; never start/act on a VM.

Use a fresh output directory. A plan's launch gate is satisfied only after all
three real responses validate, including vision, native tools and tool replies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scripts.verified_invoice import EXPERIMENTS, project_identity, specification, validate_plan, write  # noqa: E402
from ui_kobe.api.kimi_budget import StepLedger  # noqa: E402
from ui_kobe.api.qwen_native import QwenTransportBudget  # noqa: E402
from ui_kobe.osworld import telemetry  # noqa: E402


def vision_frame(contract, *, large=False):
    """Release temporary image/noise buffers before making a large HTTP call."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1920, 1080), 'white')
    try:
        if large:
            import random
            noise = bytes(value & 31 for value in random.Random(0).randbytes(1920 * 1080 * 3))
            image.close()
            image = Image.frombytes('RGB', (1920, 1080), noise)
            del noise
        ImageDraw.Draw(image).rectangle((300, 200, 500, 400), fill='red')
        with BytesIO() as buffer:
            image.save(buffer, format='PNG')
            png = buffer.getvalue()
            return contract.process(png, 1), len(png)
    finally:
        image.close()


def main(default_provider='autodl'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provider', choices=('autodl', 'tinker', 'openrouter', 'sx'), default=default_provider)
    parser.add_argument('--sx-url-env', choices=('SX_URL', 'SX_URL_SB'), default='SX_URL')
    parser.add_argument('--coordinate-type', choices=('absolute', 'relative'), default='absolute')
    parser.add_argument('--experiment', choices=EXPERIMENTS)
    parser.add_argument('--root', type=Path, help='Optional immutable comparison plan to qualify for launch')
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home() / 'osworld-verified/OSWorld')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home() / 'osworld2/OSWorld-V2')
    args = parser.parse_args()
    plan = validate_plan(args.root) if args.root else specification(args.provider, args.sx_url_env, args.coordinate_type, args.experiment)
    if plan['provider'] != args.provider:
        raise ValueError('Probe provider differs from frozen plan')
    if not os.environ.get(plan['api_key_env']):
        raise ValueError(plan['api_key_env'] + ' missing from Linux environment')
    if args.provider == 'autodl':
        from ui_kobe.api.autodl_native import AutoDLNativeClient as Client, generation_profile
    elif args.provider == 'sx':
        from ui_kobe.api.sx_native import SXNativeClient as Client, generation_profile
        os.environ['UI_KOBE_SX_URL_ENV'] = plan['base_url_env']
    elif args.provider == 'openrouter':
        from ui_kobe.api.openrouter_native import OpenRouterNativeClient as Client, generation_profile
    else:
        from ui_kobe.api.tinker_native import TinkerNativeClient as Client, generation_profile
    args.output.mkdir(parents=True, exist_ok=False)
    identity = project_identity()
    report = {k: plan[k] for k in ('model', 'base_url', 'generation_fields', 'cua_contract')}
    report.update(complete=False, checks=[], vm_started=False, gui_actions=0,
                  started_utc=datetime.now(timezone.utc).isoformat(), project_source=identity)
    write(args.output / 'report.json', report)
    events_path = args.output / 'events.jsonl'

    def emit(event, **fields):
        with events_path.open('a', encoding='utf-8') as saved:
            saved.write(json.dumps({'event': event, **telemetry.safe(fields)}, ensure_ascii=False) + '\n')

    profile = generation_profile(plan['generation_profile']['name'])
    client = Client(profile=profile, budget=QwenTransportBudget(attempts=1),
                    emit=emit, response_dir=args.output / 'responses')

    def call(messages, tools=None, tool_choice=None):
        ledger = StepLedger(profile, time.monotonic() + 180, emit)
        payload = {'model': plan['model'], 'messages': messages, 'max_tokens': profile.max_completion_tokens}
        if tools is not None:
            payload.update(tools=tools, tool_choice=tool_choice)
        result = client.create(**payload, step_ledger=ledger, budget_role='executor', deadline=ledger.deadline)
        return result

    try:
        text = call([{'role': 'user', 'content': 'Reply with exactly OK.'}])
        if (text.model_dump()['choices'][0]['message'].get('content') or '').strip() != 'OK':
            raise ValueError('Text probe did not return the requested answer')
        report['checks'].append('text')
        write(args.output / 'report.json', report)
        from ui_kobe.osworld.official_base import verify_official_base
        verify_official_base(args.compiler_repo)
        sys.path.insert(1, str(args.compiler_repo))
        from ui_kobe.osworld.cua_contract import CUAContract
        from ui_kobe.osworld.kimi_native import native_schema, validate_native
        frame, report['vision_png_bytes'] = vision_frame(CUAContract(**plan['cua_contract']), large=args.provider=='sx')
        report['vision_data_url_chars'] = len(frame.image['image_url']['url'])
        if args.provider == 'sx' and report['vision_data_url_chars'] <= 2_000_000:
            raise ValueError('SX vision diagnostic must exercise a full-size payload above the old limit')
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': frame.instruction + '\nThis is a synthetic API diagnostic. '
             'Call computer_use once with action mouse_move at the center of the red rectangle. '
             'Use the image to find its center. Do not click or terminate.'}, frame.image]}]
        tools = [native_schema(frame)]
        result = call(messages, tools, 'auto')
        arguments, _ = validate_native(result, frame)
        if (len(arguments) != 1 or arguments[0].get('action') != 'mouse_move'
                or len(arguments[0].get('coordinate', [])) != 2):
            raise ValueError('Vision/native tool probe did not locate the synthetic rectangle')
        from mm_agents.qwen.images import project_point
        screen = frame.screenshot
        point = project_point(*arguments[0]['coordinate'], coordinate_type=screen.coordinate_type,
            original_width=screen.original_width, original_height=screen.original_height,
            model_width=screen.model_width, model_height=screen.model_height)
        if any(abs(a-b)>30 for a,b in zip(point, (400,300))):
            raise ValueError('Vision/native tool probe missed the synthetic rectangle in screen pixels')
        report['vision_compiled_point_px'] = list(point)
        report['checks'].append('vision_native_tool')
        write(args.output / 'report.json', report)
        assistant = result.model_dump()['choices'][0]['message']
        messages += [assistant, {'role': 'tool', 'tool_call_id': assistant['tool_calls'][0]['id'],
                                  'content': 'Synthetic diagnostic only; no GUI action was executed.'},
                     {'role': 'user', 'content': 'Acknowledge the diagnostic result with exactly OK, without tools.'}]
        reply = call(messages, tools, 'none').model_dump()['choices'][0]['message']
        if (reply.get('content') or '').strip() != 'OK' or reply.get('tool_calls'):
            raise ValueError('Tool reply probe did not acknowledge the result')
        report['checks'].append('tool_reply')
        if project_identity() != identity:
            raise ValueError('Source changed during live probe')
        report['complete'] = True
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': telemetry.safe(str(exc))}
        response = getattr(exc, 'response', None)
        if response is not None:
            report['http_status'] = response.status_code
    finally:
        client.close()
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        report['evidence_directory'] = str(args.output.resolve())
        write(args.output / 'report.json', report)
        if args.root:
            write(args.root / 'live-provider-check.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'project_source'}, ensure_ascii=False))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
