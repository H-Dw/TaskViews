"""Mini-only report recovery and whole-turn admission; no new model role/pool."""
from copy import deepcopy
import hashlib

from kobe_views.artifact_view import ReviewError
from ui_kobe.api.kimi_stream import StreamProtocolError
from . import telemetry
from .actor_context import repair_messages
from .checkpoints import ReadAnomaly
from .native_history import context_size

TASK_PREFIX = 'Generate the next move from the screenshot, task, and prior actions.\n\nTask: '


def check_tool_pairs(messages):
    """Validate adjacency-scoped IDs; repeated IDs in separate turns are legal."""
    pending = set()
    for message in messages:
        if message.get('role') == 'tool':
            identifier = message.get('tool_call_id')
            if identifier not in pending:
                raise ReadAnomaly('Mini repair admission found an orphan or duplicate tool reply')
            pending.remove(identifier)
            continue
        if pending:
            raise ReadAnomaly('Mini repair admission found an unresolved native tool call')
        if message.get('role') == 'assistant':
            calls = message.get('tool_calls') or []
            ids = [call.get('id') for call in calls]
            if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
                raise ReadAnomaly('Mini repair admission found invalid native tool IDs')
            pending.update(ids)
    if pending:
        raise ReadAnomaly('Mini repair admission found unresolved native tool IDs')


def _actual_size(messages, context, label):
    # Match ContextClient.supplement's exact envelope, including JSON escaping.
    actual = deepcopy(messages)
    if context:
        actual[-1]['content'].append({'type': 'text', 'text': label + '\n' + context})
    return context_size(actual)


