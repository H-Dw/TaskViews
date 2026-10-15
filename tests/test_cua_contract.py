"""Contract, history and advisory regressions using real official code, offline."""
from copy import deepcopy
from io import BytesIO
import json
import time

from PIL import Image
import pytest

from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import StreamProtocolError
from ui_kobe.osworld.cua_contract import CUAContract, options_contract
from ui_kobe.osworld.kimi_native import KimiNativeAgent, native_schema, native_system, validate_native
from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
from ui_kobe.osworld.native_history import compact
from test_native_official_policy import candidate
from test_native_task_experiment import Transport, response


def png(size=(1373, 777)):
    out = BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


@pytest.mark.parametrize("mode", ["relative", "absolute"])
@pytest.mark.parametrize("size", [(1373, 777), (1920, 1080), (640, 480)])
def test_frame_schema_and_projection_use_same_official_metadata(mode, size):
    from mm_agents.qwen.actions import translate_tool_calls
    from mm_agents.qwen.images import process_screenshot
    from mm_agents.qwen.parser import ToolCall
    from mm_agents.qwen.prompts import build_tool_schema
    contract = CUAContract(coordinate_type=mode, model_screen_width=None, model_screen_height=None)
    frame = contract.process(png(size), 1)
    official = process_screenshot(png(size), coordinate_type=mode)
    assert frame.screenshot == official
    assert native_schema(frame) == build_tool_schema(coordinate_type=mode,
        model_width=official.model_width, model_height=official.model_height, enable_zoom=False)
    bound = frame.metadata["coordinate_bounds"]
    actions = [{"action": "left_click", "coordinate": [bound[0] / 2, bound[1] / 2]},
               {"action": "mouse_move", "coordinate": bound}]
    expected = translate_tool_calls([ToolCall(a, 0, 0) for a in actions], screenshot=official,
                                   coordinate_type=mode, enable_zoom=False)
    assert validate_native(candidate(actions), frame)[1] == expected
    assert str(size[0] - 1) in expected.commands[-1]


def test_units_are_declared_not_guessed_or_clamped():
    value = candidate([{"action": "left_click", "coordinate": [1342, 271]}])
    relative = CUAContract(coordinate_type="relative", model_screen_width=None, model_screen_height=None)
    frame = relative.process(png(), 1)
    with pytest.raises(StreamProtocolError) as error:
        validate_native(value, frame)
    assert error.value.code == "coordinate"
    assert "1342" in str(error.value) and "0..1000" in str(error.value)
    assert frame.screenshot.coordinate_type == "relative"
    absolute = CUAContract().process(png(), 1)
    assert len(validate_native(value, absolute)[1].commands) == 1
    with pytest.raises(StreamProtocolError):
        validate_native(candidate([{"action": "left_click", "coordinate": [1921, 271]}]), absolute)


@pytest.mark.parametrize("options,match", [
    ({"coordinate_type": "relative", "model_screen_width": 1920, "model_screen_height": None}, "both"),
    ({"coordinate_type": "auto"}, "declared"), ({"enable_zoom": True}, "Unsupported"),
    ({"terminal_status_judge": True}, "Unsupported"), ({"summary_folding": True}, "Unsupported"),
    ({"enable_thinking": False}, "Unsupported"), ({"made_up_option": True}, "Unknown"),
])
def test_misleading_or_inconsistent_options_rejected_before_api(options, match):
    with pytest.raises(ValueError, match=match):
        options_contract(options)


def test_explicit_relative_frame_keeps_pixels_and_uses_official_projection():
    contract, _, _, _ = options_contract({'coordinate_type': 'relative',
        'model_screen_width': 1920, 'model_screen_height': 1080})
    frame = contract.process(png((1920, 1080)), 1)
    assert frame.metadata['model_size'] == frame.metadata['original_size'] == [1920, 1080]
    assert frame.metadata['coordinate_bounds'] == [1000, 1000]
    _, batch = validate_native(candidate([{'action': 'mouse_move', 'coordinate': [950, 800]}]), frame)
    assert batch.commands == ['pyautogui.moveTo(1824, 864)']


