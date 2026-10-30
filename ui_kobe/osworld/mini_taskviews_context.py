"""Fixed-view reads from the original journal, without full TaskViews control."""
from copy import deepcopy
import hashlib
import json
import sqlite3

from kobe_views.fixed_views import MAX_BYTES, PROFILE, materialize
from kobe_views.model import dumps
from kobe_views.controls_view import parse_note, record as controls_record
from kobe_views.keyboard_view import key_topic, lookup_guide, record as keyboard_record, select_topic
from . import telemetry
from .actor_context import available_context_bytes
from .checkpoints import ReadAnomaly, atomic
from kobe_views import mini_graph
from kobe_views import keyboard_guidance
from kobe_views.review_presentation import schema as review_schema
from .mini_interaction import interaction_contract
from .mini_evidence import ACTIVE, MiniEvidence
from kobe_views.artifact_view import CHECKS, REVIEW_SCHEMA, ReviewError, parse_review, unknown_checks, validate_review

LABEL = ('TaskViews: sources maps seq refs to immutable events. Unknown=no independent certification; '
         'complete only after evidence review; reports never upgrade unknown. Missing evidence: inspect, never invent:')
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
        self.graph_index = None
        self.graph_audit = None
        self.projection_inputs = None
        self.guidance_selection = None
        self.guidance_records = []
        self.guidance_directory_visible = False
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

        toolsets = self.owner.keyboard_toolsets
        task_catalog = self.owner.task_keyboard
        topic, selection = select_topic([self.prose(e) for _, e, _ in decisions], toolsets, task_catalog)
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
            if key_topic([SILENT_KEY_ALIASES.get(key, key) for key in keys], topic, toolsets, task_catalog) != topic:
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
        return keyboard_record(topic, selection, memories, eligible - len(memories),
                               toolsets=toolsets, task_catalog=task_catalog)

    def validate_review_references(self, note, *, final):
        """Check review process/provenance, never certify a model's visual claim."""
        journal = self.journal()
        if not note['applicable']:
            return
        if final and set(note['checks']) != set(CHECKS):
            raise ReviewError('missing_checks', 'Review all four checks before success')
        issues = []
        for key, check in note['checks'].items():
            # Report all explicit reference defects in this bounded four-field
            # report. Never replace references or infer the model's facts.
            label = f"{key}.ref={str(check['ref'])[:80]}"
            if check['ref'] > journal.current['seq']:
                issues.append(('invalid_reference', f'{label}: no observation at this seq in the current episode'))
                continue
            rows = self.read('SELECT seq,id,payload FROM events WHERE seq=?', (check['ref'],))
            if len(rows) != 1 or rows[0][1].get('kind') != 'observation':
                issues.append(('invalid_reference', f'{label}: must identify a real same-episode observation'))
                continue
            observation = rows[0][1]
            same_task = journal.db.execute("SELECT 1 FROM events WHERE json_extract(payload,'$.instruction')=? AND "
                "((json_extract(payload,'$.kind')='task_input' AND json_extract(payload,'$.observation')=?) OR "
                "(json_extract(payload,'$.kind')='transition' AND json_extract(payload,'$.target')=?)) LIMIT 1",
                (journal.task_input['instruction'], observation['id'], observation['id'])).fetchone()
            if not same_task:
                issues.append(('wrong_task_reference', f'{label}: observation belongs to a different task input'))
                continue
            image = observation.get('images', {}).get('original', {}).get('sha256')
            if not image or image != observation.get('frame', {}).get('original_sha256'):
                raise ReadAnomaly('Artifact review image provenance differs')
        if final and note['checks']['content_previewed']['ref'] != journal.current['seq']:
            issues.append(('stale_preview', 'content_previewed.ref must equal current.ref; '
                           'preview candidate contents on the current observation before success'))
        if issues:
            raise ReviewError(issues[0][0], '; '.join(detail for _, detail in issues))

    def require_final_review(self, content):
        try:
            note = validate_review(content, final=True)
            self.validate_review_references(note, final=True)
        except ReviewError as exc:
            telemetry.emit('mini_artifact_review_rejected', failure=exc.code, action_executed=False)
            # This is an auxiliary report failure, not a native tool protocol
            # failure. Mini's bounded loop handles it without reasoning replay.
            raise
        telemetry.emit('mini_artifact_review', applicable_reported=note['applicable'],
            checks_reported=list(note.get('checks', {})), verification=unknown_checks(),
            grade='model_report_not_independent_verification', extra_role_requests=0)

    def context(self, instruction, *, knowledge_query=None):
        self.cached = None
        self.guidance_selection = None
        self.guidance_records = []
        self.guidance_directory_visible = False
        self.trace = {'profile': PROFILE, 'frame_id': self.owner.frame.metadata['frame_id'],
                      'delivered': False, 'artifact_protocol_in_packet': False, 'extra_role_requests': 0}
        self.trace['context_revision'] = knowledge_query['seq'] if knowledge_query else 0
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
            # Source IDs still resolve through the immutable controls policy;
            # repeating static URLs competes with real operation evidence.
            controls['sources'] = list(controls['sources'])
        # Real errors get first opportunity; proposals never become verified errors.
        limit = min(MAX_BYTES, available_context_bytes(self.owner.actor_input_messages,
                      label=self.owner.context_label, contract=self.owner.contract))
        # Geometry is already mandatory in this request's native frame contract.
        # current_ref resolves the immutable observation (including image hash),
        # so duplicate geometry/hash fields must not displace review evidence.
        original_current = {'ref': current_ref, 'artifact': state,
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
        guidance_enabled = self.owner.guidance_policy is not None
        keyboard = None if self.owner.controls_view_enabled or guidance_enabled else self.keyboard_view(decisions)
        delivery_v2 = self.owner.mini_graph_policy['packing'] == mini_graph.DELIVERY_PACKING
        if guidance_enabled:
            # Bounded original evidence only, including task boundaries. The
            # journal is the checkpoint: rebuild phase on every call/restore.
            routing_rows = self.read('SELECT seq,id,payload FROM events ORDER BY seq DESC LIMIT ?',
                                     (keyboard_guidance.HISTORY,))
            boundary = max((seq for seq, event, _ in routing_rows if event.get('kind') == 'task_input'
                            and event.get('instruction') != instruction), default=0)
            routing_decisions = [row for row in routing_rows if row[0] > boundary
                                 and row[1].get('kind') == 'decision' and row[1].get('instruction') == instruction][:2]
            proposals = [(seq, self.prose(event), event['step']) for seq, event, _ in routing_decisions]
            if knowledge_query is not None:
                found = next((r for r in routing_rows if r[0] == knowledge_query['seq']), None)
                if (not found or found[1]['kind'] != 'knowledge_query' or found[1]['id'] != knowledge_query['id']
                        or found[1].get('instruction') != instruction or found[1].get('step') != journal.task_input['step']
                        or found[1].get('source') != current['id']):
                    raise ReadAnomaly('Knowledge request is not sourced to the current task/frame')
                from kobe_views.decision_flow import validate_query
                query = validate_query(found[1]['query'])
                proposals = [(found[0], query['intent'], found[1]['step'])]
                original_current['strategy'] = {'ref': evidence.reference(found), 'grade': 'model_strategy_proposal'}
            from kobe_views.operation_support import build as operation_support, intent_excerpt
            support = operation_support(rows=routing_rows, instruction=instruction, proposals=proposals,
                step=journal.task_input['step'], observation_ref=current_ref,
                decision_limit=self.owner.guidance_policy['decision_limit'])
            from kobe_views.attempt_retrieval import retrieve as retrieve_attempt
            retrieval = retrieve_attempt(routing_rows, instruction, proposals, journal.task_input['step'])
            recall = retrieval['selected']
            # No ungated navigation fallback can reintroduce rejected records.
            support['navigation_recall'] = recall
            self.trace['attempt_retrieval'] = {'version': retrieval['audit']['version'],
                'selected_ref': recall['ref'] if recall else None, 'in_packet_refs': [],
                'delivered': False, 'delivery_status': 'pending' if recall else 'not_selected'}
            telemetry.emit('mini_attempt_retrieval_prepared', frame_id=self.trace['frame_id'],
                context_revision=self.trace['context_revision'], episode_id=journal.episode_id,
                journal_seq=cursor, audit=retrieval['audit'])
            original_current['artifact']['review_schema'] = review_schema(self.owner.guidance_policy, finishing=support['finishing'])
            if support['finishing']:
                original_current['completion'] = support['completion']
            if support['feedback']:
                original_current['action_conditions'] = support['feedback']
                # The source-bound constraint replaces duplicate generic
                # repeat counts; the full detection remains in local audit.
                if support['audit'].get('cycle'):
                    original_current.pop('recent_repetition', None)
            if support['reading_progress']:
                original_current['reading_progress'] = {'condition': support['reading_condition'],
                                                         'reports': support['reading_progress']}
            telemetry.emit('mini_operation_support_prepared', frame_id=self.trace['frame_id'],
                episode_id=journal.episode_id, support=support)
            self.guidance_selection = keyboard_guidance.route(instruction=instruction,
                enabled=self.owner.guidance_policy['enabled_toolsets'], rows=routing_rows,
                proposals=proposals, step=journal.task_input['step'], observation_ref=current_ref,
                task_catalog=self.owner.task_keyboard, frozen_capabilities=self.owner.guidance_policy['capabilities'],
                pending_effect=support['pending_effect'], readability=support['readability'],
                adjustment_chain=support['adjustment_chain'],
                proposal_origin='public_knowledge_request' if knowledge_query else 'public_proposal',
                missing_knowledge=query['missing_knowledge'] if knowledge_query else None)
            by_seq = {row[0]: row for row in routing_rows}
            lessons.extend(deepcopy(support['reading_progress']))
            if recall:
                row = by_seq[recall['ref']]
                recalled = next((r for r in projected if r['ref'] == recall['ref']), None)
                if recalled is None:
                    recalled = evidence.operation(row)
                    attempts.append(row)
                    projected.append(recalled)
                # Recalled failures are useful conditions to avoid, never a
                # reusable success path. Preserve their real error signals.
                failed = journal.db.execute('SELECT 1 FROM events e WHERE e.seq=? AND ' + ERROR_FILTER,
                                            (row[0],)).fetchone()
                if failed:
                    recalled.update(evidence.error(row))
                    recalled['grade'] = 'execution_attempt'
                recalled['recall'] = {'query': {'ref': evidence.reference(by_seq[recall['query_ref']])},
                    'basis': recall['basis'], 'purpose': recall['purpose'],
                    'parameters': recall['parameters'], 'coordinates': 're_ground_current_image', 'effect': 'unknown'}
            # Attempts were already dispatched facts. Attach an optional short
            # issuing intention so a coordinate can be understood in context;
            # never invent a window name or infer success from that intention.
            for row, record in zip(attempts, projected):
                event = row[1]
                issuing = next((r for r in routing_rows if r[0] < row[0]
                    and r[1].get('kind') == 'decision' and event.get('decision_id')
                    and r[1].get('id') == event['decision_id']
                    and r[1].get('instruction') == instruction), None)
                if issuing:
                    text = (recall['text'] if recall and row[0] == recall['ref'] else
                            intent_excerpt(self.prose(issuing[1])))
                    if text:
                        record['intent'] = {'ref': evidence.reference(issuing),
                            'grade': 'model_intent_proposal', 'text': text}
            for candidate in self.guidance_selection['groups']:
                for item in candidate['record']['evidence']:
                    if item['ref'] not in by_seq:
                        raise ReadAnomaly('Guidance source exceeds bounded journal evidence')
                    evidence.reference(by_seq[item['ref']])
            for ref in mini_graph.references({key: original_current[key] for key in
                    ('action_conditions', 'reading_progress') if key in original_current}):
                if ref not in by_seq:
                    raise ReadAnomaly('Operation support reference exceeds bounded journal evidence')
                if by_seq[ref][1].get('kind') == 'observation':
                    evidence.observation(by_seq[ref][1]['id'])
                else:
                    evidence.reference(by_seq[ref])
            original_current['keyboard_lookup'] = {
                'enabled': self.owner.guidance_policy['enabled_toolsets'],
                'guide_names': [c['record']['guide_id'].split(':')[0] for c in self.guidance_selection['groups']],
                'focus': 'unconfirmed'}
        elif delivery_v2:
            from kobe_views.mini_delivery import lookup_guide as delivery_lookup
            original_current['keyboard_lookup'] = delivery_lookup(
                [self.prose(e) for _, e, _ in decisions], self.owner.keyboard_toolsets, self.owner.task_keyboard)
        elif not self.owner.controls_view_enabled and keyboard is None:
            original_current['keyboard_lookup'] = lookup_guide(self.owner.keyboard_toolsets, self.owner.task_keyboard)
        if keyboard:
            for memory in keyboard['memory']:
                row = self.read('SELECT seq,id,payload FROM events WHERE id=?', (memory['source_event_id'],))[0]
                memory['ref'] = evidence.reference(row)
                # The literal receipt remains under ref; repeating "recorded"
                # can evict the actual keys and observed image delta.
                for key in ('seq', 'source_event_id', 'source_sha256', 'receipt'):
                    memory.pop(key, None)
        arguments = dict(frame_id=self.owner.frame.metadata['frame_id'], current=original_current,
            attempts=projected, lessons=lessons,
            totals={'attempts': attempt_total, 'lessons': error_total + decision_total + 1
                    + (len(support['reading_progress']) if guidance_enabled else 0)}, max_bytes=limit,
            keyboard=keyboard, sources=evidence.sources)
        self.projection_inputs = deepcopy(arguments)
        graph_mode = self.owner.mini_graph_mode
        packet = None
        try:
            if guidance_enabled:
                from kobe_views.guidance_delivery import materialize as deliver_guidance
                if graph_mode != 'legacy':
                    if self.graph_index is None:
                        self.graph_index = mini_graph.GraphIndex(journal.episode_id, journal.task_id)
                    self.graph_index.sync(self.read)
                packet = deliver_guidance(episode_id=journal.episode_id, index=self.graph_index,
                    instruction=instruction, graph_mode=graph_mode, packing=self.owner.mini_graph_policy['packing'],
                    selection=self.guidance_selection, review_policy=self.owner.guidance_policy,
                    finishing=support['finishing'], **arguments)
            elif graph_mode == 'legacy':
                packet = materialize(episode_id=journal.episode_id, controls=controls, **arguments)
            else:
                if self.graph_index is None:
                    self.graph_index = mini_graph.GraphIndex(journal.episode_id, journal.task_id)
                self.graph_index.sync(self.read)
                for ref in evidence.sources:
                    self.graph_index.event(int(ref), evidence.sources)
                packet = mini_graph.materialize(index=self.graph_index, instruction=instruction,
                    graph_mode=graph_mode, toolsets=self.owner.keyboard_toolsets,
                    task_catalog=self.owner.task_keyboard, packing=self.owner.mini_graph_policy['packing'], **arguments)
            self.cached = dumps(packet) if packet is not None else None
        except mini_graph.GraphIntegrityError as exc:
            raise ReadAnomaly(str(exc)) from exc
        except (ValueError, TypeError) as exc:
            self.trace['omission_reason'] = type(exc).__name__
        if self.cached:
            display = packet if graph_mode == 'legacy' else mini_graph.expand(packet)
            if guidance_enabled:
                self.guidance_records = display['views']['keyboard']['records']
                self.guidance_directory_visible = 'keyboard_lookup' in display['views']['current']['records'][0]
            self.trace.update(packet_sha256=hashlib.sha256(self.cached.encode()).hexdigest(),
                              keyboard_lookup_omitted='keyboard_lookup' in original_current
                                  and 'keyboard_lookup' not in display['views']['current']['records'][0],
                              packet_bytes=len(self.cached.encode()), journal_seq=cursor,
                              selected_operations=[row['tool']['arguments'] for row in display['views']['attempts']['records']
                                                   if row.get('tool')],
                              latest_operation_delivered=not projected or any(row['ref']==projected[0]['ref']
                                  for row in display['views']['attempts']['records']),
                              artifact_review_delivered=not reviews or any(row.get('ref')==reviews[0]['ref']
                                  for row in display['views']['lessons']['records']),
                              artifact_checks=unknown_checks(),
                              keyboard_delivery={'candidate': keyboard is not None,
                                  'topic': keyboard['topic'] if keyboard else None,
                                  'recipes': sum(len(r['recipes']) for r in display['views'].get('keyboard', {}).get('records', [])),
                                  'recipes_omitted': sum(r.get('recipes_omitted', 0) for r in display['views'].get('keyboard', {}).get('records', [])),
                                  'lookup_delivered': 'keyboard_lookup' in display['views']['current']['records'][0]},
                              artifact_protocol_in_packet=display['views']['current']['records'][0]
                                  ['artifact']['review_schema'] == (review_schema(self.owner.guidance_policy, finishing=support['finishing'])
                                      if guidance_enabled else REVIEW_SCHEMA),
                              views={key: {'source_event_ids': [evidence.sources[str(row['ref'])]['id']
                                         for row in view['records'] if row.get('ref')],
                                    'omitted_records': view['omitted_records']}
                                     for key, view in display['views'].items()})
            if guidance_enabled:
                sent_current = display['views']['current']['records'][0]
                from kobe_views.decision_flow import VERSION as FLOW_VERSION
                recalled_refs = [r['ref'] for r in display['views']['attempts']['records'] if r.get('recall')]
                self.trace['attempt_retrieval'].update(in_packet_refs=recalled_refs,
                    delivery_status=('packaged' if recalled_refs else 'omitted_budget' if recall else 'not_selected'))
                self.trace['decision_flow'] = {'version': FLOW_VERSION,
                    'strategy_source': 'current_knowledge_request' if knowledge_query else 'prefetch_not_current_plan',
                    'strategy_ref': knowledge_query['seq'] if knowledge_query else None,
                    'current_observation_ref': current_ref,
                    'attempt_retrieved_ref': recall['ref'] if recall else None,
                    'attempt_delivered_refs': recalled_refs,
                    'attempt_omitted_budget': bool(recall and recall['ref'] not in recalled_refs),
                    'knowledge_matched': bool(self.guidance_selection['groups']),
                    'knowledge_delivered': bool(self.guidance_records),
                    'model_use': 'unobserved_not_inferred_from_parameter_match'}
                self.trace['operation_support'] = {
                    'review_prompt': self.owner.guidance_policy['review_prompt'],
                    'review_timing': self.owner.guidance_policy['review_timing'],
                    'review_budget': self.owner.guidance_policy['review_budget'],
                    'review_full_format': support['finishing'],
                    'pending_effect': support['pending_effect'],
                    'conditions_prepared': len(original_current.get('action_conditions', [])),
                    'conditions_in_packet': len(sent_current.get('action_conditions', [])),
                    'reading_reports_prepared': len(original_current.get('reading_progress', {}).get('reports', [])),
                    'reading_reports_in_packet': sum(r.get('grade') == 'model_reading_proposal'
                        for r in display['views']['lessons']['records']),
                    'reading_refs_in_packet': sorted({r['ref'] for r in display['views']['lessons']['records']
                        if r.get('grade') == 'model_reading_proposal'}),
                    'navigation_recall_prepared': support['navigation_recall'] is not None,
                    'navigation_recall_in_packet': any(r.get('recall') for r in display['views']['attempts']['records']),
                    'view_records_in_packet': {k: len(v['records']) for k, v in display['views'].items()},
                    'model_adoption': 'unknown',
                    'delivered': False,
                    'completion_in_packet': 'completion' in sent_current,
                    'packet_is_not_delivery_receipt': True}
                delivered_recipe_count = sum(len(r['recipes']) for r in self.guidance_records)
                self.trace['keyboard_delivery'].update(
                    candidate=bool(self.guidance_selection['groups']),
                    guidance_groups=len(self.guidance_records),
                    recipes_omitted=sum(len(c['record']['recipes']) for c in self.guidance_selection['groups'])
                        - delivered_recipe_count)
        else:
            self.trace.setdefault('omission_reason', 'whole_envelope_budget')
            if guidance_enabled and recall:
                self.trace['attempt_retrieval']['delivery_status'] = 'whole_envelope_budget'
        if guidance_enabled:
            self.trace['guidance'] = keyboard_guidance.delivery_audit(self.guidance_selection,
                self.guidance_records, self.guidance_directory_visible)
            telemetry.emit('mini_guidance_prepared', frame_id=self.trace['frame_id'],
                context_revision=self.trace['context_revision'],
                episode_id=journal.episode_id, journal_seq=cursor, policy=self.owner.guidance_policy,
                selection=self.guidance_selection, event_sources=evidence.sources, metrics=self.trace['guidance'],
                omission_reason=self.trace.get('omission_reason'))
        if graph_mode != 'legacy':
            if packet and delivery_v2:
                from kobe_views.mini_delivery import unpack
                audit_links = unpack(packet)['links']
            else:
                audit_links = packet['links'] if packet else []
            refs = [r[0] for v in packet['views'].values() for r in v['record_refs']] if packet else []
            graph_trace = {'mode': graph_mode, 'schema_version': self.owner.mini_graph_policy['schema_version'],
                'id_version': mini_graph.ID_VERSION, 'packing': self.owner.mini_graph_policy['packing'], 'journal_seq': cursor,
                'node_count': len(packet['nodes']) if packet else 0,
                'link_count': len(audit_links),
                'shared_reference_count': len(refs) - len(set(refs)),
                'facts_sha256': mini_graph.sha({k: packet[k] for k in ('nodes', 'views', 'sources')}) if packet else None}
            self.trace['graph'] = graph_trace
            self.graph_audit = {**self.graph_index.audit(), 'policy': self.owner.mini_graph_policy.copy(),
                'projection': {**graph_trace, 'packet_bytes': self.trace.get('packet_bytes', 0),
                    'packet_sha256': self.trace.get('packet_sha256'), 'delivered': False,
                    'omission_reason': self.trace.get('omission_reason')}, 'links': audit_links}
            self.save_graph_audit()
        telemetry.emit('mini_fixed_views', **self.trace)
        return self.cached

    def delivered(self):
        self.trace['delivered'] = True
        if 'operation_support' in self.trace:
            self.trace['operation_support']['delivered'] = True
            telemetry.emit('mini_operation_support_delivered', frame_id=self.trace['frame_id'],
                episode_id=self.journal().episode_id, packet_sha256=self.trace['packet_sha256'],
                metrics=self.trace['operation_support'])
        self.guidance_delivery(True)
        self.delivery = {'profile': PROFILE, 'episode_id': self.journal().episode_id,
                         'frame_id': self.trace['frame_id'], 'seq': self.trace['journal_seq'],
                         'packet_sha256': self.trace['packet_sha256'], 'count': self.delivery['count'] + 1}
        telemetry.emit('mini_views_delivered', **self.delivery)
        if self.graph_audit is not None:
            self.graph_audit['projection']['delivered'] = True
            self.save_graph_audit()

    def omitted(self, reason):
        self.trace.update(delivered=False, omission_reason=reason)
        self.guidance_delivery(False)
        telemetry.emit('mini_views_request_omitted', frame_id=self.trace['frame_id'], reason=reason)
        if self.graph_audit is not None:
            self.graph_audit['projection'].update(delivered=False, omission_reason=reason)
            self.save_graph_audit()

    def save_graph_audit(self):
        journal = self.journal()
        atomic(journal.directory / (journal.episode_id + '.mini-graph.json'), self.graph_audit)

    def guidance_delivery(self, delivered):
        if 'attempt_retrieval' in self.trace:
            metrics = self.trace['attempt_retrieval']
            metrics['delivered'] = bool(delivered and metrics['in_packet_refs'])
            if metrics['delivered']:
                metrics['delivery_status'] = 'delivered'
            elif not delivered and metrics['selected_ref'] is not None:
                metrics['delivery_status'] = self.trace.get('omission_reason', 'request_not_delivered')
            telemetry.emit('mini_attempt_retrieval_delivery', frame_id=self.trace['frame_id'],
                context_revision=self.trace.get('context_revision', 0), episode_id=self.journal().episode_id,
                packet_sha256=self.trace.get('packet_sha256'), metrics=metrics)
        if self.guidance_selection is None:
            return
        metrics = keyboard_guidance.delivery_audit(self.guidance_selection, self.guidance_records,
                                                   self.guidance_directory_visible, delivered)
        self.trace['guidance'] = metrics
        telemetry.emit('mini_guidance_delivery', frame_id=self.trace['frame_id'],
            context_revision=self.trace.get('context_revision', 0),
            episode_id=self.journal().episode_id, packet_sha256=self.trace.get('packet_sha256'), metrics=metrics,
            omission_reason=self.trace.get('omission_reason'))

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
        self.graph_index = None
        self.graph_audit = None
