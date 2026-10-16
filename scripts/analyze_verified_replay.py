"""Offline postmortem of saved evidence; never calls an API, GUI or evaluator."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def analyze(root, output):
    import fitz
    from PIL import Image, ImageDraw

    output.mkdir(parents=True, exist_ok=False)
    plan = json.loads((root / 'plan.json').read_text())
    result = {'run': str(root), 'plan_sha256': digest(root / 'plan.json'),
              'mode': 'saved_evidence_only', 'live_calls': 0, 'gui_actions': 0,
              'new_official_evaluations': 0, 'arms': {}}
    selections = {'ui_kobe_like': [1, 3, 5, 11, 32, 33, 38, 40],
                  'baseline': [1, 19, 20, 27, 30, 31, 39, 40],
                  'taskviews': [1, 14, 15, 16, 21, 25, 30, 40]}
    for arm in plan['arms']:
        folder = root / arm
        official = folder / 'official' / plan['domain'] / plan['task_id']
        trajectory = list(rows(official / 'traj.jsonl'))
        record = {'outcome': json.loads((folder / 'outcome.json').read_text()),
                  'actions': trajectory, 'decisions': [], 'history': [], 'views': [],
                  'controller_results': Counter(), 'pdfs': []}
        for log in sorted((folder / 'telemetry').glob('events-*.jsonl')):
            for event in rows(log):
                kind = event.get('event')
                if kind == 'decision':
                    trace = event.get('framework_trace') or {}
                    record['decisions'].append({'step': event['step'],
                        'native_actions': trace.get('native_actions'),
                        'history_turns_omitted': trace.get('history_turns_omitted')})
                elif kind == 'history_trim':
                    record['history'].append({k: event.get(k) for k in
                        ('step', 'retained_history_turns', 'history_turns_omitted', 'retained_history_text_chars')})
                elif kind == 'mini_fixed_views':
                    record['views'].append({k: event.get(k) for k in ('step', 'packet_bytes', 'views')})
                elif kind == 'controller_result' and event.get('phase') == 'action':
                    record['controller_results'][json.dumps(event.get('result'), sort_keys=True)] += 1
        for pdf in sorted((folder / 'cache' / plan['task_id']).glob('*.pdf')):
            with fitz.open(pdf) as document:
                pages = [page.get_text() for page in document]
            record['pdfs'].append({'file': str(pdf.relative_to(root)), 'sha256': digest(pdf),
                'page_text_lengths': [len(page.strip()) for page in pages], 'page_text': pages})
        # Contact sheets are diagnostic indexes; original full-resolution files remain authoritative.
        for group in range(2):
            sheet = Image.new('RGB', (1920, 1120), 'white')
            draw = ImageDraw.Draw(sheet)
            for index, step in enumerate(selections[arm][group * 4:(group + 1) * 4]):
                row = next(row for row in reversed(trajectory) if row['step_num'] == step)
                with Image.open(official / row['screenshot_file']) as original:
                    thumb = original.resize((960, 540))
                    x, y = index % 2 * 960, index // 2 * 560
                    sheet.paste(thumb, (x, y + 20))
                    draw.text((x + 5, y + 3), f'{arm} after step {step}: {row["action"]}', fill='black')
            sheet.save(output / f'{arm}-{group + 1}.png')
        result['arms'][arm] = record
    (output / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'arms': {arm: {'decisions': len(value['decisions']),
        'actions': len(value['actions']), 'pdfs': len(value['pdfs']),
        'controller_results': value['controller_results']} for arm, value in result['arms'].items()}}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.run_dir.resolve(), args.output.resolve())
