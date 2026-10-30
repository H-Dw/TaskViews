"""Optional same-actor knowledge turn. Never compile or dispatch a GUI command."""
from copy import deepcopy
import json

from kobe_views import decision_flow as flow
from kobe_views.model import dumps
from ui_kobe.api.kimi_stream import StreamProtocolError
from . import telemetry


class KeyboardLookup:
    def __init__(self, owner):
        self.owner, self.count = owner, 0

    def configure(self, request):
        result = deepcopy(request)
        result['tools'] = [t for t in result['tools'] if t.get('function', {}).get('name') != flow.TOOL]
        if self.count < flow.MAX_LOOKUPS:
            result['tools'].append(flow.tool_schema())
        return result

    def consume(self, response, request):
        data = response.model_dump()
        choice = data['choices'][0]
        message = choice['message']
        calls = message.get('tool_calls') or []
        if not any(isinstance(c, dict) and isinstance(c.get('function'), dict)
                   and c['function'].get('name') == flow.TOOL for c in calls):
            return None
        try:
            if (choice['finish_reason'] not in ('stop', 'tool_calls') or len(calls) != 1
                    or calls[0].get('type') != 'function' or not isinstance(calls[0].get('id'), str)
                    or not calls[0]['id'] or self.count >= flow.MAX_LOOKUPS):
                raise ValueError('keyboard_lookup must be one complete call, alone, at most once per decision; no GUI batch')
            query = flow.validate_query(json.loads(calls[0]['function']['arguments']))
        except (ValueError, TypeError, KeyError) as exc:
            raise StreamProtocolError(str(exc), code='keyboard_lookup_protocol', observed_response=data, retryable=True) from exc
        owner = self.owner
        journal = owner.mini_context.journal()
        record = journal.append('knowledge_query', instruction=journal.task_input['instruction'],
            step=owner.total_steps, source=journal.current['id'], query=query,
            tool_call_id=calls[0]['id'], request_id=getattr(owner.client, 'last_request_id', None),
            interpretation='public_strategy_proposal_not_execution')
        self.count += 1
        # No instruction facts are duplicated in the tool result. The new card
        # replaces the prefetched selection inside the SAME 3000-byte envelope.
        result = deepcopy(request)
        result['messages'].append(deepcopy(message))
        reply = {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': ''}
        result['messages'].append(reply)
        result['messages'].append({'role': 'user', 'content': [{'type': 'text', 'text':
            'Use the refreshed Views only for the requested gap; Keyboard is optional. '
            'Now ground native GUI parameters in the current image. Do not repeat the lookup.'}]})
        # Reserve the largest fixed reply status before computing actual room.
        reply['content'] = dumps({'query_ref': record['seq'], 'status': 'omitted_budget'})
        owner.actor_input_messages = result['messages']
        owner.cached_context = owner.mini_context.context(journal.task_input['instruction'], knowledge_query=record)
        status = ('included' if owner.mini_context.guidance_records else
                  'omitted_budget' if owner.mini_context.guidance_selection['groups'] else 'no_match')
        reply['content'] = dumps({'query_ref': record['seq'], 'status': status})
        evidence = {'query_ref': record['seq'], 'status': status, 'frame_id': owner.frame.metadata['frame_id'],
            'packet_sha256': owner.mini_context.trace.get('packet_sha256'), 'gui_dispatched': False,
            'interpretation': 'reference_delivery_not_action_or_success'}
        journal.append('knowledge_result', instruction=journal.task_input['instruction'], step=owner.total_steps,
                       source=journal.current['id'], **evidence)
        telemetry.emit('mini_keyboard_lookup', **evidence)
        return self.configure(result), evidence
