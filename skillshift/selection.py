"""Loading feedback selectors from the config and normalising what they return.

A config entry is either "module:attribute" or a mapping
{spec: "module:attribute", kwargs: {...}}. The attribute may be a factory or class
(called with kwargs), an object with a select() method, or a plain function. The
selector is called as select(records) or select(records, budget), depending on what
it accepts, and may return any of:

  * a Selection-like object whose .items carry .record and .weight (skillshift.selectors)
  * a list of (record, weight) pairs
  * a (records, weights) tuple
  * {"records": [...], "weights": [...]}
  * a list of records, each carrying a numeric "weight" key

The pipeline always receives (records, weights) with matching lengths.
"""
from __future__ import annotations

import importlib
import inspect
import math
from typing import Callable


def passthrough(records: list[dict], budget: int) -> tuple[list[dict], list[float]]:
    """Keep every pool occurrence with weight 1. Used for pipeline smoke tests."""
    return list(records), [1.0] * len(records)


def load_selector(entry: str | dict) -> Callable[[list[dict], int], object]:
    """Resolve a config entry to a callable taking (records, budget)."""
    if isinstance(entry, dict):
        spec, kwargs = entry.get("spec"), dict(entry.get("kwargs") or {})
    else:
        spec, kwargs = entry, {}
    if not isinstance(spec, str) or ":" not in spec:
        raise ValueError(f"selector spec must look like 'module:attribute', got {spec!r}")
    module_name, attr = spec.split(":", 1)
    target = getattr(importlib.import_module(module_name), attr)
    if isinstance(target, type) or kwargs:
        target = target(**kwargs)
    select = target.select if hasattr(target, "select") else target
    if not callable(select):
        raise TypeError(f"{spec} is neither callable nor has a select() method")
    if _accepts_budget(select):
        return select
    return lambda records, budget: select(records)


def _accepts_budget(fn: Callable) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return True
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 2 or any(p.kind is p.VAR_POSITIONAL for p in params)


def normalise_output(output: object, pool: list[dict]) -> tuple[list[dict], list[float]]:
    """Convert a selector's return value to (records, weights) and check it."""
    if hasattr(output, "items") and not isinstance(output, dict) and isinstance(getattr(output, "items"), list):
        records = [item.record for item in output.items]
        weights = [item.weight for item in output.items]
    elif isinstance(output, dict):
        records, weights = output.get("records"), output.get("weights")
    elif isinstance(output, tuple) and len(output) == 2 and isinstance(output[0], list):
        records, weights = output
    elif isinstance(output, list) and all(isinstance(x, (tuple, list)) and len(x) == 2 for x in output):
        records = [x[0] for x in output]
        weights = [x[1] for x in output]
    elif isinstance(output, list) and all(isinstance(x, dict) and "weight" in x for x in output):
        records = output
        weights = [x["weight"] for x in output]
    else:
        raise TypeError("unrecognised selector output; see skillshift/selection.py for accepted shapes")

    if not isinstance(records, list) or not isinstance(weights, list) or len(records) != len(weights):
        raise ValueError("selector must return the same number of records and weights")
    clean_weights = []
    for w in weights:
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0:
            raise ValueError(f"selector returned an invalid weight: {w!r}")
        clean_weights.append(float(w))

    # Selectors may only choose among pool occurrences, never invent records.
    key = "pool_record_id" if pool and "pool_record_id" in pool[0] else "record_id"
    known = {r[key] for r in pool}
    for record in records:
        if not isinstance(record, dict) or record.get(key) not in known:
            raise ValueError(f"selector returned a record that is not in the pool (by {key})")
    return records, clean_weights
