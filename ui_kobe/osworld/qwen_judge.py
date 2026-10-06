"""Task035's text-only Qwen judge adapter, registered outside OSWorld source."""
from __future__ import annotations


def judge_request(model, messages, max_tokens, temperature):
    """Task035 specifies temperature=0; translate it to K3's fixed protocol."""
    if model == "kimi-k3":
        return {"model": model, "messages": messages, "max_completion_tokens": 16000,
                "reasoning_effort": "max", "stream": False}
    return {"model": model, "messages": messages, "max_tokens": max(4096, max_tokens),
            "temperature": temperature if temperature is not None else 0,
            "stream": False, "extra_body": {"enable_thinking": False}}


def install_qwen_judge_backend() -> None:
    from desktop_env.evaluators.backends import ModelBackend, register_backend

    @register_backend("ui_kobe_qwen_judge")
    class QwenJudgeBackend(ModelBackend):
        def __init__(self, config):
            super().__init__(config)
            from openai import OpenAI

            self.client = OpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=120,
                max_retries=0,
            )

        def _generate_once(self, prompt, images, *, system=None):
            if images:
                raise ValueError("Task035 Qwen judge adapter supports text-only table evaluation")
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = self.client.chat.completions.create(**judge_request(
                self.config.model, messages, self.config.max_tokens, self.config.temperature))
            choice = response.choices[0]
            text = choice.message.content or ""
            if not text.strip() or choice.finish_reason == "length":
                raise RuntimeError("Qwen judge returned empty or truncated content")
            return text.strip()
