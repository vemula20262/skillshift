from __future__ import annotations

from .unfiltered import Unfiltered
from .exact_dedup import ExactDedup
from .semantic_dedup import SemanticDedup
from .source_balanced import SourceBalanced
from .source_behavior import SourceBehavior

METHODS = ("unfiltered", "exact_dedup", "semantic_dedup", "source_balanced", "source_behavior")


def get_selector(method: str, threshold: float | None = None):
    simple = {"unfiltered": Unfiltered, "exact_dedup": ExactDedup, "source_balanced": SourceBalanced}
    if method in simple:
        return simple[method]()
    if method not in METHODS:
        raise ValueError(f"Unknown method: {method}")
    if threshold is None:
        raise ValueError("Semantic methods require an explicit threshold; no tuned value is available yet")
    return {"semantic_dedup": SemanticDedup, "source_behavior": SourceBehavior}[method](threshold)
