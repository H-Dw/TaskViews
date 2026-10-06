"""Deterministic multilingual lexical baseline; replace via SeedRetriever."""
from __future__ import annotations

import math
import re
from typing import Protocol
from .model import Request, Snapshot, dumps


class SeedRetriever(Protocol):
    def rank(self, snapshot: Snapshot, request: Request, candidates: list[str]) -> list[tuple[str, float]]: ...


def terms(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9_]+", text.lower()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return result


class LexicalRetriever:
    def rank(self, snapshot: Snapshot, request: Request, candidates: list[str]) -> list[tuple[str, float]]:
        query = terms(request.task + " " + " ".join(request.target_fields))
        ranked = []
        explicit = set(request.seed_ids)
        for nid in candidates:
            node = snapshot.nodes[nid]
            text = " ".join(k + " " + dumps(a.value) for k, values in node.fields.items() for a in values)
            # The function of a destination often lives on its incoming transition.
            text += " " + " ".join(dumps(e.fields) for e in snapshot.edges.values()
                                   if e.kind == "transition" and e.target == nid)
            words = terms(text)
            overlap = len(query & words)
            score = overlap / math.sqrt(max(1, len(words)))
            if nid in explicit:
                score += 100
            if score > 0:
                ranked.append((nid, score))
        return sorted(ranked, key=lambda item: (-item[1], item[0]))