def test_task_date_and_official_batch_guidance_are_shared():
    prompt = native_system(CUAContract().process(png(), 1), "2030-02-07")
    assert "2030-02-07" in prompt
    assert "depends on observing an intermediate result" in prompt
    assert "<tool_call>" not in prompt
    assert '1920x1080' in prompt


@pytest.mark.parametrize("parameters,commands,question", [
    ({"action": "terminate", "status": "success"}, ["DONE"], None),
    ({"action": "terminate", "status": "failure"}, ["FAIL"], None),
    ({"action": "wait"}, ["WAIT"], None),
    ({"action": "call_user", "text": "Which project?"}, [], "Which project?"),
])
def test_special_actions_remain_official_without_synthetic_endings(parameters, commands, question):
    frame = CUAContract().process(png(), 1)
    _, batch = validate_native(candidate([parameters]), frame)
    assert batch.commands == commands and batch.question == question
    if question:
        with pytest.raises(StreamProtocolError, match="only action"):
            validate_native(candidate([parameters, {"action": "wait"}]), frame)


@pytest.mark.parametrize("contract", [CUAContract(), CUAContract(coordinate_type="relative",
    model_screen_width=None, model_screen_height=None), CUAContract(model_screen_width=1280, model_screen_height=720,
    history_n=60, image_max=5, fold_size=3)])
def test_official_runner_arguments_honor_the_entire_frozen_contract(contract, tmp_path):
    from scripts.osworld_native_experiment import official_arguments
    values = official_arguments("059", tmp_path, contract=contract.snapshot())
    assert values[values.index("--coord") + 1] == contract.coordinate_type
    for name in ("history_n", "image_max", "fold_size", "tool_repair_retries",
                 "context_max_payload_chars", "context_max_text_chars", "context_rough_text_token_budget"):
        assert values[values.index("--" + name) + 1] == str(getattr(contract, name))
    if contract.model_screen_width is None:
        assert "--model_screen_width" not in values and "--model_screen_height" not in values
    else:
        assert values[values.index("--model_screen_width") + 1] == str(contract.model_screen_width)
        assert values[values.index("--model_screen_height") + 1] == str(contract.model_screen_height)
    assert "--no-terminal_status_judge" in values and "--no-endless_retry" in values


def build_agent(cls, monkeypatch, path, **options):
    monkeypatch.setenv("KIMI_API_KEY", "offline-only")
    monkeypatch.setenv("UI_KOBE_TELEMETRY_DIR", str(path))
    monkeypatch.setenv("UI_KOBE_TASK_ID", "contract-test")
    monkeypatch.setenv("UI_KOBE_GENERATION_PROFILE", "low-16k")
    agent = cls(model="kimi-k3", base_url="https://api.moonshot.ai/v1", temperature=1, max_tokens=16000, **options)
    agent.client.close()
    return agent


def test_frozen_contract_reaches_both_arms_and_rejects_runner_mismatch(monkeypatch, tmp_path):
    contract = CUAContract(model_screen_width=1280, model_screen_height=720, history_n=30,
                           advisory_repair_retries=1)
    monkeypatch.setenv("UI_KOBE_CUA_CONTRACT_JSON", json.dumps(contract.snapshot()))
    for cls in (KimiNativeAgent, KimiTaskViewsNativeAgent):
        agent = build_agent(cls, monkeypatch, tmp_path / cls.__name__, coordinate_type="absolute")
        try:
            assert agent.contract == contract
        finally:
            agent.close()
        with pytest.raises(ValueError, match="differs from frozen"):
            build_agent(cls, monkeypatch, tmp_path, model_screen_width=1920)


