"""GLM compatibility names retained for existing UI-KOBE integrations."""
from dataclasses import dataclass

from .compatible import APIConfig, APIRequestError, CompatibleClient


@dataclass(frozen=True)
class GLMConfig(APIConfig):
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-5.3-flash"
    api_key_env: str = "GLM_API_KEY"


class GLMRequestError(APIRequestError):
    provider = "GLM"


class GLMClient(CompatibleClient):
    config_type = GLMConfig
    error_type = GLMRequestError
    # Official business codes for funding, entitlements and long-window quotas.
    non_retryable_codes = frozenset({"1113", "1308", "1309", "1310", "1311", "1313", "1314", "1315",
                                    "1316", "1317", "1318", "1319", "1320", "1321"})
