"""Optional data at a single actor boundary; never executable decisions.

The baseline has no provider. Graph memory and TaskViews use the same boundary,
without changing the system prompt, native history, tools, or actor transport.
"""
from __future__ import annotations

from copy import deepcopy
import json

from . import telemetry
from .native_history import context_size


def protocol_feedback(executions, user_response=None):
    """Project a native tool reply, not the complete execution evidence.

Full commands, controller returns, info, and observations stay in telemetry and
the experimental journals. A returned command does not certify its effect.
"""
    if user_response is not None:
        value = {'user_response': user_response}
    else:
        errors = [item['error'] for item in executions if item.get('error')]
        value = ({'error': errors[0]} if errors else
                 {'status': 'returned' if executions else 'unobserved'})
        if not errors:
            for execution in executions:
                for receipt in execution.get('controller_receipts') or []:
                    result = receipt.get('result') if isinstance(receipt, dict) else None
                    if not isinstance(result, dict):
                        continue
                    if result.get('error'):
                        value = {'error': result['error']}
                        break
                    if type(result.get('returncode')) is int and result['returncode'] != 0:
                        value = {'returncode': result['returncode']}
                        break
                    if result.get('status') in ('error', 'failed'):
                        value = {'status': result['status']}
                        break
                if value != {'status': 'returned'}:
                    break
    return json.dumps(value, ensure_ascii=False)


def _declared_native_actions(request):
    """Return bounded exact spellings from this request's tool, never aliases."""
    tools = request.get('tools')
    if not isinstance(tools, list) or len(tools) > 16:
        return None
    functions = [tool.get('function') for tool in tools if isinstance(tool, dict)
                 and isinstance(tool.get('function'), dict)
                 and tool['function'].get('name') == 'computer_use']
    if len(functions) != 1:
        return None
    parameters = functions[0].get('parameters', {})
    properties = parameters.get('properties', {}) if isinstance(parameters, dict) else {}
    action = properties.get('action', {}) if isinstance(properties, dict) else {}
    values = action.get('enum') if isinstance(action, dict) else None
    if (not isinstance(values, list) or not 1 <= len(values) <= 32
            or any(not isinstance(v, str) or not v or len(v) > 64 for v in values)
            or len(set(values)) != len(values)):
        return None
    return list(values)


def repair_messages(request, observed, error, *, role):
    """Keep a complete rejected native candidate and resolve its tool IDs.

Truncated or structurally malformed calls remain raw evidence, never valid
assistant/tool history. No rejected call is submitted to env.step.
"""
    result = deepcopy(request)
    if role == 'executor' and observed:
        choice = observed.get('choices', [{}])[0]
        message = choice.get('message', {})
        calls = message.get('tool_calls') or []
        valid = (isinstance(calls, list) and bool(calls) and
            all(isinstance(call, dict) and isinstance(call.get('id'), str) and call['id']
                and call.get('type') == 'function' and isinstance(call.get('function'), dict)
                and call['function'].get('name') == 'computer_use'
                and isinstance(call['function'].get('arguments'), str) for call in calls))
        ids = [call['id'] for call in calls] if valid else []
        valid = (valid and choice.get('finish_reason') in ('stop', 'tool_calls')
                 and len(ids) == len(set(ids)))
        if valid:
            result['messages'].append(deepcopy(message))
            result['messages'].extend({'role': 'tool', 'tool_call_id': identifier,
                'content': json.dumps({'error': str(error)}, ensure_ascii=False)} for identifier in ids)
    elif observed:
        choice = observed.get('choices', [{}])[0]
        message = choice.get('message', {})
        if (choice.get('finish_reason') == 'stop' and message.get('role') == 'assistant'
                and isinstance(message.get('content'), str) and not message.get('tool_calls')
                and not message.get('function_call')):
            # Complete adviser JSON remains the original assistant response,
            # including the rejected fields the reader must repair. Truncated
            # responses and executable calls remain raw evidence only.
            result['messages'].append(deepcopy(message))
    target = 'native tool call with all required parameters' if role == 'executor' else 'JSON object'
    feedback = (f'Your previous computer_use response could not execute: {error}.' if role == 'executor'
                else f'Your previous {role} JSON was rejected: {error}.')
    result['messages'].append({'role': 'user', 'content': [{'type': 'text', 'text':
        f'{feedback} Return a corrected complete {target}.'}]})
    if role == 'executor' and str(getattr(error, 'code', '')).startswith('unsupported_tool_action:'):
        actions = _declared_native_actions(request)
        if actions:
            result['messages'][-1]['content'][0]['text'] += (
                '\nUse an exact action identifier from the current computer_use schema (underscores matter): '
                + json.dumps(actions, ensure_ascii=False)
                + '. Python/PyAutoGUI method names and other aliases are invalid.')
    return result


def available_context_bytes(messages, *, label, contract):
    """Conservative pre-admission under the real actor input, not output tokens.

    UTF-8 bytes bound logical text characters. Only the serialized payload needs
    escaping reserve; applying that reserve to logical text wastes its capacity.
    A control character can occupy six JSON characters (\\u0000), so keep that
    worst case separate. supplement still checks the complete actual envelope.
    """
    payload, chars = context_size(messages)
    overhead = len(json.dumps({'type': 'text', 'text': label + '\n'}, ensure_ascii=False)) + 8
    payload_room = contract.context_max_payload_chars - payload - overhead
    text_room = min(contract.context_max_text_chars - chars - len(label) - 1,
                    contract.context_rough_text_token_budget * 4 - chars - len(label) - 1)
    return max(0, min(contract.taskviews_context_bytes, text_room, payload_room // 6))


def supplement(messages, text, *, label, contract):
    """Keep optional evidence out of durable actor history and preserve the goal.

Never truncate a JSON evidence packet or evict actor history to make it fit.
Provider output is a text value, never a replacement message/tool/command list.
"""
    if not text:
        return messages
    if not isinstance(text, str):
        raise TypeError('Optional actor context must be text')
    if len(text.encode('utf-8')) > contract.taskviews_context_bytes:
        telemetry.emit('optional_context_omitted', reason='provider_envelope', provider=label)
        return messages
    result = deepcopy(messages)
    block = {'type': 'text', 'text': label + '\n' + text}
    result[-1]['content'].append(block)
    payload, chars = context_size(result)
    if (payload > contract.context_max_payload_chars or chars > contract.context_max_text_chars
            or (chars + 3) // 4 > contract.context_rough_text_token_budget):
        telemetry.emit('optional_context_omitted', reason='actor_context_limit', provider=label)
        return messages
    return result


class ContextClient:
    """One supplier transport for all native arms; add only cached context."""
    def __init__(self, owner, transport):
        self.owner, self.transport = owner, transport
        self.last_timing = {}

    def create(self, **request):
        owner = self.owner
        prepared = dict(request)
        try:
            prepared['messages'] = supplement(request['messages'], owner.cached_context,
                label=owner.context_label, contract=owner.contract)
        except TypeError:
            telemetry.emit('optional_context_omitted', reason='invalid_provider_type', provider=owner.context_label)
            prepared['messages'] = request['messages']
        response = self.transport.create(**prepared)
        if owner.cached_context and prepared['messages'] is not request['messages']:
            owner.context_delivered()
        self.last_timing = self.transport.last_timing
        self.last_request_id = getattr(self.transport, 'last_request_id', None)
        return response

    def close(self):
        self.transport.close()
