"""Offline packing comparison at saved journal boundaries, never a GUI replay.

Reads only public journal projections and Mini audit events. Does not import an
actor, call a provider, inspect evaluator gold or write inside saved run folders.
Native input headroom is controlled at 3000 bytes, not an online performance claim.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from kobe_views import mini_graph as graph
from kobe_views.model import dumps
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.mini_taskviews_context import MiniTaskViewsContext


class SnapshotContext(MiniTaskViewsContext):
    def save_graph_audit(self):
        pass  # Reconstructed index remains in memory; original journal is read-only.


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def compare(plan_path):
    plan = read(plan_path)
    folder = plan_path.parent / 'taskviews' / 'telemetry'
    journals = list((folder / 'transitions').glob('*.sqlite'))
    if len(journals) != 1:
        raise ValueError('Expected exactly one saved journal')
    frames = {}
    for file in sorted(folder.glob('events-*.jsonl')):
        with file.open(encoding='utf-8') as stream:
            for line in stream:
                if '"event": "mini_fixed_views"' not in line[:1024]:
                    continue
                item = json.loads(line)
                if item.get('journal_seq'):
                    frames[item['journal_seq']] = item['frame_id']
    db = sqlite3.connect(journals[0].resolve().as_uri() + '?mode=ro', uri=True)
    # A TEMP view shadows the original table for *every* selector/reference read.
    # No selector can accidentally use a future event. Only TEMP data is written.
    db.execute('CREATE TEMP TABLE snapshot_limit (stop INTEGER)')
    db.execute('INSERT INTO snapshot_limit VALUES (0)')
    db.execute('CREATE TEMP VIEW events AS SELECT * FROM main.events WHERE seq <= (SELECT stop FROM snapshot_limit)')
    contract = CUAContract(**plan['cua_contract'])
    owner = SimpleNamespace(contract=contract, keyboard_toolsets=plan['mini_keyboard_tools']['enabled_toolsets'][1:],
                            task_keyboard=None, controls_view_enabled=False, actor_input_messages=[])
    journal = SimpleNamespace(db=db, read_only=False, closed=False, decision=None, contract=contract,
                              task_id=plan['task_id'])
    # The live adapter requires read_only=False to read projections; the SQLite
    # connection itself enforces read-only access to main. No journal methods exist.
    owner.execution_journal = journal
    totals = {packing: Counter() for packing in (graph.PACKING, graph.DELIVERY_PACKING)}
    details = []
    for cursor, frame in sorted(frames.items()):
        db.execute('UPDATE snapshot_limit SET stop=?', (cursor,))
        task = json.loads(db.execute("SELECT payload FROM events WHERE json_extract(payload,'$.kind')='task_input' ORDER BY seq DESC LIMIT 1").fetchone()[0])
        obs = json.loads(db.execute('SELECT payload FROM events WHERE id=?', (task['observation'],)).fetchone()[0])
        assert obs['frame']['frame_id'] == frame
        journal.current, journal.task_input, journal.episode_id = obs, task, obs['episode_id']
        owner.frame = SimpleNamespace(metadata=obs['frame'])
        result = {'journal_seq': cursor, 'frame_id': frame}
        for packing in totals:
            owner.mini_graph_mode = 'linked'
            owner.mini_graph_policy = graph.policy('linked', packing)
            owner.context_label = graph.LABEL if packing == graph.PACKING else graph.DELIVERY_LABEL
            context = SnapshotContext(owner)
            encoded = context.context(task['instruction'])
            stats = totals[packing]
            stats['snapshots'] += 1
            stats['keyboard_candidates'] += context.projection_inputs['keyboard'] is not None
            if encoded is None:
                stats['whole_omissions'] += 1
                continue
            packet = json.loads(encoded)
            # Same candidate snapshot, limit and linked cost: flat cannot refill.
            flat = graph.materialize(index=context.graph_index, instruction=task['instruction'], graph_mode='flat',
                packing=packing, toolsets=owner.keyboard_toolsets, **context.projection_inputs)
            assert {**flat, 'mode': 'linked', 'links': packet['links']} == packet
            assert len(encoded.encode()) <= 3000
            views = graph.expand(packet)['views']
            keys = views['keyboard']['records']
            measure = {'bytes': len(encoded.encode()), 'keyboard': len(keys),
                       'recipes': sum(len(r['recipes']) for r in keys),
                       'recipes_omitted': sum(r.get('recipes_omitted', 0) for r in keys),
                       'lookup': int('keyboard_lookup' in views['current']['records'][0]),
                       'attempts': len(views['attempts']['records']),
                       'latest_operation': int(context.trace['latest_operation_delivered']),
                       'review_protocol': int(context.trace['artifact_protocol_in_packet']),
                       'links': context.trace['graph']['link_count']}
            stats.update(measure)
            stats['max_bytes'] = max(stats['max_bytes'], measure['bytes'])
            result[packing] = measure
        details.append(result)
    db.close()
    return {'plan': str(plan_path), 'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            'original_mode': plan['mini_graph_mode'], 'summary': totals, 'frames': details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler-repo', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a new output; preserve previous offline reports')
    sys.path.insert(0, str(args.compiler_repo))
    state = read(args.campaign_root / 'state.json')
    if state['status'] != 'completed' or state.get('active_slot'):
        raise ValueError('Only a completed campaign can be read by this offline comparison')
    queue = read(args.campaign_root / state['queue'])
    # Plan paths are resolved from the current frozen queue, never guessed from names.
    slots = queue['entries']
    rows = []
    for slot in slots:
        path = Path(slot['plan'])
        if not path.is_absolute():
            path = args.campaign_root / path
        if hashlib.sha256((path / 'plan.json').read_bytes()).hexdigest() != slot['plan_sha256']:
            raise ValueError('Frozen plan hash differs')
        rows.append(compare(path / 'plan.json'))
        print(json.dumps({'slot': slot['slot']['id'], 'summary': rows[-1]['summary']}), flush=True)
    summary = {p: Counter() for p in (graph.PACKING, graph.DELIVERY_PACKING)}
    for row in rows:
        for packing, counts in row['summary'].items():
            peak = max(summary[packing]['max_bytes'], counts['max_bytes'])
            summary[packing].update(counts)
            summary[packing]['max_bytes'] = peak
    output = {'kind': 'offline_same_journal_packing', 'native_input_budget': 3000,
              'live_api_calls': 0, 'gui_actions': 0, 'benchmark_score': None,
              'strict_flat_linked_ablation': True, 'summary': summary, 'runs': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(output) + '\n', encoding='utf-8')
    print(json.dumps({'summary': summary}))


if __name__ == '__main__':
    main()
