import json
from types import SimpleNamespace

import httpx
from openai import OpenAI
import pytest

from ui_kobe.api.glm import GLMClient, GLMConfig, GLMRequestError
from ui_kobe.utils import make_client


def completion():
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "glm-5.3-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def client_for(handler, **options):
    sdk = OpenAI(api_key="test-secret", base_url="https://example.invalid/v4", max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return GLMClient(GLMConfig(**options), sdk_client=sdk, sleep=lambda _: None, jitter=lambda a, b: b)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_transient_failure_retries_once_then_returns_sdk_result(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status if len(requests) == 1 else 200,
                              json={"error": "transient"} if len(requests) == 1 else completion())

    with client_for(handler) as client:
        response = client.chat.completions.create(messages=[{"role": "user", "content": "test"}])
        assert response.choices[0].message.content == "{}"
        assert len(requests) == 2
        assert json.loads(requests[-1].content)["model"] == "glm-5.3-flash"
        assert client.stats == {"requests": 2, "retries": 1, "prompt_tokens": 10,
                                "completion_tokens": 5, "total_tokens": 15}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_permanent_error_is_not_retried_and_does_not_leak_response_body(status):
    with client_for(lambda _: httpx.Response(status, json={"error": "test-secret"})) as client:
        with pytest.raises(GLMRequestError) as err:
            client.create(messages=[])
        assert err.value.status_code == status
        assert err.value.attempts == 1
        assert "test-secret" not in str(err.value)
        assert err.value.__suppress_context__


def test_transport_failure_and_exhaustion_are_bounded():
    def handler(request):
        raise httpx.ReadTimeout("sensitive-request", request=request)
    with client_for(handler, max_attempts=2) as client:
        with pytest.raises(GLMRequestError) as err:
            client.create(messages=[])
        assert err.value.attempts == 2
        assert client.stats["requests"] == 2


@pytest.mark.parametrize("code", ["1113", "1308", "1310", "1315", "1321"])
def test_account_quota_error_is_not_retried(code):
    with client_for(lambda _: httpx.Response(429, json={"error": {"code": code, "message": "private"}})) as client:
        with pytest.raises(GLMRequestError) as err:
            client.create(messages=[])
        assert err.value.attempts == 1
        assert err.value.provider_code == code
        assert "private" not in str(err.value)


def test_retry_budget_does_not_sleep_past_deadline():
    with client_for(lambda _: httpx.Response(503), total_timeout=0.1) as client:
        with pytest.raises(GLMRequestError, match="deadline_exceeded"):
            client.create(messages=[])
        assert client.stats["requests"] == 1
        assert client.stats["retries"] == 0


def test_no_request_after_expired_deadline():
    with client_for(lambda _: pytest.fail("Network should not be called")) as client:
        with pytest.raises(GLMRequestError, match="deadline_exceeded"):
            client.create(messages=[], deadline=0)


def test_explicit_key_is_not_replaced_with_openai_or_default_glm_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated")
    monkeypatch.setenv("GLM_API_KEY", "also-unrelated")
    monkeypatch.delenv("MISSING_CONFIG_KEY", raising=False)
    with pytest.raises(ValueError, match="configured GLM api_key"):
        make_client({"provider": "glm", "api_key": "${MISSING_CONFIG_KEY}"})


def test_factory_routes_glm_with_sdk_retry_disabled(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "only-in-test")
    client, model = make_client({"provider": "glm"})
    try:
        assert model == "glm-5.3-flash"
        assert client._sdk.max_retries == 0
        assert str(client._sdk.base_url) == "https://open.bigmodel.cn/api/paas/v4/"
        assert client._sdk.timeout == 180
    finally:
        client.close()


def test_missing_secret_fails_before_connection(monkeypatch):
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GLM_API_KEY"):
        GLMClient()


def test_stream_is_rejected_without_a_call():
    client = GLMClient(sdk_client=SimpleNamespace())
    with pytest.raises(ValueError, match="non-streaming"):
        client.create(messages=[], stream=True)
