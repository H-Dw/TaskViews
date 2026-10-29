"""Replay synthetic inputs against the preserved original v3 compactor."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest

from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.native_history import compact, policy

ORIGINAL = runpy.run_path(str(Path(__file__).parent / 'fixtures/native_history_v3.py'))['compact']


@pytest.mark.parametrize('count', [0, 3, 20, 30])
@pytest.mark.parametrize('reasoning_size', [0, 500, 4000])
@pytest.mark.parametrize('limit', [32000, 15000])
def test_original_v3_whole_turn_output_and_pairing_are_unchanged(count, reasoning_size, limit):
    turns = [[{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]},
              {'role': 'assistant', 'content': 'Public observation', 'reasoning_content': 'R' * reasoning_size,
               'tool_calls': [{'id': str(n), 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{}'}}]},
              {'role': 'tool', 'tool_call_id': str(n), 'content': 'Literal receipt'}] for n in range(count)]
    kwargs = dict(step=count+1, folded=0, contract=CUAContract(history_n=20, image_max=1, fold_size=1,
        context_max_text_chars=limit, context_reserve_chars=10000, context_rough_text_token_budget=12000),
        system={'role': 'system', 'content': 'System'},
        current={'role': 'user', 'content': [{'type': 'text', 'text': '当前观察'}]},
        instruction='Read the document', actions=['Recorded action'] * count)
    old_turns, old_kwargs = deepcopy(turns), deepcopy(kwargs)
    assert compact(turns, **kwargs) == ORIGINAL(old_turns, **old_kwargs)
    assert turns == old_turns and kwargs['current'] == old_kwargs['current']
    for turn in turns:
        assert turn[1]['tool_calls'][0]['id'] == turn[2]['tool_call_id']
        assert len(turn[1]['reasoning_content']) == reasoning_size
    assert policy(kwargs['contract'])['version'] == 'native_v3_whole_turns_v1'


def test_original_v3_rejects_oversized_current_frame_without_silent_truncation():
    kwargs = dict(step=1, folded=0, contract=CUAContract(context_max_text_chars=12000, context_reserve_chars=10000),
                  system={'role': 'system', 'content': 'S'},
                  current={'role': 'user', 'content': [{'type': 'text', 'text': 'X' * 20000}]})
    for implementation in (compact, ORIGINAL):
        with pytest.raises(ValueError, match='Current task/frame'):
            implementation([], **deepcopy(kwargs))
