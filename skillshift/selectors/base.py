"""Shared selector contract. See docs/SELECTOR_METHODS.md for semantics."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

Record = dict[str, Any]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def prepare(records: list[Record], embeddings: bool = False) -> list[Record]:
    """Validate the selector-facing contract; preserve extra upstream fields.

    pool_record_id identifies copied pool occurrences; record_id identifies the
    original attempt and is preserved. occurrence_id is the selector identity.
    If neither is supplied, a content hash plus occurrence index is assigned.
    This does not replace Charith's full attempt-schema validator.
    """
    result, seen, counts, dimensions, families, originals = [], set(), {}, set(), {}, {}
    pool_modes = set()
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("Each record must be a JSON object")
        r = deepcopy(raw)
        for key in ("task_id", "source_family", "summary", "outcome",
                    "feedback_source", "env_version"):
            if not isinstance(r.get(key), str) or not r[key].strip():
                raise ValueError(f"{key} must be a nonempty string")
        if r["outcome"] not in ("success", "failure"):
            raise ValueError("outcome must be success or failure")
        if r["outcome"] == "failure" and not r.get("error_category"):
            raise ValueError("failure records require error_category")
        if r.get("error_category") is not None and not isinstance(r["error_category"], str):
            raise ValueError("error_category must be a string or null")
        if type(r.get("token_count")) is not int or r["token_count"] < 0:
            raise ValueError("token_count must be a nonnegative integer")
        content_hash = digest(raw)
        counts[content_hash] = counts.get(content_hash, 0) + 1
        r.setdefault("record_id", f"{content_hash[:20]}:{counts[content_hash]}")
        if not isinstance(r["record_id"], str) or not r["record_id"]:
            raise ValueError("record_id must be a nonempty string")
        pool_keys = {"pool_record_id", "original_record_id", "is_copy"}
        pool_modes.add(bool(pool_keys.intersection(r)))
        if len(pool_modes) > 1:
            raise ValueError("Cannot mix original and pooled records")
        if pool_keys.intersection(r):
            if not pool_keys.issubset(r) or type(r["is_copy"]) is not bool:
                raise ValueError("Pool records require pool_record_id, original_record_id and boolean is_copy")
            if r["original_record_id"] != r["record_id"]:
                raise ValueError("original_record_id must match record_id")
        payload = {k: v for k, v in r.items() if k not in pool_keys | {"occurrence_id"}}
        fingerprint = digest(payload)
        if originals.setdefault(r["record_id"], fingerprint) != fingerprint:
            raise ValueError("Occurrences of one record_id must preserve identical original attempt content")
        identity = r.get("pool_record_id", r["record_id"])
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("pool_record_id (or record_id for originals) must be unique and nonempty")
        # The pool builder preserves extra original fields. An occurrence ID
        # derived before pooling still equals record_id and must be rebound.
        if "occurrence_id" in r and r["occurrence_id"] not in (identity, r["record_id"]):
            raise ValueError("occurrence_id conflicts with pool/attempt identity")
        r["occurrence_id"] = identity
        seen.add(identity)
        if families.setdefault(r["task_id"], r["source_family"]) != r["source_family"]:
            raise ValueError("One task cannot belong to different source families")
        if embeddings:
            v = r.get("embedding")
            if not isinstance(v, list) or not v or any(
                type(x) not in (int, float) or not math.isfinite(x) for x in v
            ):
                raise ValueError("embedding must be a nonempty list of finite numbers")
            norm = math.hypot(*v)
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("embedding must have finite nonzero norm")
            dimensions.add(len(v))
        if "embedding_model" in r and (not isinstance(r["embedding_model"], str) or not r["embedding_model"].strip()):
            raise ValueError("embedding_model must be a nonempty string when provided")
        result.append(r)
    if len(dimensions) > 1:
        raise ValueError("embedding dimensions must agree")
    if embeddings:
        models = {r.get("embedding_model") for r in result}
        if len(models) > 1:
            raise ValueError("embedding model metadata must agree")
    return result


def partition_key(r: Record) -> tuple[str, ...]:
    # Never merge contradictory outcomes, error categories, or environments.
    return (r["outcome"], r.get("error_category") or "", r["feedback_source"], r["env_version"])


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("cosine requires equal nonempty dimensions")
    na, nb = math.hypot(*a), math.hypot(*b)
    if not na or not nb:
        raise ValueError("cosine requires nonzero vectors")
    if a == b:
        return 1.0
    return max(-1.0, min(1.0, math.fsum((x / na) * (y / nb) for x, y in zip(a, b))))


def semantic_groups(records: list[Record], threshold: float) -> list[list[Record]]:
    """Deterministic greedy complete-link clusters, suited to small feedback pools.

    Every pair in a group must meet the threshold. This avoids chaining A~B~C
    when A and C differ. It is an adaptation, not a reproduction of SemDeDup.
    """
    if not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ValueError("threshold must be finite and within [-1, 1]")
    groups: list[list[Record]] = []
    for r in sorted(records, key=lambda r: (partition_key(r), r["summary"], r["occurrence_id"])):
        for group in groups:
            if partition_key(r) == partition_key(group[0]) and all(
                cosine(r["embedding"], x["embedding"]) >= threshold for x in group
            ):
                group.append(r)
                break
        else:
            groups.append([r])
    return groups


def medoid(group: list[Record]) -> Record:
    return min(group, key=lambda r: (
        -math.fsum(cosine(r["embedding"], x["embedding"]) for x in group), r.get("is_copy", False), r["occurrence_id"]
    ))


@dataclass
class Selected:
    record: Record
    weight: float
    group_id: str
    member_ids: list[str]
    families: list[str]


def selected(r: Record, weight: float, group_id: str, members: list[Record]) -> Selected:
    return Selected(r, weight, group_id, sorted(x["occurrence_id"] for x in members),
                    sorted({x["source_family"] for x in members}))


@dataclass
class Selection:
    method: str
    input_count: int
    items: list[Selected]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Selector(ABC):
    @abstractmethod
    def select(self, records: list[Record]) -> Selection:
        """Return original feedback, explicit weights, and auditable provenance."""
