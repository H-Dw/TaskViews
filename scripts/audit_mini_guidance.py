"""Read new guidance telemetry; no model calls, GUI actions or benchmark reads."""
import argparse
import json
from pathlib import Path


def summarize(paths, annotations=None):
    frames, receipts = {}, 0
    for path in paths:
        with Path(path).open(encoding='utf-8') as handle:
            for line in handle:
                row = json.loads(line)
                if row.get('event') not in ('mini_guidance_prepared', 'mini_guidance_delivery'):
                    continue
                key = (row['episode_id'], row['frame_id'], row.get('context_revision', 0))
                item = frames.setdefault(key, {'prepared': None, 'delivered': None})
                if row['event'] == 'mini_guidance_prepared':
                    if item['prepared'] is not None and item['prepared']['metrics'] != row['metrics']:
                        raise ValueError('Conflicting guidance snapshots for the same episode/frame')
                    item['prepared'] = row
                else:
                    receipts += 1
                    if row['metrics']['packet_delivered']:
                        if item['delivered'] is not None and item['delivered'] != row['metrics']:
                            raise ValueError('Conflicting delivery metrics for the same episode/frame')
                        item['delivered'] = row['metrics']
    if any(v['prepared'] is None for v in frames.values()):
        raise ValueError('Guidance delivery has no prepared snapshot')
    metrics = [v['delivered'] or v['prepared']['metrics'] for v in frames.values()]

    def total(key):
        return sum(m[key] for m in metrics)

    def ratio(n, d):
        return n / d if d else None

    delivered_groups = sum(len(m['delivered_group_ids']) for m in metrics)
    invalid = total('known_stale_or_inapplicable_groups')
    result = {'measurement_unit': 'episode_and_frame_any_successful_request_receipt', 'frames': len(frames),
            'decision_frames': len({key[:2] for key in frames}),
            'context_revisions': len(frames),
            'request_receipts_including_retries': receipts,
            'packet_delivery_rate': ratio(total('packet_delivered'), len(frames)),
            'empty_keyboard_frame_rate': (ratio(sum(m['selection_status'] in ('empty', 'no_match') for m in metrics), len(frames))
                                    if all('selection_status' in m for m in metrics) else None),
            'delivered_reference_frame_rate': ratio(sum(bool(m['packet_delivered'] and m['delivered_group_ids'])
                                                       for m in metrics), len(frames)),
            'directory_visibility_rate': ratio(total('directory_visible'), len(frames)),
            'needed_recipe_count': total('needed_recipe_count'),
            'needed_recipes_delivered': total('needed_recipes_delivered'),
            'needed_recipe_delivery_rate': ratio(total('needed_recipes_delivered'), total('needed_recipe_count')),
            'needed_group_delivery_rate': ratio(total('needed_groups_delivered'), total('needed_group_count')),
            'workflow_completeness_rate': ratio(total('complete_workflow_groups'), total('workflow_group_count')),
            'known_stale_or_inapplicable_rate': ratio(invalid, delivered_groups),
            'applicability_unknown_groups': total('applicability_unknown_groups'),
            'semantic_inapplicability_rate': None, 'adoption': 'unknown',
            'need_basis': 'deterministic_router_estimate_requires_independent_annotation',
            'benchmark_score': None}
    if any(key[2] for key in frames):
        result['measurement_unit'] = 'episode_frame_and_context_revision_any_successful_request_receipt'
    if annotations is not None:
        seen = set()
        needed = sent = workflows = complete = stale = reviewed = 0
        for label in annotations:
            key = (label['episode_id'], label['frame_id'], label.get('context_revision', 0))
            if key not in frames or key in seen:
                raise ValueError('Annotation has an unknown or duplicate episode/frame')
            seen.add(key)
            item = frames[key]
            delivered = set((item['delivered'] or {}).get('delivered_group_ids', []))
            all_records = {c['record']['guide_id']: c['record'] for c in item['prepared']['selection']['groups']}
            recipes = {r['id'] for name in delivered for r in all_records[name]['recipes']}
            required = set(label['needed_recipe_ids'])
            groups = set(label['needed_workflow_group_ids'])
            invalid = set(label['stale_or_inapplicable_delivered_group_ids'])
            if label.get('applicability_review_complete') is not True or not invalid <= delivered:
                raise ValueError('Annotation must review all delivered groups and name only delivered invalid groups')
            needed += len(required)
            sent += len(required & recipes)
            workflows += len(groups)
            complete += len(groups & delivered)  # Whole-group delivery is guaranteed by the packer.
            stale += len(invalid)
            reviewed += len(delivered)
        result['independent_annotations'] = {
            'frames': len(seen), 'coverage_rate': ratio(len(seen), len(frames)),
            'needed_recipe_delivery_rate': ratio(sent, needed),
            'workflow_completeness_rate': ratio(complete, workflows),
            'stale_or_inapplicable_guidance_rate': ratio(stale, reviewed),
            'basis': 'external_annotation_not_action_parameter_match'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, action='append', required=True,
                        help='Exact events JSONL; repeat for additional process logs')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--annotations', type=Path, help='Optional independent frame labels; see guidance documentation')
    args = parser.parse_args()
    # Exclusive creation preserves earlier reports.
    with args.output.open('x', encoding='utf-8') as handle:
        labels = json.loads(args.annotations.read_text(encoding='utf-8')) if args.annotations else None
        json.dump(summarize(args.events, labels), handle, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
