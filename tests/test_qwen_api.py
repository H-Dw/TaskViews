import json
from pathlib import Path
import sys

import httpx
from openai import OpenAI
import pytest

from ui_kobe.api import client_from_config
from ui_kobe.api.qwen import QwenClient, QwenConfig, QwenRequestError
from ui_kobe.api.discover import discover
from ui_kobe.osworld.process import AgentProcess
from ui_kobe.utils import make_client


def completion():
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "qwen3.6-35b-a3b",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 1, "total_tokens": 18}}


def test_qwen_uses_exact_root_route_and_configured_thinking_parameter():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    sdk = OpenAI(api_key="test", base_url="https://example.invalid", max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    with QwenClient(QwenConfig(base_url="https://example.invalid"), sdk_client=sdk) as client:
        client.chat.completions.create(messages=[{"role": "user", "content": "hi"}])
        assert str(requests[0].url) == "https://example.invalid/chat/completions"
        payload = json.loads(requests[0].content)
        assert payload["model"] == "qwen3.6-35b-a3b"
        assert payload["enable_thinking"] is False
        client.create(model="qwen-cua", messages=[], extra_body={"enable_thinking": True})
        assert json.loads(requests[1].content)["model"] == "qwen-cua"
        assert json.loads(requests[1].content)["enable_thinking"] is True


def test_gateway_http_200_error_is_not_a_successful_completion():
    sdk = OpenAI(api_key="test", base_url="https://example.invalid", max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(
                     lambda _: httpx.Response(200, json={"success": False, "code": 500, "message": "private"}))))
    with QwenClient(QwenConfig(base_url="https://example.invalid"), sdk_client=sdk) as client:
        with pytest.raises(QwenRequestError, match="invalid_completion") as error:
            client.create(messages=[])
        assert error.value.provider_code == "500"
        assert error.value.attempts == 1
        assert "private" not in str(error.value)


def test_qwen_does_not_fall_back_to_glm_secret(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("GLM_API_KEY", "unrelated-secret")
    with pytest.raises(ValueError, match="QWEN_API_KEY"):
        client_from_config({"provider": "qwen", "base_url": "https://example.invalid"})


def test_existing_factory_routes_qwen_without_reading_glm_key(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "test-qwen-key")
    client, model = make_client({"provider": "qwen", "base_url": "https://example.invalid"})
    try:
        assert isinstance(client, QwenClient)
        assert client._sdk.api_key == "test-qwen-key"
        assert model == "qwen3.6-35b-a3b"
    finally:
        client.close()


def test_discovery_distinguishes_verified_subset_from_unavailable_catalog(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "probe-test-key")

    def handler(request):
        assert request.headers["authorization"] == "Bearer probe-test-key"
        if request.method == "GET":
            return httpx.Response(405, json={"status": 405})
        model = json.loads(request.content)["model"]
        if model == "qwen-good":
            return httpx.Response(200, json=completion())
        return httpx.Response(200, json={"success": False, "message": "model_not_found"})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    result = discover("https://example.invalid", probe_models=["qwen-good", "qwen-bad"])
    assert result["verified_models"] == ["qwen-good"]
    assert result["catalog_complete"] is False
    assert "model_ids" not in result
    assert result["model_tests"][1]["verified"] is False


def test_qwen_subprocess_model_override_and_runtime_handshake(tmp_path, monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "offline-test-key")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    config = tmp_path / "qwen.json"
    config.write_text(json.dumps({"api": {"provider": "qwen", "base_url": "https://example.invalid"}}))
    with (tmp_path / "stderr.log").open("w") as stderr:
        agent = AgentProcess(sys.executable, config, stderr=stderr, model="qwen-cua")
        try:
            agent.reset()
            assert agent.metadata["model"] == "qwen-cua"
            assert agent.metadata["base_url"] == "https://example.invalid"
        finally:
            agent.close()
