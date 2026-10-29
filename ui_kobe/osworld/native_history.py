"""Native-ID history using the official image folding schedule and whole turns."""
from __future__ import annotations

import json

POLICY = 'native_v3_whole_turns_v1'


def policy(contract):
    """Name the original v3 behavior without silently changing caller limits.

    The same compactor is used for baseline and Mini. Keeping complete turns
    preserves tool IDs and provider reasoning; optional views never evict them.
    """
    return {'version': POLICY, 'unit': 'whole_native_turn', 'reasoning': 'count_and_preserve',
            **{key: getattr(contract, key) for key in (
                'history_n', 'image_max', 'fold_size', 'context_max_payload_chars',
                'context_max_text_chars', 'context_rough_text_token_budget',
                'context_reserve_chars', 'enable_context_rescue')}}


def context_size(messages):
    # Official context helpers understand XML text arrays. Native messages also
    # carry reasoning, function arguments and tool replies, all of which count.
    text = 0
    for message in messages:
        for key, value in message.items():
            if key == "content" and isinstance(value, list):
                text += sum(len(p.get("text", "")) for p in value if p.get("type") == "text")
            elif key in {"content", "reasoning_content", "reasoning", "reasoning_details", "tool_calls"} and value is not None:
                text += len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False))
    return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":"))), text


def compact(turns, *, step, folded, contract, system, current, instruction=None, actions=()):
    from mm_agents.qwen.history import COLLAPSED_SCREENSHOT_TEXT, folded_prefix
    folded = folded_prefix(step, folded, contract.image_max, contract.fold_size)
    omitted = max(0, len(turns) - max(0, contract.history_n - 1))
    if omitted:
        del turns[:omitted]
    first_step = step - len(turns)
    for index, turn in enumerate(turns):
        if first_step + index <= folded:
            turn[0]["content"] = [part if part.get("type") != "image_url" else
                {"type": "text", "text": COLLAPSED_SCREENSHOT_TEXT} for part in turn[0]["content"]]
    while True:
        if instruction is not None:
            from mm_agents.qwen.history import previous_actions_text
            from mm_agents.qwen.prompts import build_instruction_prompt
            first = turns[0][0] if turns else current
            # Match the upstream placement: original task/older actions on the
            # first retained observation, not repeated on every new frame.
            prefix = 'Generate the next move from the screenshot, task, and prior actions.\n\nTask: '
            first['content'] = [p for p in first['content'] if not p.get('text', '').startswith(prefix)]
            first['content'].append({'type': 'text',
                'text': build_instruction_prompt(instruction, previous_actions_text(list(actions), step - len(turns)))})
        messages = [system, *(message for turn in turns for message in turn), current]
        payload, text = context_size(messages)
        too_large = (payload + contract.context_reserve_chars > contract.context_max_payload_chars or
                     text + contract.context_reserve_chars > contract.context_max_text_chars or
                     (text + contract.context_reserve_chars + 3) // 4 > contract.context_rough_text_token_budget)
        if not too_large:
            return folded, omitted, text
        if not contract.enable_context_rescue or not turns:
            raise ValueError("Current task/frame exceeds the declared native context limits")
        # Drop assistant/tool replies together. Never strip reasoning or create
        # an orphan tool_call_id; no model-generated summary or extra API call.
        turns.pop(0)
        omitted += 1
