"""Capabilities, not agent count or names, determine requested projections."""
from __future__ import annotations

from .model import Request, ViewKind as K


class CapabilityRouter:
    def __init__(self, rules: dict[str, tuple[K, ...]] | None = None):
        self.rules = {
            "locate": (K.GROUNDING,), "understand": (K.RELATION,),
            "record": (K.RELATION,), "navigate": (K.PLANNING,),
            "explore": (K.PLANNING, K.RELATION), "verify": (K.VERIFICATION,),
            "answer": (K.VERIFICATION,),
            **(rules or {}),
        }
        self.actions = {
            "tap": (K.GROUNDING,), "click": (K.GROUNDING,), "swipe": (K.GROUNDING,),
            "type": (K.GROUNDING, K.RELATION), "fill": (K.GROUNDING, K.RELATION),
            "select": (K.GROUNDING, K.RELATION), "back": (K.PLANNING,),
            "navigate": (K.PLANNING,), "check": (K.VERIFICATION,),
            "done": (K.VERIFICATION,), "end": (K.VERIFICATION,),
        }

    def route(self, request: Request) -> tuple[K, ...]:
        if request.kinds:
            return tuple(dict.fromkeys(request.kinds))
        kinds = []
        for capability in request.capabilities:
            if capability not in self.rules:
                raise ValueError(f"Unknown capability: {capability}")
            kinds.extend(self.rules[capability])
        kinds.extend(self.actions.get(request.action.lower(), ()))
        if not kinds:
            raise ValueError("Declare capabilities, a supported action, or explicit view kinds")
        return tuple(dict.fromkeys(kinds))
