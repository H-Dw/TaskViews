"""Task modules and bounded semantic projections over immutable execution events.

Only TaskViews reads this projection. Baseline logging does not call a model or
feed these records back to its Agent. Receipt, model assessment and score differ.
"""
from __future__ import annotations

import json
import re

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
        self.subgoals, self.effects, self.unresolved = {}, {}, []
        self.selected_needs, self.page_id = [], None
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved['episode_id'] != journal.episode_id:
                raise ValueError('Task module memory belongs to another episode')
            self.cursor, self.active = saved['cursor'], saved['active']
            self.modules, self.recent = saved['modules'], saved['recent']
            self.gaps = saved.get('gaps', [])
            self.subgoals = saved.get('subgoals', {})
            self.effects = saved.get('effects', {})
            self.unresolved = saved.get('unresolved', [])
            self.selected_needs, self.page_id = saved.get('selected_needs', []), saved.get('page_id')

    def save(self):
        self.memory._atomic_json(self.path, {'episode_id': self.journal.episode_id, 'cursor': self.cursor,
                                             'active': self.active, 'modules': self.modules, 'recent': self.recent,
                                             'gaps': self.gaps[-64:], 'subgoals': self.subgoals,
                                             'effects': self.effects, 'unresolved': self.unresolved,
                                             'selected_needs': self.selected_needs, 'page_id': self.page_id})

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
        before = (self.last_action() or {}).get('before_state')
        old = before['fields'] if before else {}
        new = current_state.get('fields', {}) if isinstance(current_state, dict) else {}
        shared = sorted(set(old) & set(new))
        changed = [key for key in shared if old[key] is not None and new[key] is not None
                   and key.casefold() not in {'clock', 'time', 'timestamp'} and dumps(old[key]) != dumps(new[key])]
        return {'source_observation_id': before['observation_id'] if before else None,
                'source_evidence_ref': before['evidence_ref'] if before else None,
                'shared_field_keys': shared, 'changed_field_keys': changed, 'grade': 'model_proposal'}

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
        if last.get('evidence_capture_refs'):
            value['latest_evidence_capture'] = plain(last['evidence_capture_refs'][-1])
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
        for item in check['checks']:
            if (not isinstance(item, dict) or set(item) != {'kind', 'assessment', 'quotes'}
                    or item['kind'] not in {'focus', 'text', 'submission', 'object', 'state'}
                    or item['assessment'] not in {'observed', 'not_observed', 'unknown'}
                    or not isinstance(item['quotes'], list) or len(item['quotes']) > 4
                    or any(not isinstance(q, str) or not q or len(q) > 256 for q in item['quotes'])
                    or item['assessment'] != 'unknown' and not item['quotes']):
                raise ValueError('Action checks require bounded visible quotes, not a global goal verdict')
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
        if last['expected_change']['kind'] not in kinds:
            raise ValueError('Check the expected change of this specific action')
        if last['expected_change']['kind'] == 'text' and 'focus' not in kinds:
            raise ValueError('Verify focus as well as the typed text')
        if last['expected_change']['kind'] == 'submission' and 'object' not in kinds:
            raise ValueError('Verify the submitted object/result as well as Return')
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
            raise ValueError('Action assessment must agree with its individual checks')
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
        self.effects = dict(list(self.effects.items())[-64:])
        self.unresolved = [r for r in self.unresolved if r['transition_id'] != last['transition_id']]
        if check['assessment'] == 'not_observed' or last['error']:
            self.unresolved = (self.unresolved + [self.transition_packet(last)])[-8:]
        self.report('last_action', value, frame=frame)
        self.save()

    def feedback(self):
        last = self.last_action()
        if not last:
            return {'last_action': None, 'repetition_count': 0, 'strategy_review': False}
        count = 0
        for record in reversed(self.recent):
            if record.get('module_id') != last['module_id'] or record.get('action_fingerprint') != last.get('action_fingerprint'):
                continue
            effect = self.effects.get(record['transition_id'], {})
            legacy_click = (getattr(self, 'compare_state_v10', False)
                and record.get('action_semantics', {}).get('action') in {'left_click', 'right_click', 'double_click', 'key'}
                and not effect.get('state_comparison', {}).get('changed_field_keys'))
            if effect.get('assessment') == 'observed' and not legacy_click:
                break
            count += 1
        return {'last_action': last, 'repetition_count': count, 'strategy_review': count >= 2,
                'guidance': 'Re-observe the intended control and focus; change the strategy after repeated unconfirmed effects. '
                            'Confirm text before submission and the requested object/result after submission. '
                            'Do not infer progress from receipts or whole-image hashes.'}

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
                           'quotes': item['quotes'][:1]})
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
        # No fabricated success or executable gate: a large check stays at its
        # immutable reference, while its exact assessment/count remain present.
        while len(dumps(value).encode()) > 1800 and value['checks']:
            value['checks'].pop()
        if len(dumps(value).encode()) > 1800:
            value['original_parameters'] = {'complete_parameters_ref': last['raw_ref']}
        if len(dumps(value).encode()) > 1800:
            raise ValueError('Cannot bound protected current-action warning')
        return value

    def packet(self, max_bytes=6000):
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
                        raise ValueError('Budget cannot hold the latest action and unresolved failure references')
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
