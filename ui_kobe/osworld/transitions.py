"""Append-only official execution evidence, with UI-KOBE transition semantics.

No page matcher, model call, screenshot request, action or success gate lives here.
Observations are immutable versions; optional logical page identities are annotations.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from kobe_views.model import dumps


def now():
    return datetime.now(timezone.utc).isoformat()


class TransitionJournal:
    def __init__(self, directory, *, task_id, run_id, contract, episode_id=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.task_id, self.run_id, self.contract = task_id, run_id, contract
        self.episode_id = episode_id or uuid.uuid4().hex
        self.path = self.directory / (self.episode_id + '.sqlite')
        if self.path.exists():
            raise ValueError('Episode already exists; use open_readonly for replay')
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events '
                        '(seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
        self.db.execute('CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON events '
                        "BEGIN SELECT RAISE(ABORT, 'immutable event'); END")
        self.db.execute('CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON events '
                        "BEGIN SELECT RAISE(ABORT, 'immutable event'); END")
        self.current = self.decision = self.task_input = None
        self.position = 0
        self.closed = False
        self.read_only = False
        self.append('episode', task_id=task_id, run_id=run_id, cua_contract=contract.snapshot())

    @classmethod
    def open_readonly(cls, path):
        journal = cls.__new__(cls)
        journal.path = Path(path)
        journal.directory = journal.path.parent
        journal.db = sqlite3.connect(journal.path.resolve().as_uri() + '?mode=ro', uri=True)
        header = journal.read()[0]
        journal.task_id, journal.run_id, journal.episode_id = (header[k] for k in ('task_id', 'run_id', 'episode_id'))
        journal.closed, journal.read_only = False, True
        return journal

    def append(self, kind, *, event_id=None, **fields):
        record = {'id': event_id or uuid.uuid4().hex, 'kind': kind, 'time_utc': now(),
                  'task_id': self.task_id, 'run_id': self.run_id, 'episode_id': self.episode_id, **fields}
        encoded = dumps(record)
        old = self.db.execute('SELECT seq,payload FROM events WHERE id=?', (record['id'],)).fetchone()
        if old:
            # A retry must carry the entire original record, including its time.
            raise ValueError('Execution event identity already used')
        with self.db:
            cursor = self.db.execute('INSERT INTO events(id,payload) VALUES (?,?)', (record['id'], encoded))
        return {'seq': cursor.lastrowid, **record}

    def read(self, after=0, *, limit=256):
        return [{'seq': seq, **json.loads(payload)} for seq, payload in self.db.execute(
            'SELECT seq,payload FROM events WHERE seq>? ORDER BY seq LIMIT ?', (after, limit))]

    def reference(self, record):
        return str(self.path) + '#' + record['id']

    def observe(self, obs, *, step, phase):
        image = obs.get('screenshot')
        if not isinstance(image, (bytes, bytearray)):
            self.current = None
            return self.append('observation_gap', step=step, phase=phase, reason='missing_screenshot')
        frame = self.contract.process(bytes(image), step)
        model = base64.b64decode(frame.screenshot.data_url.split(',', 1)[1])
        references = {}
        for name, data in (('original', image), ('model', model)):
            sha = hashlib.sha256(data).hexdigest()
            extension = '.png' if bytes(data).startswith(b'\x89PNG') else '.jpg' if bytes(data).startswith(b'\xff\xd8') else '.bin'
            path = self.directory / 'images' / (sha + extension)
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                path.write_bytes(data)
            references[name] = {'ref': str(path), 'sha256': sha, 'bytes': len(data)}
        observation = self.append('observation', step=step, phase=phase, frame=frame.metadata,
                                  images=references, logical_page=None, state_schema=None)
        self.current = observation
        return observation

    def begin(self, instruction, obs, *, step):
        self.finish_pending('next_decision')
        observation = self.observe(obs, step=step, phase='decision_input')
        self.task_input = self.append('task_input', step=step, instruction=instruction,
                                     observation=observation['id'], user_response=obs.get('user_response'))
        self.decision = None
        self.position = 0

    def decide(self, response, commands, *, step, tools=(), local_instruction=None):
        self.decision = self.append('decision', step=step, response=response, commands=list(commands),
            tools=list(tools), source=self.current['id'] if self.current else None,
            instruction_ref=self.reference(self.task_input) if self.task_input else None,
            instruction=self.task_input['instruction'] if self.task_input else None, local_instruction=local_instruction,
            interpretation='model_intent_not_execution')
        self.position = 0
        return self.decision

    def result(self, action, *, step, observation=None, receipts=(), info=None, error=None):
        source = self.current
        target = self.observe(observation, step=step, phase='action_output') if observation is not None else None
        if target and target['kind'] != 'observation':
            target = None
        decision = self.decision
        commands = decision['commands'] if decision else []
        matched = self.position < len(commands) and commands[self.position] == action
        tool = None
        if matched:
            tool = next((item for item in decision['tools'] if self.position in item.get('command_indices', [])), None)
        record = self.append('transition', step=step, decision_id=decision['id'] if decision else None,
            command_index=self.position, source=source['id'] if source else None,
            target=target['id'] if target else None, action=action, tool=tool,
            instruction_ref=decision['instruction_ref'] if decision else None,
            instruction=decision['instruction'] if decision else None,
            decision_ref=self.reference(decision) if decision else None,
            local_instruction=decision['local_instruction'] if decision else None,
            target_observation=self.reference(target) if target else None, schema_delta=None,
            controller_receipts=list(receipts), info=info, error=error,
            dispatch_observed=True, effect_status='unknown', command_alignment='matched' if matched else 'unknown',
            gaps=[reason for condition, reason in ((source is None, 'missing_source'),
                  (target is None, 'missing_target'), (not matched, 'command_alignment_unknown')) if condition])
        self.position += 1
        # Never associate a future command with a pre-error or missing screenshot.
        if target is None:
            self.current = None
        return record

    def annotate(self, observation_id, *, logical_page, state_schema, evidence_ref, grade='model_proposal'):
        """Optional page/state descriptions are separate versioned evidence, not frame edits."""
        row = self.db.execute('SELECT payload FROM events WHERE id=?', (observation_id,)).fetchone()
        if not row or json.loads(row[0])['kind'] != 'observation':
            raise ValueError('Unknown observation annotation target')
        return self.append('observation_annotation', observation_id=observation_id, logical_page=logical_page,
                           state_schema=state_schema, evidence_ref=evidence_ref, grade=grade)

    def finish_pending(self, reason):
        if self.decision:
            for index in range(self.position, len(self.decision['commands'])):
                self.append('unexecuted_command', decision_id=self.decision['id'], command_index=index,
                            action=self.decision['commands'][index], reason=reason, dispatch_observed=False)
            self.decision = None

    def phase(self, kind, **fields):
        if kind in ('evaluation_start', 'decision_error', 'episode_close'):
            self.finish_pending(kind)
        return self.append(kind, **fields)

    def close(self):
        if not self.closed:
            try:
                if not self.read_only:
                    self.phase('episode_close')
                    output = self.path.with_suffix('.ui-kobe.json')
                    temporary = output.with_suffix('.tmp')
                    temporary.write_text(dumps(self.export_ui_kobe()) + '\n', encoding='utf-8')
                    temporary.replace(output)
            finally:
                self.db.close()
                self.closed = True

    def export_ui_kobe(self):
        """Lossless per-attempt edge export; never aggregate parallel optional arrays."""
        observations, annotations, transitions = {}, {}, []
        cursor = 0
        while rows := self.read(cursor):
            for row in rows:
                if row['kind'] == 'observation':
                    observations[row['id']] = row
                elif row['kind'] == 'observation_annotation':
                    annotations[row['observation_id']] = row
                elif row['kind'] == 'transition':
                    transitions.append(row)
            cursor = rows[-1]['seq']
        nodes = [{'id': oid, 'page_description': '', 'activity': '',
                  'logical_page': annotations.get(oid, {}).get('logical_page'),
                  'state_schema': annotations.get(oid, {}).get('state_schema'),
                  'observation': observation} for oid, observation in observations.items()]
        edges = []
        for row in transitions:
            before, after = annotations.get(row['source']), annotations.get(row['target'])
            delta = None
            if before and after and before['logical_page'] and before['logical_page'] == after['logical_page']:
                left, right = before['state_schema'], after['state_schema']
                if isinstance(left, dict) and isinstance(right, dict):
                    delta = {key: {'before': left.get(key), 'after': right.get(key),
                                  'before_present': key in left, 'after_present': key in right}
                             for key in left.keys() | right.keys()
                             if (key in left) != (key in right) or left.get(key) != right.get(key)} or None
            # A missing endpoint remains an explicit event gap, not a fabricated node.
            edges.append({**row, 'schema_delta': delta,
                          'schema_delta_evidence': [self.reference(before), self.reference(after)] if delta else [],
                          'schema_delta_grade': 'model_proposal' if delta else None,
                          'metadata_alignment': 'paired_event'})
        return {'schema_version': 2, 'episode_id': self.episode_id, 'nodes': nodes, 'edges': edges}


def decision_tools(agent):
    """Describe already compiled commands; parsing here cannot affect execution."""
    native = getattr(agent, 'last_trace', {}).get('native_actions')
    if native is not None:
        ids = getattr(agent, 'pending', None) or []
        ids = [ids] if isinstance(ids, str) else ids
        indices = getattr(agent, 'command_call_indices', [])
        return [{'id': ids[i] if i < len(ids) else None, 'arguments': args,
                 'command_indices': [j for j, index in enumerate(indices) if index == i]}
                for i, args in enumerate(native)]
    from mm_agents.qwen.parser import parse_tool_calls
    from mm_agents.qwen.actions import translate_tool_calls
    calls = parse_tool_calls(agent.responses[-1])
    position, result = 0, []
    for i, call in enumerate(calls):
        batch = translate_tool_calls([call], screenshot=agent.previous_full_screen,
                                     coordinate_type=agent.coordinate_type, enable_zoom=False)
        result.append({'id': None, 'xml_call_index': i, 'arguments': call.parameters,
                       'command_indices': list(range(position, position + len(batch.commands)))})
        position += len(batch.commands)
    return result
