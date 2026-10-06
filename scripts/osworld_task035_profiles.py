"""Frozen API settings shared by both Task035 comparison arms."""
from ui_kobe.api.kimi import BASE_URL


def profile_for(model):
    if model == "kimi-k3":
        return {"provider": "kimi", "api_key_env": "KIMI_API_KEY", "temperature": 1,
                "top_p": 0.95, "max_output_tokens": 16000, "extra_body": {},
                "reasoning_effort": "max", "thinking": "always enabled",
                "run_prefix": "osworld21-kimi-k3-task035-compare-"}
    return {"provider": "qwen", "api_key_env": "QWEN_API_KEY", "temperature": 0,
            "top_p": 0.9, "max_output_tokens": 16000, "extra_body": {"enable_thinking": False},
            "thinking": "disabled", "run_prefix": "osworld21-qwen38-task035-compare-"}


def validate_comparison_config(config):
    api, agent = config["api"], config["agent"]
    profile = profile_for(api["model"])
    expected_url = BASE_URL if profile["provider"] == "kimi" else "https://pjfdspqowq.a.pinggy.link"
    if (api["model"] not in ("kimi-k3", "qwen3.8-max") or api["base_url"] != expected_url
            or api["provider"] != profile["provider"] or api["api_key_env"] != profile["api_key_env"]
            or api.get("extra_body", {}) != profile["extra_body"]
            or agent["temperature"] != profile["temperature"] or agent.get("top_p") != profile["top_p"]
            or agent["max_output_tokens"] != profile["max_output_tokens"]
            or (profile["provider"] == "kimi" and api.get("reasoning_effort") != "max")):
        raise RuntimeError("Both arms must use the same supported model/API/generation profile")
    return profile


def description(model):
    if model == "kimi-k3":
        return ("K3 thinking 始终启用，reasoning_effort=max；temperature=1、top_p=0.95 为服务固定值，"
                "请求省略这两个采样字段；max_completion_tokens=16000 包含 reasoning 与最终回复。"
                "不发送 Qwen enable_thinking 或 K2 thinking 字段。stream 和批量动作关闭。")
    return "thinking、stream、批量动作关闭；temperature=0、top_p=0.9、max_tokens=16000。"
