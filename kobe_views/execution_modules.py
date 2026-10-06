"""Task modules and bounded semantic projections over immutable execution events.

Only TaskViews reads this projection. Baseline logging does not call a model or
feed these records back to its Agent. Receipt, model assessment and score differ.
"""
from __future__ import annotations

import json

from .model import digest, dumps, plain, View
from .task_views import task_view_delta
from .task_memory import _credential_safe, _GEOMETRY_KEYS


def semantics(value):
    if isinstance(value, dict):
        return {k: semantics(v) for k, v in value.items() if k.casefold() not in _GEOMETRY_KEYS}
    if isinstance(value, list):
        return [semantics(v) for v in value]
    return value


class ExecutionModules:
    def __init__(self, memory, journal):
        self.memory, self.journal = memory, journal
        self.path = memory.directory / 'execution-modules.json'
        self.cursor, self.active, self.modules, self.recent = 0, None, {}, []
        self.views, self.previous_revision = {}, None
        self.new_events, self.gaps = [], []
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved['episode_id'] != journal.episode_id:
                raise ValueError('Task module memory belongs to another episode')
            self.cursor, self.active = saved['cursor'], saved['active']
            self.modules, self.recent = saved['modules'], saved['recent']
            self.gaps = saved.get('gaps', [])

    def save(self):
        self.memory._atomic_json(self.path, {'episode_id': self.journal.episode_id, 'cursor': self.cursor,
                                             'active': self.active, 'modules': self.modules, 'recent': self.recent,
                                             'gaps': self.gaps[-64:]})

    def publish(self, event_id, kind, value, *, objects=(), entity_id=None, ref=None, source='official-execution'):
        _credential_safe(value)
        entity = entity_id or ('execution:' + event_id)
        patch = {'entities': [{'id': entity, 'type': kind, 'label': kind}], 'claims': [
            {'id': event_id + ':value', 'subject': entity, 'predicate': kind + '.record', 'value': value,
             'objects': list(objects), 'locator': event_id},
            {'id': event_id + ':task', 'subject': entity, 'predicate': kind + '.task',
             'value': self.memory.task_id, 'objects': ['task'], 'locator': event_id}]}
        if event_id + ':value' in self.memory.snapshot.claims:
            old = self.memory.snapshot.claims[event_id + ':value']
            if dumps(old['value']) != dumps(value):
                raise ValueError('Projection event identity reused')
            return
        patch['claims'][0]['supersedes'] = [cid for cid, c in self.memory.snapshot.claims.items()
            if c['subject'] == entity and c['predicate'] == kind + '.record'
            and c['evidence']['source'] == source and self.memory.snapshot.statuses[cid] == 'active']
        self.memory.graph.ingest(self.memory._event(event_id, source, ref or str(self.path),
                                                   dumps(value), patch))

    def sync(self):
        if self.journal.closed:
            return
        while rows := self.journal.read(self.cursor):
            for row in rows:
                try:
                    self._ingest(row)
                except (ValueError, TypeError, KeyError) as exc:
                    self.gaps.append({'event_id': row['id'], 'reason': type(exc).__name__})
                self.cursor = row['seq']
                self.save()

    def _ingest(self, row):
        kind, rid = row['kind'], row['id']
        reference = self.journal.reference(row)
        if kind == 'observation':
            self.publish('frame:' + rid, 'ui_observation', {'observation_id': rid, 'images': row['images'],
                'phase': row['phase'], 'interpretation': 'recorded_image_not_interpreted_ui_state'},
                entity_id='frame:' + rid, ref=reference)
        elif kind == 'task_input' and row.get('user_response') is not None:
            self.publish('answer:' + rid, 'user_response', {'text': str(row['user_response']), 'ref': reference}, ref=reference,
                         source='official-user-simulator')
        elif kind == 'observation_annotation':
            self.publish('annotation:' + rid, 'ui_state', {'observation_id': row['observation_id'],
                'logical_page': row['logical_page'], 'state_schema': row['state_schema'],
                'grade': 'model_proposal', 'evidence_ref': row['evidence_ref']},
                objects=['frame:' + row['observation_id']], ref=reference, source='perception-proposal')
            self.new_events.append(rid)
        elif kind == 'transition':
            endpoints = ['frame:' + oid for oid in (row['source'], row['target']) if oid and
                         'frame:' + oid in self.memory.snapshot.entities]
            action = semantics((row.get('tool') or {}).get('arguments') or {'action': 'unknown'})
            value = {'transition_id': rid, 'action_semantics': action, 'raw_ref': reference,
                     'instruction_ref': row['instruction_ref'], 'decision_ref': row['decision_ref'],
                     'source': row['source'], 'target': row['target'], 'error': row['error'],
                     'receipt_count': len(row['controller_receipts']), 'effect_status': 'unknown',
                     'gaps': row['gaps'], 'module_id': self.active}
            objects = endpoints + ([self.active] if self.active else [])
            self.publish('transition:' + rid, 'execution_transition', value, objects=objects, ref=reference)
            self.recent = (self.recent + [value])[-8:]
            if self.active:
                module = self.modules[self.active]
                module['outputs'] = (module['outputs'] + [{'transition_id': rid, 'raw_ref': reference,
                    'target': row['target'], 'effect_status': 'unknown'}])[-32:]
                self.publish('module-output:' + rid, 'task_module', module, entity_id=self.active,
                             objects=module['anchors'], ref=reference, source='view-controller-proposal')
            self.new_events.append(rid)
        elif kind in ('unexecuted_command', 'decision_error', 'evaluation_result', 'evaluation_error'):
            value = {k: row.get(k) for k in ('kind', 'decision_id', 'command_index', 'reason', 'error', 'score')}
            value['raw_ref'] = reference
            self.publish('event:' + rid, 'execution_event', value, objects=[self.active] if self.active else [], ref=reference)
            self.new_events.append(rid)

    def select(self, stage, needs, *, frame, ref):
        """Open task-specific subgoal/object modules from bounded controller proposals."""
        module_id = 'module:' + digest([stage, sorted({a for n in needs for a in n['anchors']})])
        previous = self.modules.get(module_id)
        value = {'id': module_id, 'stage': stage, 'goals': [n['purpose'] for n in needs],
                 'anchors': sorted({a for n in needs for a in n['anchors']}),
                 'state': 'active', 'frame_id': frame,
                 'dependencies': [a for n in needs for a in n['anchors'] if a in self.modules],
                 'inputs': sorted({a for n in needs for a in n['anchors']}), 'outputs': [], 'needed_evidence': [],
                 'reports': {}, 'interpretation': 'model_subgoal_not_completion_verdict'}
        if previous:
            value = {**previous, **{k: value[k] for k in ('frame_id', 'goals', 'anchors', 'state')}}
        if self.active and self.active != module_id:
            self.modules[self.active]['state'] = 'paused'
            self.publish('module-pause:' + digest([self.active, frame, module_id]), 'task_module',
                self.modules[self.active], entity_id=self.active, objects=self.modules[self.active]['anchors'],
                ref=ref, source='view-controller-proposal')
        self.publish('module-select:' + digest([module_id, frame, needs]), 'task_module', value,
                     entity_id=module_id, objects=value['anchors'], ref=ref, source='view-controller-proposal')
        self.modules[module_id], self.active = value, module_id
        self.save()
        return module_id

    def report(self, role, report, *, frame):
        if not self.active:
            return
        module = self.modules[self.active]
        module['reports'][role] = {'grade': 'model_proposal', 'frame_id': frame, 'report': plain(report)}
        module['needed_evidence'] = sorted(set(module['needed_evidence']) |
            set(report.get('needed_evidence', report.get('gaps', []))))
        # Assessment=verified never changes module state to done or records an official score.
        self.publish('module-report:' + digest([self.active, role, frame, report]), 'module_report',
                     module['reports'][role], objects=[self.active], source='adviser-proposal')
        self.publish('module-state:' + digest([self.active, role, frame, report]), 'task_module', module,
                     entity_id=self.active, objects=module['anchors'], source='view-controller-proposal')
        self.save()

    def packet(self):
        modules = plain(list(self.modules.values())[-8:])
        if self.active and not any(m['id'] == self.active for m in modules):
            modules = (modules + [plain(self.modules[self.active])])[-8:]
        revision = self.memory.snapshot.revision
        indexed = {r['id']: r for r in self.journal.export_ui_kobe()['edges']} if not self.journal.closed else {}
        recent = [{**r, 'schema_delta': indexed.get(r['transition_id'], {}).get('schema_delta'),
                   'schema_delta_grade': indexed.get(r['transition_id'], {}).get('schema_delta_grade')}
                  for r in self.recent]
        packet = {'revision': revision, 'base_revision': self.previous_revision,
                  'active_module': self.active, 'modules': modules, 'omitted_modules': max(0, len(self.modules) - len(modules)),
                  'recent_transitions': recent, 'changed_execution_ids': self.new_events[-32:],
                  'omitted_change_ids': max(0, len(self.new_events) - 32), 'gaps': self.gaps[-8:],
                  'interpretation': 'recorded_execution_and_model_modules_not_verified_effects'}
        # Keep the active subgoal before optional history. Full module records
        # remain in SQLite/state; the prompt explicitly reports all omissions.
        omissions = packet['projection_omissions'] = []
        while len(dumps(packet).encode()) > 6000:
            if packet['recent_transitions']:
                packet['recent_transitions'].pop(0)
                omissions.append('older_transition')
            elif len(modules) > 1:
                modules.pop(next(i for i, m in enumerate(modules) if m['id'] != self.active))
                packet['omitted_modules'] += 1
            elif modules:
                module = modules[0]
                key = next((k for k in ('reports', 'outputs', 'needed_evidence', 'goals', 'inputs', 'anchors')
                            if module.get(k)), None)
                if key is None:
                    packet['modules'] = modules = []
                    omissions.append('active_module_detail')
                else:
                    module[key] = {} if key == 'reports' else []
                    omissions.append('active_module.' + key)
            elif packet['changed_execution_ids']:
                packet['changed_execution_ids'].pop(0)
                packet['omitted_change_ids'] += 1
            elif packet['gaps']:
                packet['gaps'].pop(0)
                omissions.append('older_gap')
            else:
                break
        return packet

    def view_changes(self, compiled):
        """Track materialized role packets; a delta is never the actor's only context."""
        changes, current = {}, {}
        for packet in compiled['packets']:
            role = packet['consumer']
            instances = [i for need in packet['needs'] for i in need.get('instances', [])]
            entities, claims, views = {}, {}, []
            for instance in instances:
                instance = instance['projection']
                for collection, target in (('entities', entities), ('claims', claims)):
                    for item in instance.get(collection, []):
                        target[item['id']] = item
                views.extend(instance.get('views', []))
            data = {'task_id': packet['task_id'], 'consumer': role, 'contract_revision': packet['contract_revision'],
                    'revision': packet['revision'], 'entities': list(entities.values()),
                    'claims': list(claims.values()), 'views': views,
                    'needs': [{k: v for k, v in n.items() if k != 'instances'} for n in packet['needs']]}
            current[role] = View(dumps(data), len(dumps(data).encode()))
            changes[role] = task_view_delta(self.views.get(role), current[role])
        self._pending_views = current
        return changes

    def delivered(self, *, views=True, events=True):
        if views:
            self.views = getattr(self, '_pending_views', self.views)
        if events:
            self.previous_revision = self.memory.snapshot.revision
            self.new_events = []