def test_two_arms_have_identical_acting_frame_schema_date_and_contract(monkeypatch, tmp_path):
    recorded = []
    for cls in (KimiNativeAgent, KimiTaskViewsNativeAgent):
        agent = build_agent(cls, monkeypatch, tmp_path / cls.__name__)
        actual = Transport()
        if cls is KimiNativeAgent:
            agent.client = actual
        else:
            agent.transport = agent.client.transport = actual
        agent.task_current_date = "2030-02-07"
        try:
            agent.predict("literal original goal", {"screenshot": png()})
            actor = next(r for r in actual.requests if r.get("tools"))
            recorded.append((actor, agent.frame.metadata, agent.contract.snapshot()))
            if cls is KimiTaskViewsNativeAgent:
                for request in actual.requests:
                    image = next(p for p in request["messages"][-1]["content"] if p["type"] == "image_url")
                    assert image == agent.frame.image
                controller = actual.requests[1]
                context = json.loads(controller["messages"][-1]["content"][0]["text"])
                allowed = context["role_evidence"]["consumer_allowed_anchors"]
                assert all("task" in v["anchors"] for v in allowed.values())
                assert agent.last_trace["taskviews"]["frame"]["model_size"] == [1920, 1080]
        finally:
            agent.close()
    first, second = recorded
    assert first[1:] == second[1:]
    assert first[0]["tools"] == second[0]["tools"]
    assert first[0]["messages"][0] == second[0]["messages"][0]


def test_specific_coordinate_repair_feedback_preserves_complete_native_history(monkeypatch, tmp_path):
    agent = build_agent(KimiNativeAgent, monkeypatch, tmp_path,
                        coordinate_type="relative", model_screen_width=None, model_screen_height=None)
    class RejectOnce(Transport):
        def create(self, **request):
            self.requests.append(deepcopy(request))
            return candidate([{"action": "left_click", "coordinate": [1342, 271] if len(self.requests) == 1 else [699, 251]}])
    actual = agent.client = RejectOnce()
    try:
        _, actions = agent.predict("literal goal", {"screenshot": png((1920, 1080))})
        assert len(actions) == 1 and len(actual.requests) == 2
        feedback = actual.requests[1]["messages"][-1]["content"][-1]["text"]
        assert "1342" in feedback and "0..1000" in feedback and 'error_code' not in feedback
        history = actual.requests[1]['messages']
        assert history[-3]['role'] == 'assistant' and history[-2]['role'] == 'tool'
        assert history[-3]['tool_calls'][0]['id'] == history[-2]['tool_call_id']
        assert json.loads(history[-2]['content'])['error'] in feedback
        assert actual.requests[0]["deadline"] == actual.requests[1]["deadline"]
    finally:
        agent.close()


@pytest.mark.parametrize("bad_role", ["perception", "view_controller", "planner", "verifier"])
def test_business_schema_repair_inside_bounded_role_loop(monkeypatch, tmp_path, bad_role):
    agent = build_agent(KimiTaskViewsNativeAgent, monkeypatch, tmp_path)
    class InvalidOnce(Transport):
        failed = False
        def create(self, **request):
            prompt = request["messages"][0]["content"]
            role = ("executor" if request.get("tools") else "perception" if "Extract visible evidence" in prompt
                    else "planner" if "subordinate task planner" in prompt
                    else "verifier" if "subordinate visual verifier" in prompt else "view_controller")
            if role == bad_role and not self.failed:
                self.failed = True
                self.requests.append(deepcopy(request))
                return response({"content": '{}'})
            if role == "view_controller":
                self.requests.append(deepcopy(request))
                return response({"content": json.dumps({"stage": "observe", "needs": [{"id": c, "consumer": c,
                    "purpose": "current task", "anchors": ["task"], "focus_predicates": ["*"], "max_hops": 1}
                    for c in ("executor", "planner", "verifier")]})})
            if role in {"planner", "verifier"}:
                self.requests.append(deepcopy(request))
                return response({"content": json.dumps({"advice": "Inspect", "needed_evidence": []}
                    if role == "planner" else {"assessment": "unknown", "quotes": [], "gaps": []})})
            return super().create(**request)
    actual = InvalidOnce()
    agent.transport = agent.client.transport = actual
    try:
        _, commands = agent.predict("goal", {"screenshot": png()})
        assert commands and agent.step_ledger.repair_counts == {"executor": 0, "advisory": 0}
        assert agent.advisory_ledger.repair_counts == {"executor": 0, "advisory": 1}
        assert "advisory_failure" not in agent.last_trace["taskviews"]
        assert any("Invalid " + bad_role in str(r["messages"][-1]["content"]) for r in actual.requests)
    finally:
        agent.close()


