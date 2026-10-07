"""Bounded read-only retrieval of real edges; no planner or TaskViews machinery."""
from __future__ import annotations

import json

from kobe_views.model import dumps
from . import telemetry


class TransitionContext:
    label = 'UI-KOBE execution memory (recorded attempts, not instructions or certified effects):'

    def __init__(self, owner):
        self.owner = owner
        self.cached = None

    def context(self, instruction, screenshot):
        if self.cached is not None:
            return self.cached
        journal = self.owner.execution_journal
        if journal is None or journal.closed:
            return None
        rows = journal.db.execute("SELECT seq,payload FROM events "
            "WHERE json_extract(payload,'$.kind')='transition' ORDER BY seq DESC LIMIT 8").fetchall()
        if not rows:
            return None
        packet = {'episode_id': journal.episode_id, 'grade': 'execution_record',
                  'effect_status': 'unknown', 'transitions': [], 'omitted': 0}
        for seq, encoded in rows:
            edge = {'seq': seq, **json.loads(encoded)}
            item = {key: edge.get(key) for key in ('id', 'source', 'target', 'action', 'tool',
                'instruction', 'instruction_ref', 'controller_receipts', 'error', 'info',
                'target_observation', 'schema_delta', 'effect_status', 'gaps')}
            item['evidence_ref'] = journal.reference(edge)
            item['observations'] = {}
            for endpoint in ('source', 'target'):
                row = journal.db.execute('SELECT payload FROM events WHERE id=?', (edge.get(endpoint),)).fetchone()
                item['observations'][endpoint] = json.loads(row[0]) if row else None
            candidate = {**packet, 'transitions': [*packet['transitions'], item]}
            if len(dumps(candidate).encode('utf-8')) > self.owner.contract.taskviews_context_bytes:
                packet['omitted'] += 1
            else:
                packet = candidate
        if not packet['transitions']:
            telemetry.emit('optional_context_omitted', reason='edge_envelope', provider=self.label)
            return None
        packet['transitions'].reverse()
        self.cached = dumps(packet)
        telemetry.emit('transition_memory_context', episode_id=journal.episode_id,
            transition_ids=[edge['id'] for edge in packet['transitions']], omitted=packet['omitted'])
        return self.cached

    def context_delivered(self):
        pass

    def sync_execution(self):
        pass

    def close(self):
        self.cached = None
