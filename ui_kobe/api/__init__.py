"""Optional model providers. Importing this package never reads credentials."""


def client_from_config(config=None):
    """Configs without a provider remain GLM for backward compatibility."""
    options = dict(config or {})
    provider = options.pop("provider", "glm")
    if provider == "glm":
        from .glm import GLMClient, GLMConfig
        return GLMClient(GLMConfig(**options))
    if provider == "qwen":
        from .qwen import QwenClient, QwenConfig
        return QwenClient(QwenConfig(**options))
    if provider == "kimi":
        from .kimi import KimiClient, KimiConfig
        return KimiClient(KimiConfig(**options))
    raise ValueError(f"Unsupported model provider: {provider}")
