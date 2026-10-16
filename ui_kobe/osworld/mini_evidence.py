"""Small journal projections; source integrity is distinct from semantic truth."""
from copy import deepcopy
import json

from kobe_views.artifact_view import CHECKS, REVIEW_SCHEMA, parse_review, unknown_checks
from .checkpoints import ReadAnomaly

PASSIVE = "json_extract(payload,'$.tool.arguments.action') IN ('screenshot','wait')"
ACTIVE = "json_extract(payload,'$.kind')='transition' AND NOT coalesce((" + PASSIVE + "),0)"


class MiniEvidence:
    def __init__(self, context):
        self.context = context
        self.sources = {}
        self.observations = {}

    def reference(self, row):
        seq, event, digest = row
        self.sources[str(seq)] = {'id': event['id'], 'sha256': digest, 'kind': event['kind']}
        return seq

    def observation(self, identity):
        if identity not in self.observations:
            rows = self.context.read('SELECT seq,id,payload FROM events WHERE id=?', (identity,))
            if len(rows) != 1 or rows[0][1].get('kind') != 'observation':
                raise ReadAnomaly('Mini operation observation is missing')
            event = rows[0][1]
            image = event.get('images', {}).get('original', {}).get('sha256')
            if (not isinstance(image, str) or len(image) != 64
                    or image != event.get('frame', {}).get('original_sha256')):
                raise ReadAnomaly('Mini operation image provenance differs')
            self.observations[identity] = self.reference(rows[0])
        return self.observations[identity]

    def operation(self, row, upper=None):
        seq, event, _ = row
        if (not event.get('dispatch_observed') or event.get('command_alignment') != 'matched'
                or event.get('gaps')):
            raise ReadAnomaly('Mini operation has unconfirmed dispatch or observation')
        record = {'ref': self.reference(row), 'grade': 'execution_attempt',
                  'tool': deepcopy(event.get('tool')), 'before': self.observation(event['source']),
                  'after': self.observation(event['target']), 'effect_status': 'unknown',
                  'receipt': 'returned'}
        if upper is not None:
            tail = self.context.read("SELECT seq,id,payload FROM events WHERE seq>? AND seq<? AND "
                "json_extract(payload,'$.kind')='transition' AND json_extract(payload,'$.instruction')=? AND " + PASSIVE +
                ' ORDER BY seq DESC LIMIT 1', (seq, upper, event.get('instruction')))
            if tail:
                t = tail[0][1]
                if not t.get('dispatch_observed') or t.get('gaps') or t.get('command_alignment') != 'matched':
                    raise ReadAnomaly('Mini follow-up observation is incomplete')
                record['followup'] = {'ref': self.reference(tail[0]), 'after': self.observation(t['target'])}
        return record

    def error(self, row):
        record = self.operation(row)
        record.update(grade='execution_error_record', receipt='error', resolution='unknown')
        event = row[1]
        # The original full error/receipts remain immutable under the reference.
        # A large original is explicitly referenced, never sliced into a claim.
        error = event.get('error')
        if isinstance(error, str) and len(error.encode()) <= 240:
            record['error'] = error
        else:
            record['error_details'] = 'see original referenced event'
        signals = []
        for receipt in event.get('controller_receipts') or []:
            result = receipt.get('result') if isinstance(receipt, dict) else None
            if not isinstance(result, dict):
                continue
            value = result.get('error')
            nonempty = bool(value.strip()) if isinstance(value, str) else bool(value)
            if (nonempty or result.get('success') is False or result.get('status') in ('error', 'failed', 'failure')
                    or (type(result.get('returncode')) is int and result['returncode'] != 0)):
                signal = {k: result[k] for k in ('status', 'success', 'returncode', 'error') if k in result}
                if len(json.dumps(signal, ensure_ascii=False).encode()) <= 240:
                    signals.append(signal)
        if signals:
            record['failure_signal'] = signals[0]
        return record

    def review(self, row):
        note = parse_review(self.context.prose(row[1]))
        if note is None:
            return None
        try:
            self.context.validate_review_references(note, final=False)
        except ValueError:
            return None  # A bad model reference is not an original-journal corruption.
        record = {'ref': self.reference(row), 'grade': 'model_artifact_review',
                  'verification': unknown_checks(), 'report': note}
        # Every cited image has its own original-event reference in the packet.
        for check in note.get('checks', {}).values():
            observed = self.context.read('SELECT seq,id,payload FROM events WHERE seq=?', (check['ref'],))
            self.observation(observed[0][1]['id'])
        return record

    def artifact_state(self, review=None):
        state = {'verification': unknown_checks(), 'grade': 'unverified',
                 'review_schema': REVIEW_SCHEMA}
        if review:
            state['review_ref'] = review['ref']
            state['candidate_reported'] = review['report'].get('candidate')
            state['reported_checks'] = [key for key in CHECKS if key in review['report'].get('checks', {})]
        return state
