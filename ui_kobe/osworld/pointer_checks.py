"""Isolated mouse-grounding cases and an observer-only custom evaluator.

Hidden rectangles are fixture geometry, never actor hints or repaired actions.
The same original GUI commands, screenshots and receipts are still required.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


def _case(name, labels, layouts):
    return {'id': 'taskviews-pointer-' + name + '-v11', 'test_kind': 'project_custom_pointer',
        'instruction': ('In Pointer Lab, use the mouse to click ' + ', then '.join(labels)
            + ', once each and in that order. Locate each control in the current image; '
              'controls may move. Confirm all clicks were accepted, then finish. '
              'Do not use keyboard activation, terminal, console or scripting.'),
        'initial_state': 'Isolated local mouse-only canvas; accepted events initially empty',
        'expected_guest_artifact': '/home/user/Desktop/tv_pointer_' + name + '.json',
        'targets': labels, 'layouts': layouts, 'screen_size': [1920, 1080],
        'official_benchmark_score': None}


POINTER_CASES = {
    'pointer-corners': _case('corners', ['Cobalt', 'Willow', 'Amber'], [{
        'Cobalt': [1540, 90, 180, 80], 'Willow': [140, 810, 200, 80],
        'Amber': [840, 470, 200, 80]}]),
    'pointer-relocation': _case('relocation', ['Moss', 'Violet', 'River'], [
        {'Moss': [140, 180, 110, 48], 'Violet': [790, 850, 110, 42], 'River': [1500, 750, 120, 48]},
        {'Moss': [1440, 750, 110, 48], 'Violet': [1510, 170, 110, 42], 'River': [820, 480, 120, 48]},
        {'Moss': [820, 480, 110, 48], 'Violet': [140, 180, 110, 42], 'River': [1500, 840, 120, 48]}]),
}


def rectangles(spec, revision):
    layout = spec['layouts'][min(revision, len(spec['layouts']) - 1)]
    return {label: [box[0], box[1], box[0] + box[2], box[1] + box[3]]
            for label, box in layout.items()}


def hit_target(spec, revision, point):
    x, y = point
    hits = [label for label, box in rectangles(spec, revision).items()
            if box[0] <= x < box[2] and box[1] <= y < box[3]]
    if len(hits) > 1:
        raise ValueError('Overlapping pointer targets')
    return hits[0] if hits else None


def validate_case(spec):
    if spec['screen_size'] != [1920, 1080] or not 1 <= len(spec['targets']) <= 6:
        raise ValueError('Pointer cases use the fixed original screen and bounded target count')
    if len(set(spec['targets'])) != len(spec['targets']) or not 1 <= len(spec['layouts']) <= 6:
        raise ValueError('Pointer labels/layouts must be bounded and unambiguous')
    for revision in range(len(spec['layouts'])):
        boxes = rectangles(spec, revision)
        if set(boxes) != set(spec['targets']):
            raise ValueError('Each layout must contain every declared visible label')
        for box in boxes.values():
            if (any(type(v) is not int for v in box) or not 0 <= box[0] < box[2] <= 1920
                    or not 0 <= box[1] < box[3] <= 1080):
                raise ValueError('Invalid fixture rectangle')
        for name, a in boxes.items():
            for other, b in boxes.items():
                if name < other and max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]):
                    raise ValueError('Overlapping pointer targets')


def grade_pointer_log(path, spec, *, terminal=False):
    result = {'test_kind': 'project_custom_pointer', 'official_score': None,
              'custom_score': None, 'checks': {}, 'evaluation_started': terminal}
    if not terminal:
        return result
    checks = {'observer_log': False, 'mouse_events_valid': False, 'ordered_targets': False}
    accepted, misses, wrong_order = [], 0, 0
    try:
        validate_case(spec)
        path = Path(path)
        if path.stat().st_size > 256 * 1024:
            raise ValueError('Oversized mouse observer log')
        data = json.loads(path.read_text())
        if (data['case_id'] != spec['id'] or data['screen_size'] != spec['screen_size']
                or data['window_origin'] != [0, 0] or data['initial_accepted'] != []):
            raise ValueError('Observer belongs to a different fixture')
        events = data['events']
        if not isinstance(events, list) or len(events) > 200:
            raise ValueError('Unbounded mouse observer events')
        checks['observer_log'] = True
        for seq, event in enumerate(events, 1):
            if (type(event['seq']) is not int or event['seq'] != seq or event['kind'] != 'mouse_release'
                    or type(event['button']) is not int or event['button'] != 1
                    or type(event['revision']) is not int or event['revision'] != len(accepted)):
                raise ValueError('Invalid mouse event or layout revision')
            point = event['screen_point']
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
                raise ValueError('Invalid observed pointer point')
            if not 0 <= point[0] < 1920 or not 0 <= point[1] < 1080:
                raise ValueError('Pointer observer point is outside the original screen')
            if event['rectangles'] != rectangles(spec, len(accepted)):
                raise ValueError('Observer target geometry differs from the declared fixture')
            hit = hit_target(spec, len(accepted), point)
            expected = spec['targets'][len(accepted)] if len(accepted) < len(spec['targets']) else None
            valid = hit is not None and hit == expected
            if event['hit'] != hit or event['accepted'] is not valid:
                raise ValueError('Observer acceptance contradicts its raw mouse coordinates')
            if valid:
                accepted.append(hit)
            elif hit is None:
                misses += 1
            else:
                wrong_order += 1
        if data['accepted'] != accepted:
            raise ValueError('Final state does not match the ordered physical events')
        checks['mouse_events_valid'] = True
        checks['ordered_targets'] = accepted == spec['targets']
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        pass
    total = len(accepted) + misses + wrong_order
    result.update(checks=checks, custom_score=float(all(checks.values())),
        mouse_metrics={'accepted': accepted, 'misses': misses, 'wrong_order': wrong_order,
            'event_count': total, 'precision': len(accepted) / total if total else 0.0})
    return result
