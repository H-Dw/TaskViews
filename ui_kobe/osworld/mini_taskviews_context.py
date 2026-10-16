"""Fixed-view reads from the original journal, without full TaskViews control."""
from copy import deepcopy
import hashlib
import json
import sqlite3

from kobe_views.fixed_views import MAX_BYTES, PROFILE, materialize
from kobe_views.model import dumps
from kobe_views.controls_view import parse_note, record as controls_record
from kobe_views.keyboard_view import key_topic, record as keyboard_record, select_topic
from . import telemetry
from .actor_context import available_context_bytes
from .checkpoints import ReadAnomaly
from .mini_interaction import interaction_contract
from .mini_evidence import ACTIVE, MiniEvidence
from kobe_views.artifact_view import CHECKS, parse_review, unknown_checks

LABEL = ('TaskViews: sources maps seq refs to immutable events. Reports are unverified; '
         'unknown checks are not success. Verify app/focus and artifact contents on the current image:')
CONTROLS_LABEL = 'Fixed TaskViews with controls guidance (documented defaults guide actions; historical records and visual notes are unverified data):'


def nonempty_error(expression):
    # Official successful receipts contain error="". NULL/empty/whitespace
    # messages and false flags must not consume the lessons error budget.
    return f"""(CASE json_type({expression})
        WHEN 'text' THEN length(trim(json_extract({expression}), char(9)||char(10)||char(13)||' ')) > 0
        WHEN 'true' THEN 1
        WHEN 'object' THEN json_extract({expression}) != '{{}}'
        WHEN 'array' THEN json_extract({expression}) != '[]'
        ELSE 0 END)"""


ERROR_FILTER = """json_extract(e.payload,'$.kind')='transition' AND (
    """ + nonempty_error("e.payload,'$.error'") + """ OR EXISTS (
      SELECT 1 FROM json_each(e.payload,'$.controller_receipts') r WHERE
      json_extract(r.value,'$.result.success')=0 OR """ + nonempty_error("r.value,'$.result.error'") + """
      OR json_extract(r.value,'$.result.status') IN ('error','failed','failure')
      OR (json_type(r.value,'$.result.returncode')='integer'
          AND json_extract(r.value,'$.result.returncode')!=0)))"""
PROSE_VALUE = """coalesce(nullif(json_extract(payload,'$.local_instruction'),''),
    CASE WHEN json_valid(json_extract(payload,'$.response')) THEN
      json_extract(json_extract(payload,'$.response'),'$.content')
    ELSE json_extract(payload,'$.response') END)"""
PROSE_FILTER = "json_extract(payload,'$.kind')='decision' AND typeof(" + PROSE_VALUE + ")='text'"


