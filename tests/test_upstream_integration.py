"""Exercise real upstream methods; replace only unavailable models/devices/frameworks."""
import importlib
import json
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from kobe_views import RuntimeBridge, UIKobeAdapter

ROOT = Path(__file__).parents[1]


def graph_fixture():
    return json.loads((ROOT / "examples/graphs/settings.json").read_text(encoding="utf-8"))


@pytest.fixture
def translator_module(monkeypatch):
    # AITK is an optional external framework. Only its base-class import is stubbed.
    aitk = ModuleType("aitk")
    translators = ModuleType("aitk.translators")
    base = ModuleType("aitk.translators.base")
    base.BaseTranslator = type("BaseTranslator", (), {})
    monkeypatch.setitem(sys.modules, "aitk", aitk)
    monkeypatch.setitem(sys.modules, "aitk.translators", translators)
    monkeypatch.setitem(sys.modules, "aitk.translators.base", base)
    module = importlib.import_module("aitk_files.ui_kobe_v2")
    yield module


def test_real_graph_manager_live_snapshot_and_save_load(tmp_path):
    from ui_kobe.utils.graph_manager import GraphManager
    manager = GraphManager()
    manager.graph.add_node("one", page_description="Home", state_schema={}, last_detail_snapshot={})
    manager.graph.add_node("two", page_description="Settings", state_schema={}, last_detail_snapshot={})
    manager.add_edge("one", "two", {"action": "tap"}, instruction="settings")
    first = manager.projection_snapshot("demo")
    manager.graph.nodes["two"]["last_detail_snapshot"] = {"saved": True}
    assert manager.projection_snapshot("demo").revision != first.revision
    path = tmp_path / "demo.json"
    manager.save_graph(path)
    assert UIKobeAdapter().convert(json.loads(path.read_text()), "demo").revision == manager.projection_snapshot("demo").revision


def test_runtime_loader_keeps_controls_and_edge_trust(translator_module, tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(graph_fixture()), encoding="utf-8")
    graph, _ = translator_module._load_graph_from_json(path)
    assert graph.nodes["settings"]["interactable_elements"][0]["id"] == "toggle"
    assert graph["home"]["unreachable"]["grade"] == "contradicted"
    assert graph["home"]["unreachable"]["failed"] is True


@pytest.mark.parametrize("enabled", [False, True])
def test_real_translator_loop_delivers_views_and_resets(translator_module, monkeypatch, tmp_path, enabled):
    mod = translator_module
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(graph_fixture()), encoding="utf-8")
    graph, _ = mod._load_graph_from_json(path)
    # Skip credential-dependent initialization, exercise actual _step and consumers.
    runtime = mod.UIKobeV2Translator.__new__(mod.UIKobeV2Translator)
    runtime._projection = RuntimeBridge({"enabled": enabled, "max_tokens": 40000})
    runtime._reset_task_state()
    runtime._current_graph = graph
    runtime._app_name = "demo"
    runtime._app_opened = True
    runtime.model_client, runtime.model_name = object(), "offline-model"
    prompts, grounded = [], []

    def identify(activity, screenshot):
        runtime._projection_detail = {"ready": True}
        runtime._projection_elements = [{"description": "Settings", "position": "top right"}]
        return "home", "Home"

    monkeypatch.setattr(runtime, "_identify_node", identify)

    def chat(client, **kwargs):
        content = kwargs["messages"][0]["content"]
        prompt = content if isinstance(content, str) else content[0]["text"]
        prompts.append(prompt)
        response = '{"choice":"B","instruction":"Open menu"}' if "runtime.decide" in prompt or "Which action" in prompt else "nothing"
        # DECIDE parser accepts this response; record parser can also consume it
        # without involving any external model.
        if len(prompts) == 2:
            response = '{"choice":"B","instruction":"Open menu"}'
        yield 0, response, False

    monkeypatch.setattr(mod, "_chat_completion_content", chat)

    def predict(*args, **kwargs):
        grounded.append(kwargs.get("projection_context", ""))
        return {"action": "tap", "x": 20, "y": 20}, "menu | tap"

    monkeypatch.setattr(mod, "predict_next_action", predict)
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    response = json.loads(runtime._step("Open notification settings", {
        "screenshot": "synthetic-frame", "activity": "com.demo.app/.Home", "package": "com.demo.app"}, {"actions": []}))
    assert response["aitk_action"]["action"] == "tap"
    assert len(prompts) == 2
    assert bool(grounded[0]) is enabled
    if enabled:
        assert '"kind":"relation"' in prompts[0]
        assert '"kind":"planning"' in prompts[1]
        assert '"kind":"verification"' in prompts[1]
        assert '"kind":"grounding"' in grounded[0]
        assert runtime._projection.observation_id == "step:1"
        assert runtime._projection.recent_action["action"] == "tap"
        runtime._generate_answer("Check task result")
        assert '"kind":"verification"' in prompts[-1]
        runtime._plan_free_action("Open settings", "synthetic-frame", "unknown page", [])
        assert '"kind":"planning"' in prompts[-1]
    runtime._reset_task_state()
    assert not runtime._projection.service.store.read().nodes
    assert not runtime._projection.recent_action


