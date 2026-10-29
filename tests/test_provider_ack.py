"""Provider smoke acknowledgement must not confuse punctuation with transport."""
import pytest

from scripts.probe_native_provider import acknowledgement, tool_reply_messages


@pytest.mark.parametrize('content,period', [('OK', False), ('OK.', True), ('  OK.\n', True)])
def test_completed_literal_acknowledgements_keep_the_observed_format(content, period):
    result = acknowledgement({'finish_reason': 'stop', 'message': {'content': content}})
    assert result == {'exact_ok': not period, 'terminal_period_normalized': period, 'finish_reason': 'stop'}


@pytest.mark.parametrize('content,finish,tools', [
    ('', 'stop', None), (None, 'stop', None), ('Okay', 'stop', None),
    ('OK?', 'stop', None), ('OK. extra', 'stop', None), ('OK..', 'stop', None),
    ('OK', 'length', None), ('OK', None, None), ('OK.', 'tool_calls', [{'id': 'call'}]),
    ('OK.', 'stop', [{'id': 'call'}]),
])
def test_non_acknowledgements_truncation_and_tool_calls_remain_rejected(content, finish, tools):
    with pytest.raises(ValueError, match='completed OK/OK.'):
        acknowledgement({'finish_reason': finish, 'message': {'content': content, 'tool_calls': tools}})


def test_deprecated_function_call_does_not_qualify_as_text_reply():
    with pytest.raises(ValueError):
        acknowledgement({'finish_reason': 'stop', 'message': {'content': 'OK.',
                        'function_call': {'name': 'unexpected'}}})


def test_tool_reply_preserves_the_original_assistant_and_exact_tool_id():
    from copy import deepcopy
    assistant = {'role': 'assistant', 'content': None, 'reasoning_content': 'original',
                 'tool_calls': [{'id': 'original-call', 'type': 'function',
                                 'function': {'name': 'computer_use', 'arguments': '{"action":"mouse_move"}'}}]}
    original = deepcopy(assistant)
    messages = tool_reply_messages(assistant)
    assert messages[1] is assistant and assistant == original
    assert messages[2]['role'] == 'tool'
    assert messages[2]['tool_call_id'] == 'original-call'


def test_reply_probe_uses_text_context_after_separate_full_size_vision_check():
    import json
    messages = tool_reply_messages({'role': 'assistant', 'content': None,
                                   'tool_calls': [{'id': 'call'}]})
    assert [m['role'] for m in messages] == ['user', 'assistant', 'tool', 'user']
    assert 'image_url' not in json.dumps(messages)
    assert all(isinstance(m['content'], str) for m in (messages[0], messages[2], messages[3]))
