from __future__ import annotations

from .unfiltered import Unfiltered
from .exact_dedup import ExactDedup
from .semantic_dedup import SemanticDedup

METHODS = ("unfiltered", "exact_dedup", "semantic_dedup")


def get_selector(method: str, threshold: float | None = None):
    simple = {"unfiltered": Unfiltered, "exact_dedup": ExactDedup}
    if method in simple:
        return simple[method]()
    if method not in METHODS:
        raise ValueError(f"Unknown method: {method}")
    if threshold is None:
        raise ValueError("Semantic methods require an explicit threshold; no tuned value is available yet")
    return SemanticDedup(threshold)
