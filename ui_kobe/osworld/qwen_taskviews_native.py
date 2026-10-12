"""Qwen native tools plus the audited TaskViews graph/checkpoint implementation.

This is a new provider protocol, not a claim of equivalence to the original
Qwen XML agent or to the completed Kimi comparison runs.
"""
from ui_kobe.api.qwen_native import PROTOCOL as PROTOCOL
from .qwen_native_base import QwenNativeProvider
from .kimi_taskviews_native import KimiTaskViewsNativeAgent


class QwenTaskViewsNativeAgent(QwenNativeProvider, KimiTaskViewsNativeAgent):
    """Keep full TaskViews lifecycle and validation; share only provider methods."""