def test_existing_vlm_functions_accept_and_include_context(monkeypatch):
    from ui_kobe.utils import vlm_utils as vlm
    captured = []
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="Open settings"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vlm, "_resize_screenshot", lambda screenshot: (screenshot, 1080, 1920, 1))
    monkeypatch.setattr(vlm, "_build_image_message", lambda screenshot: {"type": "text", "text": "synthetic frame"})
    assert vlm.plan_next_action(client, "frame", "Home", [], projection_context="PROJECTION_MARKER") == "Open settings"
    assert "PROJECTION_MARKER" in captured[-1]["messages"][0]["content"][0]["text"]
    monkeypatch.setattr(vlm, "_parse_agent_response", lambda response: ({"action": "wait"}, "waiting", "wait"))
    action, _ = vlm.predict_next_action(client, "frame", "Open settings", projection_context="GROUNDING_MARKER")
    assert action["action"] == "wait"
    assert "GROUNDING_MARKER" in captured[-1]["messages"][1]["content"][0]["text"]


def test_explorer_executes_one_step_with_projection_hooks(monkeypatch, tmp_path):
    from ui_kobe import kobe as mod
    monkeypatch.setattr(mod, "make_client", lambda config: (None, "offline-model"))
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    executed, contexts = [], []
    controller = SimpleNamespace(
        w=1080, h=1920,
        get_state=lambda: {"activity": "com.demo.app/.Main", "screenshot": "frame", "package": "com.demo.app"},
        exe_action=lambda action: executed.append(action))
    explorer = mod.Kobe(controller, "demo", "com.demo.app", logging.getLogger("test"),
                        graph_dir=tmp_path, max_steps=1, projection_config={"enabled": True, "max_tokens": 40000})
    explorer.graph.graph.add_node("home", page_description="Home", last_detail_snapshot={"ready": True}, state_schema={})
    explorer.graph.graph.add_node("menu", page_description="Settings menu", last_detail_snapshot={}, state_schema={})
    identifications = iter(["home", "menu"])
    def identify(*args, **kwargs):
        nid = next(identifications)
        explorer.graph.latest_projection_observation = (nid, hash("frame"), {"ready": True}, [])
        return nid
    monkeypatch.setattr(explorer.graph, "identify_state", identify)
    monkeypatch.setattr(explorer.graph, "normalize_all_edges", lambda: None)
    monkeypatch.setattr(explorer.graph, "maybe_normalize_node_edges", lambda nid: None)
    def plan(**kwargs):
        contexts.append(kwargs["projection_context"])
        return "Open settings"
    def action(**kwargs):
        contexts.append(kwargs["projection_context"])
        return {"action": "tap", "x": 20, "y": 30}, "Open settings"
    monkeypatch.setattr(mod, "plan_next_action", plan)
    monkeypatch.setattr(mod, "predict_next_action", action)
    explorer.explore()
    assert executed == [{"action": "tap", "x": 20, "y": 30}]
    assert '"kind":"planning"' in contexts[0] and '"kind":"relation"' in contexts[0]
    assert '"kind":"grounding"' in contexts[1]
    assert explorer.graph.graph.has_edge("home", "menu")
    assert (tmp_path / "demo/demo.json").exists()


def test_android_world_config_reaches_same_runtime(translator_module, monkeypatch, tmp_path):
    # Android World is an optional external framework; replace its import shells.
    names = ["android_world", "android_world.agents", "android_world.agents.base_agent",
             "android_world.env", "android_world.env.adb_utils", "android_world.env.interface", "android_world.env.json_action"]
    modules = {name: ModuleType(name) for name in names}
    class Base:
        def __init__(self, env, **kwargs):
            self.env = env
    modules["android_world.agents.base_agent"].EnvironmentInteractingAgent = Base
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "aitk.translators.ui_kobe_v2", translator_module)
    aw = importlib.import_module("aw_files.ui_kobe_aw_agent")
    received = []
    monkeypatch.setattr(aw, "UIKobeV2Translator", lambda **kwargs: received.append(kwargs))
    config = tmp_path / "config.yaml"
    config.write_text("task_views:\n  enabled: true\n  max_tokens: 16000\n", encoding="utf-8")
    aw.UIKobeAndroidWorldAgent.from_config(object(), config)
    assert received[0]["projection_config"] == {"enabled": True, "max_tokens": 16000}


def test_projection_core_import_needs_no_site_packages():
    import subprocess
    result = subprocess.run([sys.executable, "-S", "-c", "import kobe_views; import ui_kobe; print('ok')"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ok"
