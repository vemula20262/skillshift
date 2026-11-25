"""Weighted sampling of selected feedback records into a fixed token budget.

Every selection method hands the optimizer the same amount of feedback, measured in
record token_count. Selector weights decide which records fill that budget: records
are put in a seeded weighted random order (Efraimidis-Spirakis keys, u ** (1 / w))
and added in that order while they fit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SampledRecord:
    record: dict
    weight: float
    order: int


def sample_to_budget(
    records: list[dict],
    weights: list[float],
    token_budget: int,
    seed: int,
) -> list[SampledRecord]:
    """Return records chosen by weight until token_budget is filled.

    Records with weight <= 0 are never chosen. A record larger than the remaining
    budget is skipped and later, smaller records can still fill the gap. The same
    inputs and seed always give the same result.
    """
    if len(records) != len(weights):
        raise ValueError("records and weights must have the same length")
    if token_budget <= 0:
        raise ValueError("token_budget must be positive")

    rng = random.Random(seed)
    keyed = []
    for index, (record, weight) in enumerate(zip(records, weights)):
        w = float(weight)
        if w != w or w in (float("inf"), float("-inf")):
            raise ValueError(f"weight at index {index} is not finite")
        u = rng.random()
        if w <= 0:
            continue
        # Larger key = earlier position. u is in [0, 1); guard u == 0.
        key = (u if u > 0 else 1e-300) ** (1.0 / w)
        keyed.append((key, index, record, w))
    keyed.sort(key=lambda item: (-item[0], item[1]))

    chosen: list[SampledRecord] = []
    used = 0
    for order, (_, _, record, w) in enumerate(keyed):
        cost = int(record["token_count"])
        if used + cost > token_budget:
            continue
        chosen.append(SampledRecord(record=record, weight=w, order=order))
        used += cost
    return chosen