def admit_request(request, turn_lengths, *, contract, context='', label=''):
    """Remove only complete old native turns, never the current repair suffix.

    turn_lengths come from the common actor's retained self.turns, not inferred
    from prose. The suffix starts with the original current observation and
    includes every complete native rejected message/tool pair and feedback.
    Durable actor history and raw response evidence are never edited here.
    """
    result = deepcopy(request)
    messages = result['messages']
    if (not messages or messages[0].get('role') != 'system'
            or any(type(n) is not int or n < 2 for n in turn_lengths)):
        raise ReadAnomaly('Mini repair admission requires the original system and whole native turns')
    position, turns = 1, []
    for length in turn_lengths:
        turn = messages[position:position+length]
        if len(turn) != length or turn[0].get('role') != 'user' or turn[1].get('role') != 'assistant':
            raise ReadAnomaly('Mini repair admission turn boundary differs from native history')
        check_tool_pairs(turn)
        turns.append(turn)
        position += length
    suffix = messages[position:]
    if (not suffix or suffix[0].get('role') != 'user' or
            not any(p.get('type') == 'image_url' for p in suffix[0].get('content', []))):
        raise ReadAnomaly('Mini repair admission lost the original current observation')
    check_tool_pairs(suffix)
    task_parts = [part for message in messages if message.get('role') == 'user'
                  and isinstance(message.get('content'), list) for part in message['content']
                  if part.get('text', '').startswith(TASK_PREFIX)]
    if len(task_parts) != 1:
        raise ReadAnomaly('Mini repair admission requires exactly one original task instruction')
    task = deepcopy(task_parts[0])
    if context and len(context.encode('utf-8')) > contract.taskviews_context_bytes:
        raise ReadAnomaly('Mini cached evidence exceeds its declared optional envelope')
    before = _actual_size(messages, context, label)
    removed = 0
    while True:
        actual = [messages[0], *(m for turn in turns for m in turn), *suffix]
        payload, chars = _actual_size(actual, context, label)
        if (payload <= contract.context_max_payload_chars and chars <= contract.context_max_text_chars
                and (chars + 3) // 4 <= contract.context_rough_text_token_budget):
            check_tool_pairs(actual)
            result['messages'] = actual
            return result, [len(turn) for turn in turns], {
                'old_turns_removed': removed, 'before_payload_chars': before[0], 'before_text_chars': before[1],
                'actual_payload_chars': payload, 'actual_text_chars': chars,
                'task_sha256': hashlib.sha256(task['text'].encode()).hexdigest(),
                'current_observation_preserved': True, 'native_tool_pairs_preserved': True}
        if not contract.enable_context_rescue or not turns:
            telemetry.emit('mini_repair_admission_failed', actual_payload_chars=payload, actual_text_chars=chars,
                           old_turns_removed=removed, action_executed=False)
            raise ReadAnomaly('Mini repair input exceeds declared limits after complete old-turn admission; '
                              'required current input and native pairs cannot be truncated')
        discarded = turns.pop(0)
        removed += 1
        # The upstream task prefix is attached to the first retained observation.
        # Move that exact generated part if its complete old turn was removed.
        if task in discarded[0]['content']:
            target = turns[0][0] if turns else suffix[0]
            target['content'].append(deepcopy(task))


def report_feedback(request, error):
    """Do not replay rejected reasoning/content/tools or invent tool receipts.

    The full response remains in original transport telemetry. Omitting BOTH
    the rejected assistant call and its tool replies creates no orphan IDs.
    """
    result = deepcopy(request)
    detail = str(error)
    if len(detail.encode('utf-8')) > 1200:
        detail = error.code + ': use the fields and bounds in current.artifact.review_schema'
    text = ('Mini auxiliary report rejected; the previous success was NOT dispatched. '
            + detail + '. Correct assistant.content per current.artifact.review_schema, '
            'and return a complete native tool call. If evidence is missing, inspect before success. '
            'Unknown stays unknown; never invent facts or references.')
    result['messages'].append({'role': 'user', 'content': [{'type': 'text', 'text': text}]})
    return result


def generate_candidate(owner, transport, role, deadline, request, validator):
    """Use the original actor ledger/deadline for both distinct error paths."""
    candidate, parent = 1, None
    lengths = [len(turn) for turn in owner.turns]
    trace = {'report_rejections': 0, 'native_rejections': 0, 'admissions': []}
    owner.mini_recovery_trace = trace
    ledger = owner.step_ledger
    while True:
        request, lengths, admission = admit_request(request, lengths, contract=owner.contract,
            context=owner.cached_context, label=owner.context_label)
        trace['admissions'].append(admission)
        telemetry.emit('mini_repair_admission', generation_attempt=candidate, **admission)
        payload = deepcopy(request)
        payload.update(owner.generation_fields(ledger, role))
        observed = None
        try:
            response = transport.create(deadline=deadline, step_ledger=ledger, budget_role=role,
                generation_attempt=candidate, parent_request_id=parent, **payload)
            observed = response.model_dump()
            return response, validator(response)
        except ReviewError as exc:
            parent = getattr(transport, 'last_request_id', None)
            trace['report_rejections'] += 1
            telemetry.emit('mini_report_rejected', request_id=parent, generation_attempt=candidate,
                           failure=exc.code, recovery='mini_report_feedback', action_executed=False)
            if candidate > owner.contract.tool_repair_retries or not ledger.regenerate(role, owner.budget.connect_s):
                raise
            request = report_feedback(request, exc)
            candidate += 1
            telemetry.emit('mini_report_regeneration', generation_attempt=candidate, parent_request_id=parent,
                           reason=exc.code, action_executed=False, step_tokens=ledger.snapshot())
        except StreamProtocolError as exc:
            parent = getattr(exc, 'request_id', getattr(transport, 'last_request_id', None))
            trace['native_rejections'] += 1
            telemetry.emit('candidate_rejected', role=role, generation_attempt=candidate,
                request_id=parent, error_code=exc.code, error=str(exc), action_executed=False)
            if (not exc.retryable or candidate > owner.contract.tool_repair_retries
                    or not ledger.regenerate(role, owner.budget.connect_s)):
                exc.retryable = False
                raise
            request = repair_messages(request, observed, exc, role=role,
                compact_executor_feedback=bool(getattr(owner, 'feedback_v10', False)),
                declared_parameter_feedback=bool(getattr(owner, 'native_parameter_repair_feedback', False)))
            candidate += 1
            telemetry.emit('semantic_regeneration', role=role, generation_attempt=candidate,
                parent_request_id=parent, reason=exc.code, action_executed=False, step_tokens=ledger.snapshot())