class MiniTaskViewsContext:
    def __init__(self, owner):
        self.owner = owner
        self.cached = None
        self.trace = {}
        self.delivery = {'profile': PROFILE, 'episode_id': None, 'frame_id': None,
                         'seq': 0, 'packet_sha256': None, 'count': 0}

    def journal(self):
        journal = self.owner.execution_journal
        if journal is None or journal.closed or journal.read_only:
            raise ReadAnomaly('Mini requires a live original execution journal')
        if journal.contract.snapshot() != self.owner.contract.snapshot():
            raise ReadAnomaly('Mini journal contract differs from current actor')
        return journal

    def read(self, query, parameters=()):
        journal = self.journal()
        try:
            result = []
            for seq, identity, encoded in journal.db.execute(query, parameters):
                event = json.loads(encoded)
                if not isinstance(event, dict) or event.get('id') != identity or event.get('episode_id') != journal.episode_id:
                    raise ReadAnomaly('Mini journal event identity/episode mismatch')
                result.append((seq, event, hashlib.sha256(encoded.encode()).hexdigest()))
            return result
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ReadAnomaly('Mini journal read integrity failure') from exc

    def boundary(self):
        """Incomplete or misaligned dispatch is never an optional view failure."""
        journal = self.journal()
        if journal.decision:
            commands = journal.decision['commands']
            if journal.position != len(commands):
                raise ReadAnomaly('Mini checkpoint has an unconfirmed command')
            rows = self.read("SELECT seq,id,payload FROM events WHERE json_extract(payload,'$.kind')='transition' "
                             "AND json_extract(payload,'$.decision_id')=? ORDER BY seq",
                             (journal.decision['id'],))
            if (len(rows) != len(commands) or any(event.get('command_index') != index
                    or event.get('action') != commands[index] or event.get('command_alignment') != 'matched'
                    or event.get('gaps') for index, (_, event, _) in enumerate(rows))):
                raise ReadAnomaly('Mini command/observation evidence is incomplete')

    @staticmethod
    def source(seq, event, digest):
        return {'seq': seq, 'source_event_id': event['id'], 'source_sha256': digest}

    @staticmethod
    def prose(decision):
        text = decision.get('local_instruction')
        if not isinstance(text, str) or not text:
            text = decision.get('response')
            if isinstance(text, str) and text.lstrip().startswith('{'):
                try:
                    text = json.loads(text).get('content')
                except (ValueError, AttributeError):
                    pass  # Plain original prose can also begin with a brace.
        return text if isinstance(text, str) and text else None

    def recent_repetition(self, attempts):
        """Literal recent journal comparison, never a semantic failure judgment."""
        if not attempts:
            return None
        _, latest, _ = attempts[0]
        arguments = (latest.get('tool') or {}).get('arguments')
        if not isinstance(arguments, dict) or arguments.get('action') not in (
                'left_click', 'right_click', 'middle_click', 'double_click', 'triple_click',
                'key', 'type', 'scroll', 'mouse_move', 'hold_key'):
            return None
        repeated = []
        for row in attempts:
            event = row[1]
            if event.get('action') != latest.get('action') or (event.get('tool') or {}).get('arguments') != arguments:
                break
            if not event.get('dispatch_observed') or event.get('command_alignment') != 'matched' or event.get('gaps'):
                return None
            repeated.append(row)
        if len(repeated) < 2:
            return None
        identical = 0
        for _, event, _ in repeated:
            hashes = []
            for key in ('source', 'target'):
                rows = self.read('SELECT seq,id,payload FROM events WHERE id=?', (event.get(key),))
                if len(rows) != 1 or rows[0][1].get('kind') != 'observation':
                    raise ReadAnomaly('Mini repeat feedback observation is unavailable')
                observation = rows[0][1]
                sha = observation.get('images', {}).get('original', {}).get('sha256')
                if (not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha)
                        or sha != observation.get('frame', {}).get('original_sha256')):
                    raise ReadAnomaly('Mini repeat feedback image provenance differs')
                hashes.append(sha)
            identical += hashes[0] == hashes[1]
        _, event, sha = repeated[0]
        return {'grade': 'literal_journal_comparison', 'source_seqs': sorted(row[0] for row in repeated),
                'latest_event_id': event['id'], 'latest_event_sha256': sha, 'action': event['action'],
                'repeat_count': len(repeated), 'same_image_count': identical, 'effect_status': 'unknown'}

    def keyboard_view(self, decisions):
        from mm_agents.qwen.parser import parse_keys
        from .mini_interaction import SILENT_KEY_ALIASES

        topic, selection = select_topic([self.prose(e) for _, e, _ in decisions])
        if topic is None:
            return None
        # A separate keyboard index survives long intervening mouse sequences
        # and native-history trimming. It can only read this episode's journal.
        rows = self.read("SELECT seq,id,payload FROM events WHERE json_extract(payload,'$.kind')='transition' "
                         "AND json_extract(payload,'$.tool.arguments.action') IN ('key','key_down','key_up') "
                         "ORDER BY seq DESC LIMIT 32")
        memories, eligible = [], 0
        for seq, event, digest in rows:
            keys = parse_keys(event['tool']['arguments'].get('keys'))
            if key_topic(keys) != topic:
                continue
            eligible += 1
            if len(memories) >= 2:
                continue
            if not event.get('dispatch_observed') or event.get('command_alignment') != 'matched' or event.get('gaps'):
                raise ReadAnomaly('Mini keyboard memory has unconfirmed dispatch')
            images = []
            for field in ('source', 'target'):
                observed = self.read('SELECT seq,id,payload FROM events WHERE id=?', (event[field],))
                if len(observed) != 1 or observed[0][1].get('kind') != 'observation':
                    raise ReadAnomaly('Mini keyboard memory observation is missing')
                obs = observed[0][1]
                image = obs.get('images', {}).get('original', {}).get('sha256')
                if not isinstance(image, str) or len(image) != 64 or image != obs.get('frame', {}).get('original_sha256'):
                    raise ReadAnomaly('Mini keyboard memory image provenance differs')
                images.append(image)
            invalid = any(key in SILENT_KEY_ALIASES for key in keys)
            # Do not turn previously returned invalid aliases into examples to imitate.
            memories.append({**self.source(seq, event, digest),
                'keys': [SILENT_KEY_ALIASES.get(key, key) for key in keys],
                'key_status': 'suggested_correction_not_executed' if invalid else 'recorded_backend_tokens',
                'receipt': 'recorded; see original event',
                'image_delta': 'same_bytes' if images[0] == images[1] else 'different_bytes',
                'effect_status': 'key_not_emitted' if invalid else 'unknown'})
        return keyboard_record(topic, selection, memories, eligible - len(memories))

    def validate_review_references(self, note, *, final):
        """Check review process/provenance, never certify a model's visual claim."""
        journal = self.journal()
        if not note['applicable']:
            return
        if final and set(note['checks']) != set(CHECKS):
            raise ValueError('Review source, contents, name and destination before success')
        for check in note['checks'].values():
            rows = self.read('SELECT seq,id,payload FROM events WHERE seq=?', (check['ref'],))
            if len(rows) != 1 or rows[0][1].get('kind') != 'observation':
                raise ValueError('Artifact review must reference real same-episode observations')
            observation = rows[0][1]
            same_task = journal.db.execute("SELECT 1 FROM events WHERE json_extract(payload,'$.instruction')=? AND "
                "((json_extract(payload,'$.kind')='task_input' AND json_extract(payload,'$.observation')=?) OR "
                "(json_extract(payload,'$.kind')='transition' AND json_extract(payload,'$.target')=?)) LIMIT 1",
                (journal.task_input['instruction'], observation['id'], observation['id'])).fetchone()
            if not same_task:
                raise ValueError('Artifact evidence belongs to a different task input')
            image = observation.get('images', {}).get('original', {}).get('sha256')
            if not image or image != observation.get('frame', {}).get('original_sha256'):
                raise ReadAnomaly('Artifact review image provenance differs')
        if final and note['checks']['content_previewed']['ref'] != journal.current['seq']:
            raise ValueError('Preview final candidate contents on the current observation before success')

    def require_final_review(self, content, response):
        from ui_kobe.api.kimi_stream import StreamProtocolError
        note = parse_review(content)
        try:
            if note is None:
                raise ValueError('Success requires a bounded <artifact_review> of the candidate, or a reason no artifact is required')
            self.validate_review_references(note, final=True)
        except ValueError as exc:
            raise StreamProtocolError(str(exc), code='mini_artifact_review', observed_response=response.model_dump(),
                                      retryable=True) from exc
        telemetry.emit('mini_artifact_review', applicable_reported=note['applicable'],
            checks_reported=list(note.get('checks', {})), verification=unknown_checks(),
            grade='model_report_not_independent_verification', extra_role_requests=0)

    def context(self, instruction):
        self.cached = None
        self.trace = {'profile': PROFILE, 'frame_id': self.owner.frame.metadata['frame_id'],
                      'delivered': False, 'extra_role_requests': 0}
        journal = self.journal()
        self.boundary()
        current = journal.current
        if (not current or current.get('kind') != 'observation'
                or current.get('frame') != self.owner.frame.metadata
                or not journal.task_input or journal.task_input.get('observation') != current['id']
                or journal.task_input.get('instruction') != instruction):
            raise ReadAnomaly('Mini current frame/task is not the original journal input')
        # These reads are mandatory integrity checks, outside optional packing.
        self.read("SELECT seq,id,payload FROM events WHERE json_extract(payload,'$.kind')='transition' ORDER BY seq DESC LIMIT 4")
        attempts = self.read('SELECT seq,id,payload FROM events WHERE ' + ACTIVE +
                             " AND json_extract(payload,'$.instruction')=? ORDER BY seq DESC LIMIT 4", (instruction,))
        errors = self.read("SELECT e.seq,e.id,e.payload FROM events e WHERE " + ERROR_FILTER +
                           " AND json_extract(e.payload,'$.instruction')=? ORDER BY e.seq DESC LIMIT 4", (instruction,))
        decisions = self.read('SELECT seq,id,payload FROM events WHERE ' + PROSE_FILTER +
                             " AND json_extract(payload,'$.instruction')=? ORDER BY seq DESC LIMIT 2", (instruction,))
        review_rows = self.read('SELECT seq,id,payload FROM events WHERE ' + PROSE_FILTER +
            " AND instr(" + PROSE_VALUE + ",'<artifact_review>')>0 AND json_extract(payload,'$.instruction')=? ORDER BY seq DESC LIMIT 8", (instruction,))
        try:
            attempt_total = journal.db.execute('SELECT count(*) FROM events WHERE ' + ACTIVE +
                " AND json_extract(payload,'$.instruction')=?", (instruction,)).fetchone()[0]
            error_total = journal.db.execute('SELECT count(*) FROM events e WHERE ' + ERROR_FILTER +
                " AND json_extract(e.payload,'$.instruction')=?", (instruction,)).fetchone()[0]
            decision_total = journal.db.execute('SELECT count(*) FROM events WHERE ' + PROSE_FILTER +
                " AND json_extract(payload,'$.instruction')=?", (instruction,)).fetchone()[0]
            cursor = journal.db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]
        except sqlite3.Error as exc:
            raise ReadAnomaly('Mini journal selection failed') from exc
        evidence = MiniEvidence(self)
        current_ref = evidence.observation(current['id'])
        projected = [evidence.operation(row, attempts[index-1][0] if index else cursor+1)
                     for index, row in enumerate(attempts)]
        reviews = [review for row in review_rows if (review := evidence.review(row)) is not None]
        state = evidence.artifact_state(reviews[0] if reviews else None)
        lessons = [{'grade': 'artifact_verification_state', 'current_ref': current_ref,
                    'verification': unknown_checks()}]
        lessons.extend(evidence.error(row) for row in errors)
        lessons.extend(reviews[:1])
        lessons.extend({'ref': evidence.reference(row), 'grade': 'model_intent_proposal', 'text': text}
                       for row in decisions if (text := self.prose(row[1])) and parse_review(text) is None)
        controls = None
        if self.owner.controls_view_enabled:
            previous = None
            for seq, event, digest in decisions:
                note = parse_note(self.prose(event))
                if note is not None:
                    previous = {**self.source(seq, event, digest), **note,
                                'source_observation_id': event.get('source'), 'reobserve_required': True}
                    # A long original note is retained by the journal, not cut into a misleading fragment.
                    if len(dumps(previous).encode()) > 450:
                        previous = {**self.source(seq, event, digest), 'grade': 'model_proposal',
                                    'whole_note_omitted': True, 'note_sha256': note['note_sha256']}
                    break
            controls = controls_record(self.owner.frame.metadata['frame_id'], previous)
            controls.pop('guidance')  # Whole original guidance stays in the declared controls catalog.
            controls['guidance_ref'] = 'mini_controls_v1 catalog'
        # Real errors get first opportunity; proposals never become verified errors.
        limit = min(MAX_BYTES, available_context_bytes(self.owner.actor_input_messages,
                      label=self.owner.context_label, contract=self.owner.contract))
        original_current = {'ref': current_ref, 'artifact': state,
                            'original_sha256': self.owner.frame.original_sha256,
                            'frame_geometry': {key: deepcopy(self.owner.frame.metadata[key]) for key in
                                ('coordinate_type', 'original_size', 'model_size', 'coordinate_bounds')},
                            'grade': 'original_input', 'image_source': 'current_native_message'}
        # Real errors and the legacy opt-in controls pack take precedence over
        # generic workflow advice. The default keyboard reference is independent.
        if not errors and not self.owner.controls_view_enabled:
            original_current['interaction_contract'] = interaction_contract()
        if (repeated := self.recent_repetition(attempts)) is not None:
            repeated = deepcopy(repeated)
            repeated['ref'] = attempts[0][0]
            repeated.pop('latest_event_id')
            repeated.pop('latest_event_sha256')
            original_current['recent_repetition'] = repeated
        keyboard = None if self.owner.controls_view_enabled else self.keyboard_view(decisions)
        if keyboard:
            for memory in keyboard['memory']:
                row = self.read('SELECT seq,id,payload FROM events WHERE id=?', (memory['source_event_id'],))[0]
                memory['ref'] = evidence.reference(row)
                for key in ('seq', 'source_event_id', 'source_sha256'):
                    memory.pop(key, None)
        try:
            packet = materialize(episode_id=journal.episode_id, frame_id=self.owner.frame.metadata['frame_id'],
                current=original_current,
                attempts=projected, lessons=lessons,
                totals={'attempts': attempt_total, 'lessons': error_total + decision_total + 1}, max_bytes=limit,
                controls=controls, keyboard=keyboard, sources=evidence.sources)
            self.cached = dumps(packet) if packet is not None else None
        except (ValueError, TypeError) as exc:
            self.trace['omission_reason'] = type(exc).__name__
        if self.cached:
            self.trace.update(packet_sha256=hashlib.sha256(self.cached.encode()).hexdigest(),
                              packet_bytes=len(self.cached.encode()), journal_seq=cursor,
                              selected_operations=[row['tool']['arguments'] for row in packet['views']['attempts']['records']
                                                   if row.get('tool')],
                              latest_operation_delivered=not projected or any(row['ref']==projected[0]['ref']
                                  for row in packet['views']['attempts']['records']),
                              artifact_review_delivered=not reviews or any(row.get('ref')==reviews[0]['ref']
                                  for row in packet['views']['lessons']['records']),
                              artifact_checks=unknown_checks(),
                              views={key: {'source_event_ids': [evidence.sources[str(row['ref'])]['id']
                                         for row in view['records'] if row.get('ref')],
                                    'omitted_records': view['omitted_records']}
                                     for key, view in packet['views'].items()})
        else:
            self.trace.setdefault('omission_reason', 'whole_envelope_budget')
        telemetry.emit('mini_fixed_views', **self.trace)
        return self.cached

    def delivered(self):
        self.trace['delivered'] = True
        self.delivery = {'profile': PROFILE, 'episode_id': self.journal().episode_id,
                         'frame_id': self.trace['frame_id'], 'seq': self.trace['journal_seq'],
                         'packet_sha256': self.trace['packet_sha256'], 'count': self.delivery['count'] + 1}
        telemetry.emit('mini_views_delivered', **self.delivery)

    def omitted(self, reason):
        self.trace.update(delivered=False, omission_reason=reason)
        telemetry.emit('mini_views_request_omitted', frame_id=self.trace['frame_id'], reason=reason)

    def snapshot(self):
        return deepcopy(self.delivery)

    def restore(self, value):
        journal = self.owner.execution_journal
        if (not isinstance(value, dict) or set(value) != set(self.delivery) or value['profile'] != PROFILE
                or value['episode_id'] not in (None, journal.episode_id if journal else None)
                or type(value['seq']) is not int or value['seq'] < 0
                or type(value['count']) is not int or value['count'] < 0):
            raise ReadAnomaly('Mini fixed-view checkpoint state is incompatible')
        digest = value['packet_sha256']
        if (digest is not None and (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest))) or (value['count'] and (
                journal is None or value['episode_id'] != journal.episode_id or not isinstance(value['frame_id'], str))):
            raise ReadAnomaly('Mini delivery provenance is invalid')
        if journal and value['seq'] > journal.db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]:
            raise ReadAnomaly('Mini delivery cursor exceeds restored journal')
        self.delivery = deepcopy(value)
        self.cached = None  # A restored old frame is never supplied as new context.
