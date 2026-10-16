"""Opt-in synthetic grounding probe through the real SX Mini predict path.

No VM, GUI dispatch, benchmark task, gold data, or scoring. Each fresh actor
returns a candidate mouse move; its compiled point must be inside the target.
This evidence never substitutes for a real guest action/result acceptance test.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


# Independent synthetic controls at asymmetric locations, including right/bottom.
TARGETS = [(1580, 140, 1660, 220), (180, 820, 260, 900),
           (1720, 880, 1800, 960), (990, 300, 1070, 380)]
INSTRUCTION = ('This is a synthetic localization diagnostic. Locate the red square on the current image. '
               'Return exactly one computer_use mouse_move at its center. Do not click, type or terminate. '
               'The candidate will be checked offline and will not be executed.')


def synthetic_image(box):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1920, 1080), '#e8eaed')
    draw = ImageDraw.Draw(image)
    for x, y in ((100, 100), (700, 700), (1400, 400)):
        draw.rectangle((x, y, x+64, y+64), fill='#3366cc')
    draw.rectangle(box, fill='#ee2020')
    output = BytesIO()
    image.save(output, format='PNG')
    return {'screenshot': output.getvalue()}


def inspect_candidate(actor, observation, box):
    """The real actor builds its own schema, prompt, views and native history."""
    from ui_kobe.osworld.transitions import decision_tools
    actor.execution_journal.begin(INSTRUCTION, observation, step=1)
    response, commands = actor.predict(INSTRUCTION, observation)
    actor.execution_journal.decide(response, commands, step=1, tools=decision_tools(actor))
    native = actor.last_trace['native_actions']
    point = None
    if len(native) == len(commands) == 1 and native[0].get('action') == 'mouse_move':
        tree = ast.parse(commands[0])
        call = tree.body[0].value if len(tree.body)==1 and isinstance(tree.body[0], ast.Expr) else None
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id=='pyautogui'
                and call.func.attr=='moveTo' and len(call.args)==2 and not call.keywords):
            point = [ast.literal_eval(a) for a in call.args]
    center = [(box[0]+box[2])/2, (box[1]+box[3])/2]
    matched = bool(point and all(type(n) in (int,float) for n in point)
                   and all(abs(a-b)<=30 for a,b in zip(point, center)))
    return {'passed': matched, 'expected_center_px': center, 'compiled_point_px': point,
            'native_actions': native, 'commands': commands, 'frame': actor.frame.metadata,
            'usage': actor.last_trace.get('usage'), 'step_tokens': actor.last_trace.get('step_tokens'),
            'views': actor.last_trace.get('taskviews_mini'),
            'gui_dispatched': False, 'journal_decision_unexecuted': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly send bounded, billable synthetic API requests')
    parser.add_argument('--coordinate-type', choices=('absolute','relative'), default='absolute')
    from scripts.verified_invoice import EXPERIMENTS
    parser.add_argument('--experiment', choices=EXPERIMENTS, default='legacy-low35')
    parser.add_argument('--sx-url-env', choices=('SX_URL','SX_URL_SB'), default='SX_URL_SB')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, help='Optional new frozen SX plan to receive this prerequisite proof')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home()/'osworld2/OSWorld-V2')
    args = parser.parse_args()
    if not args.live:
        parser.error('No API request sent: --live is required for this synthetic probe')
    from scripts.osworld_native_experiment import require_scope
    require_scope(128*1024**2)
    from scripts.verified_invoice import project_identity, specification, validate_plan, write
    from ui_kobe.osworld.official_base import verify_official_base
    from ui_kobe.osworld.transitions import TransitionJournal
    from ui_kobe.osworld.sx_native import SXMiniTaskViewsNativeAgent
    from ui_kobe.osworld.cua_contract import CUAContract
    plan = validate_plan(args.root) if args.root else specification('sx', args.sx_url_env, args.coordinate_type, args.experiment)
    if plan['provider'] != 'sx':
        raise ValueError('This grounding probe is for the declared SX Mini actor only')
    policy = plan.get('mini_grounding_check_policy', 'all_targets_within30px')
    collect_all = policy == 'collect_all_record_accuracy'
    contract = CUAContract(**plan['cua_contract'])
    args.output.mkdir(parents=True, exist_ok=False)
    source = project_identity()
    report = {'kind':'synthetic_mini_grounding', 'complete':False, 'cases':[],
              'policy':policy, 'collection_complete':False, 'all_targets_passed':False,
              'started_utc':datetime.now(timezone.utc).isoformat(), 'project_source':source,
              'model':plan['model'], 'base_url':plan['base_url'], 'cua_contract':contract.snapshot(),
              'generation_fields':plan['generation_fields'], 'live_api_called':False,
              'vm_started':False, 'gui_actions':0, 'benchmark_score':None,
              'benchmark_launch_qualification':False}
    os.environ.update(UI_KOBE_TASKVIEWS_PROFILE='mini_fixed_v1', UI_KOBE_MINI_CONTROLS_VIEW='disabled',
        UI_KOBE_TASKVIEWS_FEEDBACK_V10='0', UI_KOBE_GENERATION_PROFILE=plan['generation_profile']['name'],
        UI_KOBE_SX_URL_ENV=plan['base_url_env'], UI_KOBE_CUA_CONTRACT_JSON=json.dumps(contract.snapshot()))
    actor = None
    try:
        write(args.output/'report.json', report)
        verify_official_base(args.compiler_repo)
        sys.path.insert(1, str(args.compiler_repo))
        for index, box in enumerate(TARGETS, 1):
            path = args.output / f'case-{index}'
            os.environ['UI_KOBE_TELEMETRY_DIR'] = str(path)
            from ui_kobe.osworld import telemetry
            telemetry.install_api(path)
            actor = SXMiniTaskViewsNativeAgent(model=plan['model'],base_url=plan['base_url'],
                temperature=0,max_tokens=16000,max_api_retries=1,retry_sleep_cap=15.0)
            actor.execution_journal = TransitionJournal(path/'journal',task_id='synthetic-localization',
                                                         run_id=f'synthetic-{index}',contract=contract)
            report['live_api_called'] = True
            record = inspect_candidate(actor, synthetic_image(box), box)
            report['cases'].append(record)
            actor.close()
            actor = None
            write(args.output/'report.json', report)
            print(json.dumps({'case':index, 'passed':record['passed'],
                              'compiled_point_px':record['compiled_point_px'] }), flush=True)
            if not record['passed'] and not collect_all:
                break  # Preserve the first failure; never auto-switch units or retry for success.
        report['collection_complete'] = len(report['cases'])==len(TARGETS)
        report['all_targets_passed'] = report['collection_complete'] and all(c['passed'] for c in report['cases'])
        report['complete'] = report['collection_complete'] and (collect_all or report['all_targets_passed'])
    except Exception as exc:
        from ui_kobe.osworld.telemetry import safe
        report['error'] = {'type':type(exc).__name__, 'message':safe(str(exc))}
    finally:
        if actor is not None:
            try:
                actor.close()
            except Exception as exc:
                from ui_kobe.osworld.telemetry import safe
                report['close_error'] = {'type':type(exc).__name__, 'message':safe(str(exc))}
                report['complete'] = False
        report['source_unchanged'] = project_identity()==source
        report['complete'] = report['complete'] and report['source_unchanged']
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write(args.output/'report.json', report)
        if args.root:
            write(args.root/'mini-grounding-check.json', report)
    return 0 if report['complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
