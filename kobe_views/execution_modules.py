"""Task modules and bounded semantic projections over immutable execution events.

Only TaskViews reads this projection. Baseline logging does not call a model or
feed these records back to its Agent. Receipt, model assessment and score differ.
"""
from __future__ import annotations

import json
import hashlib
import re
from collections.abc import Mapping
from datetime import datetime

from .model import digest, dumps, plain, View
from .task_views import task_view_delta
from .task_memory import _credential_safe, _GEOMETRY_KEYS


def semantics(value):
    if isinstance(value, dict):
        return {k: semantics(v) for k, v in value.items() if k.casefold() not in _GEOMETRY_KEYS}
    if isinstance(value, list):
        return [semantics(v) for v in value]
    return value


class ExecutionPacketBudgetError(ValueError):
    """The remaining projection contains only protected execution references."""

    def __init__(self, projection):
        super().__init__('Budget cannot hold the latest action and unresolved failure references')
        self.projection = plain(projection)


class ExecutionModules:
    def __init__(self, memory, journal):
        self.memory, self.journal = memory, journal
        self.path = memory.directory / 'execution-modules.json'
        self.cursor, self.active, self.modules, self.recent = 0, None, {}, []
        self.views, self.previous_revision = {}, None
        self.new_events, self.gaps = [], []
        self.subgoals, self.effects, self.unresolved = {}, {}, []
        self.effect_order = []
        self.selected_needs, self.page_id = [], None
        self.uncertainty_reviews = {}
        self.application_failure_memory = {'module_id': None, 'reports': [], 'omitted_reports': 0}
        self._application_failures_ready = False
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved['episode_id'] != journal.episode_id:
                raise ValueError('Task module memory belongs to another episode')
            self.cursor, self.active = saved['cursor'], saved['active']
            self.modules, self.recent = saved['modules'], saved['recent']
            self.gaps = saved.get('gaps', [])
            self.subgoals = saved.get('subgoals', {})
            self.effects = saved.get('effects', {})
            self.effect_order = saved.get('effect_order', [])
            self.unresolved = saved.get('unresolved', [])
            self.selected_needs, self.page_id = saved.get('selected_needs', []), saved.get('page_id')
            self.uncertainty_reviews = saved.get('uncertainty_reviews', {})
            self.application_failure_memory = saved.get('application_failure_memory', self.application_failure_memory)
            if (len(self.effect_order) != len(self.effects)
                    or len(set(self.effect_order)) != len(self.effect_order)
                    or set(self.effect_order) != set(self.effects)):
                self._restore_effect_order()

    def _restore_effect_order(self):
        """Migrate sorted-key caches from accepted immutable reports, not IDs.

        Canonical JSON sorts dictionaries. Their insertion order after a reload
        cannot identify the oldest operation. Historical accepted reports remain
        in this memory graph; only exact transition-bound values are recovered.
        """
        candidates = dict(self.effects)
        for claim in self.memory.snapshot.claims.values():
            if claim['predicate'] != 'module_report.record':
                continue
            value = claim['value']
            if not isinstance(value, Mapping):
                continue
            report = value.get('report')
            if (value.get('grade') != 'model_proposal' or not isinstance(report, Mapping)
                    or not report or report.get('grade') != 'model_proposal'
                    or not report.get('transition_id') or not report.get('checks')):
                continue
            identity = report['transition_id']
            edge = self.event(identity)
            if (edge and edge.get('kind') == 'transition'
                    and edge['target'] == report.get('target_observation_id')
                    and report.get('raw_transition_ref', '').endswith('#' + identity)):
                candidates[identity] = plain(report)
        ordered = []
        for identity in candidates:
            row = self.journal.db.execute('SELECT seq FROM events WHERE id=?', (identity,)).fetchone()
            if row:
                ordered.append((row[0], identity))
        self.effect_order = [identity for _, identity in sorted(ordered)][-64:]
        self.effects = {identity: candidates[identity] for identity in self.effect_order}

    @staticmethod
    def _application_failure_checks(report):
        if report.get('grade') != 'model_proposal' or report.get('assessment') != 'not_observed':
            return []
        return [{key: plain(item[key]) for key in ('kind', 'assessment', 'quotes')}
                for item in report.get('checks', []) if item.get('kind') in {'submission', 'object'}
                and item.get('assessment') == 'not_observed' and item.get('quotes')]

    def enable_application_failure_retention(self):
        """Recover accepted application feedback independently of the recent cache.

        Eight distinct whole reports for the active subgoal preserve the earliest
        response to each failure. Repeated attempts and dialog dismissal cannot
        evict it. On restore/subgoal change, rebuild once from immutable accepted
        graph reports with exact transition bindings; never parse actor history.
        Historical checks remain proposals, not command bans or current state.
        """
        self.application_failure_retention_v12 = True
        if (self._application_failures_ready
                and self.application_failure_memory['module_id'] == self.active):
            return
        ordered = []
        for claim in self.memory.snapshot.claims.values():
            if claim['predicate'] != 'module_report.record':
                continue
            value = claim['value']
            report = value.get('report') if isinstance(value, Mapping) else None
            if (not isinstance(report, Mapping) or value.get('grade') != 'model_proposal'
                    or report.get('module_id') != self.active or not self._application_failure_checks(report)):
                continue
            identity = report.get('transition_id')
            edge = self.event(identity)
            if (not edge or edge.get('kind') != 'transition'
                    or edge['target'] != report.get('target_observation_id')
                    or not report.get('raw_transition_ref', '').endswith('#' + str(identity))):
                continue
            row = self.journal.db.execute('SELECT seq FROM events WHERE id=?', (identity,)).fetchone()
            occurred = claim.get('evidence', {}).get('occurred_at')
            stamp = datetime.fromisoformat(occurred.replace('Z', '+00:00')).timestamp() if occurred else 0
            ordered.append((row[0], stamp, dumps(report), report))
        self.application_failure_memory = {'module_id': self.active, 'reports': [], 'omitted_reports': 0}
        self._application_failures_ready = True
        for _, _, _, report in sorted(ordered, key=lambda row: row[:3]):
            self._retain_application_failure(report)

    def _retain_application_failure(self, report):
        if not getattr(self, 'application_failure_retention_v12', False):
            return
        checks = self._application_failure_checks(report)
        if not checks or report.get('module_id') != self.active:
            return
        if self.application_failure_memory['module_id'] != self.active:
            self.enable_application_failure_retention()
        saved = self.application_failure_memory
        signature = dumps(checks)
        if any(row['transition_id'] == report['transition_id']
               or dumps(self._application_failure_checks(row)) == signature for row in saved['reports']):
            return
        if len(saved['reports']) < 8:
            saved['reports'].append(plain(report))
        else:
            saved['omitted_reports'] += 1

    def _prior_effect_items(self):
        retained = (self.application_failure_memory['reports']
                    if getattr(self, 'application_failure_retention_v12', False)
                    and self.application_failure_memory['module_id'] == self.active else [])
        identities = {report['transition_id'] for report in retained}
        items = [(report['transition_id'], report) for report in retained] + [
            (identity, self.effects[identity]) for identity in getattr(self, 'effect_order', list(self.effects))
            if identity not in identities]
        if getattr(self, 'application_failure_retention_v12', False):
            # The durable store keeps the first provenance of each rejection.
            # A short local brief must also expose the most recent route's
            # response instead of filling its budget with the oldest error.
            # SQLite event sequence, not JSON/ID order or a guessed timestamp,
            # orders the unchanged original reports. This is projection only.
            ordered = []
            for identity, report in items:
                row = self.journal.db.execute('SELECT seq FROM events WHERE id=?', (identity,)).fetchone()
                if not row:
                    raise ValueError('Historical feedback requires its original operation sequence')
                ordered.append((row[0], identity, report))
            items = [(identity, report) for _, identity, report in sorted(ordered, key=lambda row: row[0], reverse=True)]
        return items

    def save(self):
        self.memory._atomic_json(self.path, {'episode_id': self.journal.episode_id, 'cursor': self.cursor,
                                             'active': self.active, 'modules': self.modules, 'recent': self.recent,
                                             'gaps': self.gaps[-64:], 'subgoals': self.subgoals,
                                             'effects': self.effects, 'unresolved': self.unresolved,
                                             'effect_order': self.effect_order,
                                             'selected_needs': self.selected_needs, 'page_id': self.page_id,
                                             **({'uncertainty_reviews': self.uncertainty_reviews}
                                                if getattr(self, 'uncertainty_reviews', {}) else {}),
                                             **({'application_failure_memory': self.application_failure_memory}
                                                if getattr(self, 'application_failure_memory', {}).get('module_id')
                                                is not None else {})})

    def event(self, identity):
        """Read one immutable event, without exporting the entire trajectory."""
        if not identity or self.journal.closed:
            return None
        row = self.journal.db.execute('SELECT payload FROM events WHERE id=?', (identity,)).fetchone()
        return json.loads(row[0]) if row else None

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
                     'gaps': row['gaps'], 'module_id': self.active,
                     'tool_call_id': (row.get('tool') or {}).get('id'),
                     'action_fingerprint': digest((row.get('tool') or {}).get('arguments') or row['action'])}
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

    def select(self, stage, needs, *, frame, ref, subgoal_id=None):
        """Open task-specific subgoal/object modules from bounded controller proposals."""
        if subgoal_id is not None and subgoal_id not in self.subgoals:
            raise ValueError('Unknown stable subgoal ID')
        # Explicit task-derived identities survive changes of role/anchor/stage.
        module_id = ('module:' + digest(['subgoal', subgoal_id]) if subgoal_id is not None else
                     'module:' + digest([stage, sorted({a for n in needs for a in n['anchors']})]))
        previous = self.modules.get(module_id)
        value = {'id': module_id, 'stage': stage, 'goals': [n['purpose'] for n in needs],
                 'anchors': sorted({a for n in needs for a in n['anchors']}),
                 'state': 'active', 'frame_id': frame,
                 'dependencies': [a for n in needs for a in n['anchors'] if a in self.modules],
                 'inputs': sorted({a for n in needs for a in n['anchors']}), 'outputs': [], 'needed_evidence': [],
                 'reports': {}, 'interpretation': 'model_subgoal_not_completion_verdict'}
        if subgoal_id is not None:
            goal = self.subgoals[subgoal_id]
            value.update(subgoal_id=subgoal_id, goals=[goal['label']],
                         dependencies=['module:' + digest(['subgoal', dep]) for dep in goal['dependencies']])
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
        self.selected_needs = plain(needs)
        self.save()
        return module_id

    def validate_subgoals(self, proposed):
        """Freeze a small dependency plan from the user's goal, never an answer key."""
        if not isinstance(proposed, list) or not 1 <= len(proposed) <= 8:
            raise ValueError('Use 1..8 stable subgoals')
        ids = set()
        for goal in proposed:
            if (not isinstance(goal, dict) or set(goal) != {'id', 'label', 'dependencies'}
                    or any(not isinstance(goal[k], str) or not goal[k].strip() or len(goal[k]) > cap
                           for k, cap in (('id', 64), ('label', 256)))
                    or not isinstance(goal['dependencies'], list)
                    or any(not isinstance(dep, str) for dep in goal['dependencies'])
                    or len(goal['dependencies']) != len(set(goal['dependencies'])) or goal['id'] in ids):
                raise ValueError('Subgoals require unique immutable IDs and earlier dependencies')
            ids.add(goal['id'])
        by_id = {g['id']: g for g in proposed}
        def visit(identity, path):
            if identity not in ids or identity in path:
                raise ValueError('Subgoal dependency is unknown or cyclic')
            for dep in by_id[identity]['dependencies']:
                visit(dep, path | {identity})
        for identity in ids:
            visit(identity, set())
        if self.subgoals and {g['id']: g for g in proposed} != self.subgoals:
            raise ValueError('Task subgoal identities/dependencies are immutable')

    def register_subgoals(self, proposed):
        self.validate_subgoals(proposed)
        self.subgoals = {g['id']: plain(g) for g in proposed}
        self.save()

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

    def transition_packet(self, record):
        """Bounded action semantics and exact references to the full receipts/images."""
        source, target = self.event(record['source']), self.event(record['target'])
        value = plain(record)
        for name, row in (('before_image', source), ('after_image', target)):
            value[name] = row['images']['model'] if row else None
        transition = self.event(record['transition_id'])
        tool = transition.get('tool') if transition else None
        if tool:
            arguments = plain(tool.get('arguments'))
            value['executed_tool_input'] = {'tool_call_id': tool.get('id'),
                'source_frame': source['frame'] if source else None,
                'parameters': arguments if len(dumps(arguments).encode()) <= 512 else
                    {'complete_parameters_ref': record['raw_ref']},
                'interpretation': 'actual_original_dispatch_input; re-ground pointers in the current frame'}
        value['controller_receipt_ref'] = record['raw_ref']
        if len(dumps(value['action_semantics']).encode()) > 512:
            value['action_semantics'] = {'action': value['action_semantics'].get('action', 'unknown'),
                                         'details_ref': record['raw_ref']}
        value['action_check'] = plain(self.effects.get(record['transition_id']))
        return value

    def last_effect_record(self):
        """Delay/capture retain their edges without replacing the UI mutation."""
        if not self.recent:
            return None
        if not getattr(self, 'compare_state_v10', False):
            return self.recent[-1]
        return next((record for record in reversed(self.recent)
                     if record.get('action_semantics', {}).get('action') not in {'screenshot', 'wait'}), None)

    def last_action(self):
        record = self.last_effect_record()
        if record is None:
            return None
        result = self.transition_packet(record)
        action = result['action_semantics']
        keys = action.get('keys', action.get('key', ''))
        single_key = keys[0] if isinstance(keys, list) and len(keys) == 1 else keys
        submitted = isinstance(single_key, str) and single_key.casefold() in {'return', 'enter'}
        expected = {'kind': 'state', 'description': 'Check the visible effect of this exact action'}
        if action.get('action') in {'left_click', 'double_click', 'right_click'}:
            expected = {'kind': 'focus', 'description': 'Confirm the intended control/focus; a click receipt is insufficient'}
        elif action.get('action') == 'type':
            expected = {'kind': 'text', 'description': 'Confirm the exact text in the intended control',
                        'text': action.get('text'), 'text_ref': result['raw_ref']}
        elif action.get('action') == 'key' and submitted:
            typed = next((r for r in reversed(self.recent[:-1]) if r['action_semantics'].get('action') == 'type'
                          and r['module_id'] == result['module_id']), None)
            expected = {'kind': 'submission', 'description': 'Confirm submission and the requested object/result appears',
                        'input_transition_ref': typed['raw_ref'] if typed else None}
            literal = typed['action_semantics'].get('text', '') if typed else ''
            assignment = re.match(r'\s*([A-Za-z][A-Za-z0-9_]*)\s*=', literal)
            if assignment:
                expected['requested_object_label'] = assignment.group(1)
        result['expected_change'] = expected
        if getattr(self, 'compare_state_v10', False):
            captures = [self.transition_packet(r) for r in self.recent
                        if r['transition_id'] != record['transition_id']
                        and r.get('action_semantics', {}).get('action') in {'screenshot', 'wait'}
                        and self.recent.index(r) > self.recent.index(record)]
            result['evidence_capture_refs'] = [{'transition_id': r['transition_id'],
                'observation_kind': r['action_semantics']['action'],
                'raw_ref': r['raw_ref'], 'target_observation_id': r['target'],
                'after_image': r['after_image']} for r in captures[-3:]]
            result['omitted_older_capture_refs'] = max(0, len(captures) - 3)
            row = self.journal.db.execute("SELECT payload FROM events WHERE "
                "json_extract(payload,'$.kind')='observation_annotation' AND "
                "json_extract(payload,'$.observation_id')=? ORDER BY seq DESC LIMIT 1",
                (result['source'],)).fetchone()
            state = json.loads(row[0]) if row else None
            result['before_state'] = {'observation_id': state['observation_id'],
                'fields': state['state_schema'], 'evidence_ref': state['evidence_ref'],
                'grade': 'model_proposal'} if state else None
        return result

    def state_comparison(self, current_state):
        """Omitted verification fields cannot establish a before/after change.

        Keep exact values and literal comparison. The opt-in reader only knows
        its admitted source fields; other fields remain uncomparable, never
        silently unchanged or normalized to a synonym.
        """
        before = (self.last_action() or {}).get('before_state')
        omitted = []
        bounded = getattr(self, 'provided_state_comparison_v12', False)
        if bounded:
            verification = self.verification_action()
            before = (verification or {}).get('before_state')
            omitted = (verification or {}).get('omitted_before_state_keys', [])
        old = before['fields'] if before else {}
        new = current_state.get('fields', {}) if isinstance(current_state, dict) else {}
        shared = sorted(set(old) & set(new))
        changed = [key for key in shared if old[key] is not None and new[key] is not None
                   and key.casefold() not in {'clock', 'time', 'timestamp'} and dumps(old[key]) != dumps(new[key])]
        return {'source_observation_id': before['observation_id'] if before else None,
                'source_evidence_ref': before['evidence_ref'] if before else None,
                'shared_field_keys': shared, 'changed_field_keys': changed, 'grade': 'model_proposal',
                **({'source_scope': 'provided_verification_before_state',
                    'omitted_source_field_keys': list(omitted)} if bounded else {})}

    def verification_intent(self, last):
        """Read original actor prose, not a planner's replacement of its intent."""
        if not getattr(self, 'intent_verification_v12', False):
            return None
        edge = self.event(last['transition_id'])
        decision = self.event(edge.get('decision_id')) if edge else None
        if not decision:
            return None
        text, field = decision.get('local_instruction'), 'local_instruction'
        if not isinstance(text, str) or not text.strip():
            text, field = decision.get('response'), 'response'
            if isinstance(text, str):
                try:
                    message = json.loads(text)
                except ValueError:
                    message = None
                # Native completions without prose use serialized tool messages.
                # Those arguments are dispatch input, not an invented intention.
                if isinstance(message, dict):
                    text, field = message.get('content'), 'response.content'
        if not isinstance(text, str) or not text.strip():
            return None
        encoded = text.encode()
        return {'text': text if len(encoded) <= 1200 else None,
                'text_omitted': len(encoded) > 1200, 'original_text_bytes': len(encoded),
                'original_text_sha256': hashlib.sha256(encoded).hexdigest(),
                'original_field': field, 'decision_ref': edge['decision_ref'],
                'scope': 'whole_decision_model_proposal_not_verified_effect',
                'command_index': edge['command_index'], 'command_count': len(decision['commands'])}

    def verification_action(self, max_bytes=4000):
        """Bound adviser evidence without altering the original action/state."""
        last = self.last_action()
        if last is None:
            return None
        value = {key: plain(last[key]) for key in
                 ('transition_id', 'source', 'target', 'module_id', 'raw_ref',
                  'before_image', 'after_image', 'expected_change')}
        original = last.get('executed_tool_input') or {}
        value['executed_tool_input'] = {'tool_call_id': original.get('tool_call_id'),
            'parameters': original.get('parameters'), 'source_frame_evidence_ref': last['before_image']}
        value['before_state'] = plain(last.get('before_state'))
        value['omitted_before_state_keys'] = []
        value['previous_assessment'] = (last.get('action_check') or {}).get('assessment', 'unknown')
        value['complete_model_feedback_ref'] = str(self.path) + '#effects/' + last['transition_id']
        intent = self.verification_intent(last)
        if intent is not None:
            value['actor_intent'] = intent
        if last.get('evidence_capture_refs'):
            value['latest_evidence_capture'] = plain(last['evidence_capture_refs'][-1])
        # Opt-in local verification can share the exact same source image already
        # present in this packet. Keep the original intent and known state before
        # dropping values; the immutable native parameters/history remain intact.
        tool = value['executed_tool_input']
        if (getattr(self, 'intent_verification_v12', False)
                and len(dumps(value).encode()) > max_bytes
                and tool['source_frame_evidence_ref'] == value['before_image']):
            tool['source_frame_evidence_ref'] = {'record_ref': '#/before_image'}
        # Keep whole known field values. Omitted fields remain at the exact
        # source observation; absence cannot be turned into a changed value.
        state = value.get('before_state')
        while len(dumps(value).encode()) > max_bytes and state and state['fields']:
            fields = state['fields']
            keys = sorted(fields, key=lambda key: (
                any(word in key.casefold() for word in ('focus', 'input', 'file', 'location', 'selection')),
                -len(dumps(fields[key]).encode()), key))
            key = keys[0]
            fields.pop(key)
            value['omitted_before_state_keys'].append(key)
        if len(dumps(value).encode()) > max_bytes:
            raise ValueError('Cannot bound exact current-action verification references')
        return value

    def verification_binding(self, frame):
        """Exact operation identity; later capture remains separate evidence."""
        last = self.last_action()
        return ({'transition_id': last['transition_id'],
                 'target_observation_id': last['target'], 'frame_id': frame}
                if last is not None else None)

    def validate_action_check(self, check, *, frame, visible_texts, current_state=None):
        last = self.last_action()
        if last is None:
            if check is not None:
                raise ValueError('No executed action to verify')
            return
        fields = {'transition_id', 'target_observation_id', 'frame_id', 'assessment', 'checks'}
        if (not isinstance(check, dict) or set(check) != fields
                or check['transition_id'] != last['transition_id']
                or check['target_observation_id'] != last['target'] or check['frame_id'] != frame
                or check['assessment'] not in {'observed', 'not_observed', 'unknown'}
                or not isinstance(check['checks'], list) or not 1 <= len(check['checks']) <= 4
                or len(dumps(check).encode()) > 1800):
            raise ValueError('Action verification must bind the last transition/post observation/current frame. '
                'Copy action_check_binding exactly: ' + dumps(self.verification_binding(frame))
                + '. A later screenshot target is evidence only; do not replace the operation target.')
        intent = self.verification_intent(last)
        for item in check['checks']:
            intent_check = isinstance(item, dict) and item.get('kind') == 'intent'
            fields = {'kind', 'assessment', 'quotes'} | ({'state_keys'} if intent_check else set())
            if (not isinstance(item, dict) or set(item) != fields
                    or item['kind'] not in {'focus', 'text', 'submission', 'object', 'state', 'intent'}
                    or item['assessment'] not in {'observed', 'not_observed', 'unknown'}
                    or not isinstance(item['quotes'], list) or len(item['quotes']) > 4
                    or any(not isinstance(q, str) or not q or len(q) > 256 for q in item['quotes'])
                    or item['assessment'] != 'unknown' and not item['quotes']):
                bounded_quotes = (isinstance(item, dict) and isinstance(item.get('quotes'), list)
                    and len(item['quotes']) <= 4
                    and all(isinstance(q, str) and q and len(q) <= 256 for q in item['quotes']))
                provided = (item if bounded_quotes else {
                    'whole_malformed_check_omitted': True,
                    'original_check_sha256': hashlib.sha256(dumps(item).encode()).hexdigest(),
                    'original_check_bytes': len(dumps(item).encode())})
                detail = {'check_index': check['checks'].index(item), 'provided_check': provided,
                          'required_fields': sorted(fields),
                          'extra_fields': sorted(set(item) - fields) if isinstance(item, dict) else [],
                          'repair': 'Regenerate a separate check for each kind. An object check uses kind:object; '
                                    'object/result are not fields of a submission check. Non-unknown marks need '
                                    'literal quotes from this current summary/elements; otherwise keep unknown. '
                                    'Only intent has state_keys. Do not auto-filter fields or invent an outcome.'}
                raise ValueError('Action checks require bounded visible quotes, not a global goal verdict: ' + dumps(detail))
            if intent_check:
                keys = item['state_keys']
                if (not intent or not isinstance(keys, list) or len(keys) > 4
                        or any(not isinstance(key, str) or not key or len(key) > 64 for key in keys)
                        or len(keys) != len(set(keys))):
                    raise ValueError('Intent check requires supplied actor intent and <=4 unique state_keys')
                if item['assessment'] == 'observed':
                    comparison = self.state_comparison(current_state)
                    if intent['text_omitted'] or not keys or not set(keys) <= set(comparison['changed_field_keys']):
                        supplied = (self.verification_action()
                            if getattr(self, 'provided_state_comparison_v12', False) else last)
                        before = (supplied.get('before_state') or {}).get('fields', {})
                        current = (current_state or {}).get('fields', {})
                        detail = {'provided_state_keys': keys, 'changed_field_keys': comparison['changed_field_keys'],
                                  'unknown_or_missing_state_keys': [key for key in keys
                                      if before.get(key) is None or current.get(key) is None],
                                  'actor_prose_omitted': intent['text_omitted'],
                                  'repair': 'null is unknown, not visible absence. If the current image establishes '
                                            'that a control/result is absent, report {status:absent} for that same '
                                            'field and describe the absence in the current summary. Do not copy '
                                            'actor prose as a visible quote. If evidence is insufficient, keep '
                                            'intent unknown/not_observed and reduce the aggregate accordingly.'}
                        raise ValueError('Observed intent requires its exact admitted actor prose and changed '
                            'before/current ui_state keys for that intended effect; an unrelated menu/focus '
                            'change is insufficient. Use unknown/not_observed when it is not established: ' + dumps(detail))
            missing = [quote for quote in item['quotes'] if not any(quote in text for text in visible_texts)]
            if missing:
                # Preserve the candidate and strict guard. A generic rejection
                # did not tell the model which quote was absent during repair.
                detail = {'check_index': check['checks'].index(item), 'kind': item['kind'],
                          'missing_visible_quotes': missing,
                          'repair': 'Every quote must occur literally in this candidate summary/elements. '
                                    'Re-read the current image: report actual visible text with its element, '
                                    'or use an existing literal source. Do not invent a label or auto-drop evidence; '
                                    'use unknown when the action effect cannot be established.'}
                raise ValueError('Action checks require bounded visible quotes, not a global goal verdict: ' + dumps(detail))
        assessments = {c['assessment'] for c in check['checks']}
        kinds = {c['kind'] for c in check['checks']}
        if intent and sum(c['kind'] == 'intent' for c in check['checks']) != 1:
            raise ValueError('Verify the original actor intent separately with one intent check and state_keys; '
                             'generic focus/state success does not prove the intended effect')
        if last['expected_change']['kind'] not in kinds:
            raise ValueError('Check the expected change of this specific action')
        if last['expected_change']['kind'] == 'text' and 'focus' not in kinds:
            raise ValueError('Verify focus as well as the typed text')
        if last['expected_change']['kind'] == 'submission' and 'object' not in kinds:
            raise ValueError('Verify the submitted object/result as well as Return with a separate kind:object '
                             'check. Its fields are exactly kind, assessment, quotes; do not add object/result '
                             'fields to the kind:submission check. Keep the object unknown if current evidence '
                             'cannot establish creation; no automatic promotion to observed.')
        literal = last['expected_change'].get('text')
        label = last['expected_change'].get('requested_object_label')
        for item in check['checks']:
            if item['assessment'] != 'observed':
                continue
            required = literal if item['kind'] == 'text' else label if item['kind'] == 'object' else None
            if required and not any(required in quote for quote in item['quotes']):
                raise ValueError('Observed input/object must quote the exact previous request, not another object')
        expected = 'not_observed' if 'not_observed' in assessments else 'unknown' if 'unknown' in assessments else 'observed'
        if check['assessment'] != expected:
            detail = {'provided_assessment': check['assessment'], 'required_assessment': expected,
                      'individual_checks': [{'kind': item['kind'], 'assessment': item['assessment']}
                                            for item in check['checks']],
                      'rule': 'Any not_observed => not_observed; otherwise any unknown => unknown; '
                              'otherwise observed. Aggregate only this operation, not the whole task.',
                      'repair': 'Regenerate the complete evidence response. Keep unestablished intent unknown; '
                                'do not invent a state change or silently promote any check to observed.'}
            raise ValueError('Action assessment must agree with its individual checks: ' + dumps(detail))
        if (getattr(self, 'compare_state_v10', False) and check['assessment'] == 'observed'
                and last['expected_change']['kind'] in {'focus', 'state', 'submission'}):
            comparison = self.state_comparison(current_state)
            if not comparison['changed_field_keys']:
                detail = {**comparison, 'reason': 'Pre-existing focus/labels do not prove this action caused a change',
                          'repair': 'Compare the supplied before_state to actual current ui_state using the same field keys. '
                                    'Use unknown when change is not established, or not_observed for an evidenced failed effect. '
                                    'Do not invent a changed state, rename keys, or count a clock/receipt as progress.'}
                raise ValueError('Observed action lacks before/after state evidence: ' + dumps(detail))

    def record_action_check(self, check, *, frame, current_state=None):
        if check is None:
            return
        last = self.last_effect_record()
        if last is None or check['transition_id'] != last['transition_id']:
            raise ValueError('Action effect must bind to the selected executed action')
        value = {**plain(check), 'grade': 'model_proposal', 'raw_transition_ref': last['raw_ref'],
                 'module_id': last['module_id'], 'action_fingerprint': last.get('action_fingerprint')}
        if getattr(self, 'compare_state_v10', False):
            value['state_comparison'] = self.state_comparison(current_state)
        self.effects[last['transition_id']] = value
        order = getattr(self, 'effect_order', list(self.effects))
        self.effect_order = ([identity for identity in order if identity != last['transition_id']]
                             + [last['transition_id']])[-64:]
        self.effects = {identity: self.effects[identity] for identity in self.effect_order}
        self.unresolved = [r for r in self.unresolved if r['transition_id'] != last['transition_id']]
        if check['assessment'] == 'not_observed' or last['error']:
            self.unresolved = (self.unresolved + [self.transition_packet(last)])[-8:]
        self.report('last_action', value, frame=frame)
        self._retain_application_failure(value)
        self.save()

    def original_parameters(self, record):
        """Read pointer parameters from the immutable edge, not semantic hashes.

        Older module projections can have geometry-free action fingerprints.
        They remain historical records; never rewrite them to repair counting.
        """
        journal = getattr(self, 'journal', None)
        if journal is None or journal.closed:
            return None
        edge = self.event(record['transition_id'])
        return plain((edge.get('tool') or {}).get('arguments')) if edge else None

    def _action_fingerprint(self, record):
        parameters = self.original_parameters(record)
        return digest(parameters) if parameters is not None else record.get('action_fingerprint')

    def stalled_pointer_actions(self):
        actions = {'left_click', 'right_click', 'double_click'}
        if getattr(self, 'returned_page_pointer_review_v12', False):
            actions.add('triple_click')
        return self._with_returned_page_failures(actions)

    def stalled_keyboard_actions(self):
        return self._with_returned_page_failures({'key'})

    def _with_returned_page_failures(self, actions):
        existing = self._stalled_actions(actions)
        returned = self._returned_page_intent_failures(actions)
        return existing + [row for row in returned
                           if not any(row['parameters'] == old['parameters'] for old in existing)]

    def _observation_annotation(self, identity):
        row = self.journal.db.execute("SELECT payload FROM events WHERE "
            "json_extract(payload,'$.kind')='observation_annotation' AND "
            "json_extract(payload,'$.observation_id')=? ORDER BY seq DESC LIMIT 1", (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def _returned_page_intent_failures(self, actions):
        """An observed recovery does not validate a failed destination operation.

        Require two exact parameters, accepted failed intent, original single
        command prose, the same source page/frame geometry and known intent
        state values matching the current observation. This is bounded proposal
        evidence, not a locator or a certified unchanged application layout.
        Other pages, unknown states, changed geometry and a later successful
        intention do not inherit this warning. Legacy arms remain unchanged.
        """
        if not getattr(self, 'returned_page_intent_v12', False):
            return []
        journal = self.journal
        current = journal.current if not journal.closed else None
        annotation = self._observation_annotation(current['id']) if current else None
        if not annotation or not annotation.get('logical_page'):
            return []
        frame = self.event(current['id'])['frame']
        fields = annotation['state_schema']
        groups, cleared = {}, set()
        for record in reversed(self.recent[-8:]):
            if record.get('module_id') != self.active:
                continue
            parameters = self.original_parameters(record)
            if not isinstance(parameters, dict) or parameters.get('action') not in actions:
                continue
            edge = self.event(record['transition_id'])
            before = self._observation_annotation(edge['source']) if edge and edge.get('source') else None
            source = self.event(edge['source']) if before else None
            if (not before or before['logical_page'] != annotation['logical_page'] or not source
                    or any(source['frame'][key] != frame[key] for key in ('model_size', 'coordinate_type'))):
                continue
            effect = self.effects.get(record['transition_id'], {})
            intent = next((item for item in effect.get('checks', []) if item['kind'] == 'intent'), None)
            prose = self.verification_intent(record)
            if not intent or not prose or prose['text_omitted'] or prose['command_count'] != 1:
                continue
            identity = digest(parameters)
            if identity in cleared:
                continue
            if intent['assessment'] == 'observed':
                groups.pop(identity, None)
                cleared.add(identity)
                continue
            keys = [key for key in intent['state_keys'] if key.casefold() not in {'clock', 'time', 'timestamp'}
                    and before['state_schema'].get(key) is not None and fields.get(key) is not None]
            if (effect.get('assessment') != 'not_observed' or intent['assessment'] != 'not_observed'
                    or not intent['quotes'] or not keys
                    or any(dumps(before['state_schema'][key]) != dumps(fields[key]) for key in keys)):
                continue
            group = groups.setdefault(identity, {'parameters': parameters, 'transition_ids': [],
                'assessments': [], 'grade': 'model_proposal',
                'reason': 'failed_intent_after_return_to_source_page',
                'source_page': annotation['logical_page'], 'matched_intent_state_keys': keys})
            group['transition_ids'].append(record['transition_id'])
            group['assessments'].append(effect['assessment'])
            group['matched_intent_state_keys'] = sorted(set(group['matched_intent_state_keys']) & set(keys))
        return [row for row in groups.values()
                if len(row['transition_ids']) >= 2 and row['matched_intent_state_keys']]

    def _stalled_actions(self, actions):
        """Exact repeated operations with action-bound unchanged state proposals.

        Only the current subgoal and eight recent edges participate. A known
        state change clears earlier failures; unknown without comparable state
        is insufficient. This supplies a bounded validation warning, not an
        executable alternative, verified effect, or completion decision.
        """
        groups, cleared = {}, set()
        for record in reversed(self.recent):
            if record.get('module_id') != self.active:
                continue
            effect = self.effects.get(record['transition_id'], {})
            comparison = effect.get('state_comparison', {})
            if comparison.get('changed_field_keys'):
                break
            parameters = self.original_parameters(record)
            if not isinstance(parameters, dict) or parameters.get('action') not in actions:
                continue
            identity = digest(parameters)
            if identity in cleared:
                continue
            if effect.get('assessment') == 'observed':
                groups.pop(identity, None)
                cleared.add(identity)
                continue
            uncertain_unchanged = (effect.get('assessment') == 'unknown'
                and bool(comparison.get('shared_field_keys')))
            if effect.get('assessment') != 'not_observed' and not uncertain_unchanged:
                continue
            group = groups.setdefault(identity, {'parameters': parameters, 'transition_ids': [],
                'assessments': [], 'grade': 'model_proposal'})
            group['transition_ids'].append(record['transition_id'])
            group['assessments'].append(effect['assessment'])
        return [value for value in groups.values() if len(value['transition_ids']) >= 2]

    def prior_action_evidence(self, max_bytes=1600):
        """Carry literal earlier failure proposals to a stateless local planner.

        Closing a dialog does not erase the earlier application's response.
        Preserve whole quotes, immutable operation refs and original short prose;
        do not reinterpret a native Return as another command submission. These
        are historical, fallible model checks, not current-frame math or success.
        """
        candidates = []
        recent = {record['transition_id']: record for record in self.recent[-8:]}
        for identity, effect in self._prior_effect_items():
            record = recent.get(identity) or {'transition_id': identity,
                'module_id': effect.get('module_id'), 'raw_ref': effect.get('raw_transition_ref')}
            if record.get('module_id') != self.active:
                continue
            checks = [{k: plain(check[k]) for k in ('kind', 'assessment', 'quotes')}
                      for check in effect.get('checks', [])
                      if check.get('assessment') == 'not_observed' and check.get('quotes')]
            if not checks:
                continue
            if identity not in recent and not any(check['kind'] in {'submission', 'object'} for check in checks):
                continue
            intent = self.verification_intent(record)
            text = (intent or {}).get('text')
            row = {'transition_id': record['transition_id'], 'raw_transition_ref': record['raw_ref'],
                   'frame_id': effect['frame_id'], 'target_observation_id': effect['target_observation_id'],
                   'checks': checks, 'original_feedback_sha256': hashlib.sha256(dumps(effect).encode()).hexdigest(),
                   'original_intent': {'text': text if text and len(text.encode()) <= 400 else None,
                       'source_sha256': (intent or {}).get('original_text_sha256'),
                       'source_bytes': (intent or {}).get('original_text_bytes'),
                       'whole_text_omitted': not text or len(text.encode()) > 400}}
            # Prefer application responses over recovery attempts. The opt-in
            # durable protocol orders those responses by original sequence,
            # most recent first, without changing the retained first provenance.
            # Check kinds alone cannot distinguish Return submission from dialog
            # dismissal. No error phrase or application name is hardcoded.
            candidates.append(row)
        candidates.sort(key=lambda row: not any(check['kind'] in {'submission', 'object'} for check in row['checks']))
        result = {'records': [], 'omitted_records': len(candidates), 'grade': 'model_proposal',
                  'scope': 'historical_operation_checks_not_current_visible_evidence'}
        if len(dumps(result).encode()) > max_bytes:
            raise ValueError('Prior action evidence cannot hold its omission metadata')
        for row in candidates:
            proposed = {**result, 'records': result['records'] + [row],
                        'omitted_records': result['omitted_records'] - 1}
            if len(dumps(proposed).encode()) <= max_bytes:
                result = proposed
        return result

    def unconfirmed_state_review(self):
        """Request observation/planning across varying inputs, never infer failure.

        Field names shared by model state proposals can include unknown values.
        They establish a comparable schema, not known unchanged GUI state. Three
        unconfirmed operations in one active subgoal warrant a fresh strategy.
        A recorded review, established change or subgoal boundary starts a new
        window; captures/delays do not manufacture another failed operation.
        """
        if not getattr(self, 'subgoal_state_review_v12', False):
            return None
        reviewed = getattr(self, 'uncertainty_reviews', {}).get(self.active)
        identities, fields = [], None
        interactions = {'left_click', 'right_click', 'double_click', 'key', 'type', 'scroll', 'drag'}
        if getattr(self, 'returned_page_pointer_review_v12', False):
            interactions.add('triple_click')
        for record in reversed(self.recent[-8:]):
            if record.get('module_id') != self.active or record['transition_id'] == reviewed:
                break
            parameters = self.original_parameters(record)
            if not isinstance(parameters, dict):
                break
            if parameters.get('action') in {'wait', 'screenshot'}:
                continue
            if parameters.get('action') not in interactions:
                break
            effect = self.effects.get(record['transition_id'], {})
            comparison = effect.get('state_comparison', {})
            if comparison.get('changed_field_keys') or effect.get('assessment') not in {'unknown', 'not_observed'}:
                break
            shared = set(comparison.get('shared_field_keys', [])) - {'clock', 'time', 'timestamp'}
            if effect['assessment'] == 'unknown' and not shared:
                break
            if shared:
                common = shared if fields is None else fields & shared
                if not common:
                    break
                fields = common
            identities.append(record['transition_id'])
        if len(identities) < 3:
            return self._returned_page_pointer_review(reviewed)
        return {'module_id': self.active, 'transition_ids': identities,
                'unconfirmed_operation_count': len(identities),
                'comparison_field_keys': sorted(fields or []), 'grade': 'model_proposal'}

    def _returned_page_pointer_review(self, reviewed):
        """Review a location reused across click types and window recoveries.

        This never merges original operations for dispatch or marks unknown
        focus as failure. Exact source page/geometry and at least two matching
        known field proposals bind the historical attempts to the current page.
        Three unconfirmed focus attempts warrant planning, not a new locator.
        """
        if not getattr(self, 'returned_page_pointer_review_v12', False):
            return None
        current = self.journal.current if not self.journal.closed else None
        annotation = self._observation_annotation(current['id']) if current else None
        if not annotation or not annotation.get('logical_page'):
            return None
        frame, fields = self.event(current['id'])['frame'], annotation['state_schema']
        groups, cleared = {}, set()
        for record in reversed(self.recent[-8:]):
            if record.get('module_id') != self.active or record['transition_id'] == reviewed:
                break
            parameters = self.original_parameters(record)
            if not isinstance(parameters, dict) or parameters.get('action') not in {
                    'left_click', 'double_click', 'triple_click'}:
                continue
            coordinate = parameters.get('coordinate')
            if not isinstance(coordinate, list) or len(coordinate) != 2:
                continue
            edge = self.event(record['transition_id'])
            before = self._observation_annotation(edge['source']) if edge and edge.get('source') else None
            source = self.event(edge['source']) if before else None
            if (not before or before['logical_page'] != annotation['logical_page'] or not source
                    or any(source['frame'][key] != frame[key] for key in ('model_size', 'coordinate_type'))):
                continue
            identity = dumps({key: value for key, value in parameters.items() if key != 'action'})
            if identity in cleared:
                continue
            effect = self.effects.get(record['transition_id'], {})
            focus = next((item for item in effect.get('checks', []) if item['kind'] == 'focus'), None)
            if focus and focus['assessment'] == 'observed':
                groups.pop(identity, None)
                cleared.add(identity)
                continue
            prose = self.verification_intent(record)
            known = {key for key in before['state_schema'].keys() & fields.keys()
                     if key.casefold() not in {'clock', 'time', 'timestamp'}
                     and before['state_schema'][key] is not None and fields[key] is not None}
            if (not focus or focus['assessment'] not in {'unknown', 'not_observed'}
                    or not focus['quotes'] or effect.get('assessment') not in {'unknown', 'not_observed'}
                    or effect.get('state_comparison', {}).get('changed_field_keys')
                    or not prose or prose['text_omitted'] or prose['command_count'] != 1
                    or len(known) < 2
                    or any(dumps(before['state_schema'][key]) != dumps(fields[key]) for key in known)):
                continue
            group = groups.setdefault(identity, {'transition_ids': [], 'fields': known})
            group['transition_ids'].append(record['transition_id'])
            group['fields'] &= known
        candidate = next((row for row in groups.values()
                          if len(row['transition_ids']) >= 3 and len(row['fields']) >= 2), None)
        if candidate is None:
            return None
        return {'module_id': self.active, 'transition_ids': candidate['transition_ids'],
                'unconfirmed_operation_count': len(candidate['transition_ids']),
                'comparison_field_keys': sorted(candidate['fields']), 'grade': 'model_proposal',
                'reason': 'same_source_point_unconfirmed_focus'}

    def actor_prior_action_evidence(self, max_bytes=900):
        """Keep accepted application rejection proposals in the local loop.

        This compact actor projection is independent of planner scheduling.
        Whole earlier submission/object checks retain their exact provenance;
        they do not become current-frame state or an executable prohibition.
        """
        candidates = []
        recent = {record['transition_id']: record for record in self.recent[-8:]}
        for identity, effect in self._prior_effect_items():
            record = recent.get(identity) or {'module_id': effect.get('module_id'),
                                            'raw_ref': effect.get('raw_transition_ref')}
            if record.get('module_id') != self.active or effect.get('assessment') != 'not_observed':
                continue
            checks = [{key: plain(item[key]) for key in ('kind', 'assessment', 'quotes')}
                      for item in effect.get('checks', []) if item.get('kind') in {'submission', 'object'}
                      and item.get('assessment') == 'not_observed' and item.get('quotes')]
            if checks:
                candidates.append({'transition_id': identity, 'frame_id': effect['frame_id'],
                    'target_observation_id': effect['target_observation_id'],
                    'raw_transition_ref': record['raw_ref'], 'checks': checks,
                    'original_feedback_sha256': hashlib.sha256(dumps(effect).encode()).hexdigest()})
        result = {'records': [], 'omitted_records': len(candidates), 'grade': 'model_proposal',
                  'scope': 'past_application_feedback_not_current_state_or_math'}
        if len(dumps(result).encode()) > max_bytes:
            raise ValueError('Actor prior evidence cannot hold its omission metadata')
        for row in candidates:
            candidate = {**result, 'records': result['records'] + [row],
                         'omitted_records': result['omitted_records'] - 1}
            if len(dumps(candidate).encode()) <= max_bytes:
                result = candidate
        return result

    def record_uncertainty_review(self, review):
        """Persist only a completed planner review, not success or an action."""
        if review:
            self.uncertainty_reviews = getattr(self, 'uncertainty_reviews', {})
            self.uncertainty_reviews[review['module_id']] = review['transition_ids'][0]
            self.uncertainty_reviews = dict(list(self.uncertainty_reviews.items())[-8:])
            self.save()

    def feedback(self):
        last = self.last_action()
        if not last:
            return {'last_action': None, 'repetition_count': 0, 'strategy_review': False}
        count = 0
        for record in reversed(self.recent):
            if (record.get('module_id') != last['module_id']
                    or self._action_fingerprint(record) != self._action_fingerprint(last)):
                continue
            effect = self.effects.get(record['transition_id'], {})
            legacy_click = (getattr(self, 'compare_state_v10', False)
                and record.get('action_semantics', {}).get('action') in {'left_click', 'right_click', 'double_click', 'key'}
                and not effect.get('state_comparison', {}).get('changed_field_keys'))
            if effect.get('assessment') == 'observed' and not legacy_click:
                break
            count += 1
        result = {'last_action': last, 'repetition_count': count, 'strategy_review': count >= 2,
                'guidance': 'Re-observe the intended control and focus; change the strategy after repeated unconfirmed effects. '
                            'Confirm text before submission and the requested object/result after submission. '
                            'Do not infer progress from receipts or whole-image hashes.'}
        review = self.unconfirmed_state_review()
        if review:
            result['state_review'] = review
            result['strategy_review'] = True
        return result

    def actor_feedback(self):
        """A small protected warning, separate from optional module/view detail."""
        feedback = self.feedback()
        last = feedback['last_action']
        if last is None:
            return None
        original = last.get('executed_tool_input') or {}
        check = last.get('action_check') or {}
        # Full immutable checks, images and receipts remain at the raw edge.
        # Keep complete short quotes; never truncate one into a new assertion.
        checks = []
        for item in check.get('checks', []):
            checks.append({'kind': item['kind'], 'assessment': item['assessment'],
                           'quotes': item['quotes'][:1],
                           **({'state_keys': item['state_keys']} if item['kind'] == 'intent' else {})})
        value = {'transition_id': last['transition_id'], 'target_observation_id': last['target'],
                 'raw_transition_ref': last['raw_ref'], 'tool_call_id': original.get('tool_call_id'),
                 'original_parameters': original.get('parameters'),
                 'expected_change': last['expected_change']['kind'],
                 'assessment': check.get('assessment', 'unknown'), 'checks': checks,
                 'unconfirmed_repetition_count': feedback['repetition_count'],
                 'strategy_review': feedback['strategy_review'], 'grade': 'model_proposal',
                 'decision_guidance': ('Repeated identical parameters have not established the intended effect. '
                     'Choose a newly grounded strategy/control from the current image before another attempt; '
                     'do not reuse these pointer parameters as a locator or proof of focus.'
                     if feedback['strategy_review'] else
                     'Confirm this specific effect in the current image; a returned command does not prove focus.')}
        if last.get('evidence_capture_refs'):
            value['latest_evidence_capture_ref'] = last['evidence_capture_refs'][-1]['raw_ref']
        if feedback.get('state_review'):
            value['unconfirmed_state_operation_count'] = feedback['state_review']['unconfirmed_operation_count']
            value['decision_guidance'] = (
                'Several operations in this subgoal have not established a state change, even with different parameters. '
                'Unknown remains uncertainty, not a proved failure. Re-observe focus/input/current control and use the '
                'fresh strategy; do not keep offsetting an old pointer guess or infer progress from receipts.')
        # No fabricated success or executable gate: a large check stays at its
        # immutable reference, while its exact assessment/count remain present.
        while len(dumps(value).encode()) > 1800 and value['checks']:
            value['checks'].pop()
        if len(dumps(value).encode()) > 1800:
            value['original_parameters'] = {'complete_parameters_ref': last['raw_ref']}
        if len(dumps(value).encode()) > 1800:
            raise ValueError('Cannot bound protected current-action warning')
        return value

    @staticmethod
    def _share_packet_reference(packet):
        """Intern one identical receipt/image value, retaining separate edges.

        References point only to earlier concrete values in this projection;
        neither different transition IDs nor different image values are merged.
        Persistent records and executable parameters are never changed.
        """
        images = []
        for collection in ('recent_transitions', 'unresolved_failures'):
            for index, record in enumerate(packet[collection]):
                prefix = '#/' + collection + '/' + str(index) + '/'
                receipt = record.get('controller_receipt_ref')
                if isinstance(receipt, str) and receipt == record.get('raw_ref'):
                    reference = {'value_ref': prefix + 'raw_ref'}
                    if len(dumps(reference).encode()) < len(dumps(receipt).encode()):
                        record['controller_receipt_ref'] = reference
                        return True
                for key in ('before_image', 'after_image'):
                    image = record.get(key)
                    if not isinstance(image, dict) or set(image) == {'value_ref'}:
                        continue
                    if not isinstance(image.get('ref'), str) or not isinstance(image.get('sha256'), str):
                        continue
                    for path, previous in images:
                        reference = {'value_ref': path}
                        if image == previous and len(dumps(reference).encode()) < len(dumps(image).encode()):
                            record[key] = reference
                            return True
                    images.append((prefix + key, image))
        return False

    def packet(self, max_bytes=6000, *, include_modules=True, share_duplicate_refs=False,
               share_exact_refs=False):
        modules = plain(list(self.modules.values())[-8:])
        if self.active and not any(m['id'] == self.active for m in modules):
            modules = (modules + [plain(self.modules[self.active])])[-8:]
        revision = self.memory.snapshot.revision
        recent = [self.transition_packet(r) for r in self.recent]
        last = self.last_action()
        if last is not None:
            selected = next(i for i, record in enumerate(recent)
                            if record['transition_id'] == last['transition_id'])
            recent[selected] = last
        protected_ids = {record['transition_id'] for record in recent[-1:]}
        if last is not None:
            protected_ids.add(last['transition_id'])
        packet = {'revision': revision, 'base_revision': self.previous_revision,
                  'active_module': self.active, 'modules': modules, 'omitted_modules': max(0, len(self.modules) - len(modules)),
                  'recent_transitions': recent, 'changed_execution_ids': self.new_events[-32:],
                  'omitted_change_ids': max(0, len(self.new_events) - 32), 'gaps': self.gaps[-8:],
                  'interpretation': 'recorded_execution_and_model_modules_not_verified_effects'}
        packet['unresolved_failures'] = plain(self.unresolved[-2:])
        # Action/post-frame/receipt references precede old modules and verbose
        # advice. Never delete the newest transition to keep a planner essay.
        omissions = packet['projection_omissions'] = {}
        if not include_modules:
            # Classification remains in persistent TaskViews memory. The local
            # actor needs operation evidence, not accumulated graph/planner
            # descriptions that can compete with its current screenshot.
            packet['omitted_modules'] = len(self.modules)
            packet['modules'] = modules = []
            omissions['module_detail_at_source'] = len(self.modules)
        def omitted(key):
            omissions[key] = omissions.get(key, 0) + 1
        while len(dumps(packet).encode()) > max_bytes:
            if len(modules) > 1:
                modules.pop(next(i for i, m in enumerate(modules) if m['id'] != self.active))
                packet['omitted_modules'] += 1
            elif modules:
                module = modules[0]
                key = next((k for k in ('reports', 'outputs', 'needed_evidence', 'goals', 'inputs', 'anchors')
                            if module.get(k)), None)
                if key is None:
                    packet['modules'] = modules = []
                    omitted('active_module_detail')
                else:
                    module[key] = {} if key == 'reports' else []
                    omitted('active_module.' + key)
            elif any(r['transition_id'] not in protected_ids for r in packet['recent_transitions']):
                index = next(i for i, r in enumerate(packet['recent_transitions'])
                             if r['transition_id'] not in protected_ids)
                packet['recent_transitions'].pop(index)
                omitted('older_transition')
            elif packet['changed_execution_ids']:
                packet['changed_execution_ids'].pop(0)
                packet['omitted_change_ids'] += 1
            elif packet['gaps']:
                packet['gaps'].pop(0)
                omitted('older_gap')
            elif len(packet['unresolved_failures']) > 1:
                packet['unresolved_failures'].pop(0)
                omitted('older_unresolved_failure')
            else:
                # Whole detailed values stay at immutable raw_ref. Reserve the
                # identity and image/receipt references even in a small packet.
                records = packet['recent_transitions'] + packet['unresolved_failures']
                detailed = next((r for r in records if 'action_semantics' in r), None)
                if detailed is None:
                    metadata = next((r for r in records if
                        any('bytes' in (r.get(k) or {}) for k in ('before_image', 'after_image'))
                        or 'description' in r.get('expected_change', {})
                        or r.get('evidence_capture_refs') == [] and r.get('omitted_older_capture_refs') == 0), None)
                    if metadata is None:
                        derived = next((r for r in records if 'action_fingerprint' in r
                                        or 'error' in r and r['error'] is None), None)
                        if derived is None:
                            # A failed latest operation also belongs to unresolved.
                            # Share only fields that match its exact recent record;
                            # retain each differing/absent field without inference.
                            shared = False
                            if share_duplicate_refs:
                                identity_fields = ('transition_id', 'source', 'target', 'raw_ref',
                                    'controller_receipt_ref', 'receipt_count', 'before_image', 'after_image',
                                    'effect_status')
                                for index, unresolved in enumerate(packet['unresolved_failures']):
                                    if 'shared_fields' in unresolved:
                                        continue
                                    for recent_index, recent_record in enumerate(packet['recent_transitions']):
                                        if not all(key in unresolved and key in recent_record
                                                   and unresolved[key] == recent_record[key]
                                                   for key in identity_fields):
                                            continue
                                        keys = sorted(key for key in unresolved
                                            if key not in {'transition_id', 'raw_ref'} and key in recent_record
                                            and unresolved[key] == recent_record[key])
                                        packet['unresolved_failures'][index] = {
                                            **{key: value for key, value in unresolved.items() if key not in keys},
                                            'record_ref': '#/recent_transitions/' + str(recent_index),
                                            'shared_fields': keys}
                                        omitted('shared_duplicate_reference_fields')
                                        shared = True
                                        break
                                    if shared:
                                        break
                            if shared:
                                continue
                            if share_exact_refs and self._share_packet_reference(packet):
                                omitted('shared_exact_reference_values')
                                continue
                            raise ExecutionPacketBudgetError(packet)
                        # Repetition is already in protected actor_feedback.
                        # Its derived fingerprint and an absent error need no
                        # second copy; real errors and exact refs stay intact.
                        derived.pop('action_fingerprint', None)
                        if derived.get('error') is None:
                            derived.pop('error', None)
                        omitted('derived_transition_metadata')
                        continue
                    # Image lengths and generic advice are optional metadata.
                    # Keep exact image refs/SHA, operation/receipt identity and
                    # the unresolved failure; never relabel its outcome.
                    for key in ('before_image', 'after_image'):
                        if isinstance(metadata.get(key), dict):
                            metadata[key].pop('bytes', None)
                    metadata.get('expected_change', {}).pop('description', None)
                    if metadata.get('evidence_capture_refs') == [] and metadata.get('omitted_older_capture_refs') == 0:
                        metadata.pop('evidence_capture_refs')
                        metadata.pop('omitted_older_capture_refs')
                    omitted('optional_transition_metadata')
                    continue
                for key in ('action_semantics', 'action_check', 'instruction_ref', 'decision_ref', 'gaps',
                            'executed_tool_input', 'before_state'):
                    detailed.pop(key, None)
                omitted('transition_details_at_raw_ref')
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