def test_advisory_exhaustion_leaves_actor_repair_pool_and_original_task(monkeypatch, tmp_path):
    agent = build_agent(KimiTaskViewsNativeAgent, monkeypatch, tmp_path)
    class ExhaustAdviser(Transport):
        actor_count = 0
        def create(self, **request):
            self.requests.append(deepcopy(request))
            if not request.get("tools"):
                return response({"content": '{}'})
            self.actor_count += 1
            return candidate([{"action": "mouse_move", "coordinate": [1921, 100] if self.actor_count < 3 else [100, 100]}])
    actual = ExhaustAdviser()
    agent.transport = agent.client.transport = actual
    try:
        _, commands = agent.predict("literal goal", {"screenshot": png()})
        assert len(actual.requests) == 6 and len(commands) == 1
        assert agent.step_ledger.repair_counts == {"executor": 2, "advisory": 0}
        assert agent.advisory_ledger.repair_counts == {"executor": 0, "advisory": 2}
        actor = actual.requests[-1]
        assert 'literal goal' in actor['messages'][1]['content'][-1]['text']
        assert not any('advisory_status' in json.dumps(r['messages']) for r in actual.requests if r.get('tools'))
        assert "advisory_failure" in agent.last_trace["taskviews"]
        assert len({r["deadline"] for r in actual.requests if r.get("tools")}) == 1
    finally:
        agent.close()


def test_native_folding_uses_official_schedule_and_keeps_tool_pairs():
    from mm_agents.qwen.history import folded_prefix
    contract = CUAContract(history_n=50, image_max=2, fold_size=2)
    turns = []
    originals = []
    for step in range(1, 6):
        assistant = candidate([{"action": "wait"}]).model_dump()["choices"][0]["message"]
        assistant["tool_calls"][0]["id"] = str(step)
        originals.append(deepcopy(assistant))
        turns.append([{"role": "user", "content": [{"type": "text", "text": "goal"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
                      assistant, {"role": "tool", "tool_call_id": str(step), "content": 'actual receipt'}])
    folded, omitted, _ = compact(turns, step=6, folded=0, contract=contract,
                                system={"role": "system", "content": "rules"}, current={"role": "user", "content": []})
    assert folded == folded_prefix(6, 0, 2, 2) and omitted == 0
    assert sum(p["type"] == "image_url" for turn in turns for p in turn[0]["content"]) == 1
    assert [turn[1] for turn in turns] == originals
    contract = CUAContract(history_n=2)
    _, removed, _ = compact(turns, step=6, folded=folded, contract=contract,
                           system={"role": "system", "content": "rules"}, current={"role": "user", "content": []})
    assert removed == 4 and turns[0][1]["tool_calls"][0]["id"] == turns[0][2]["tool_call_id"] == "5"


def test_advisers_cannot_spend_actor_output_or_refresh_deadline():
    ledger = StepLedger(__import__('ui_kobe.api.kimi', fromlist=['generation_profile']).generation_profile(),
                        time.monotonic() + 60, lambda *a, **k: None)
    deadline = ledger.deadline
    for i in range(4):
        ledger.reserve(str(i), "perception", 4000)
        ledger.settle(str(i), None)
    assert not ledger.regenerate("perception", 15)
    assert ledger.allowance("executor") == 16000
    assert ledger.regenerate("executor", 15) and ledger.deadline == deadline
