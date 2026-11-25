"""Attempt record schema shared by attempt collection, pool building, selectors and the update pipeline.

One record describes one evaluated agent attempt on one development task. Pool files
(see docs/pool_contract.md) may contain several occurrences of the same attempt; each
occurrence keeps the original fields and adds pool_record_id, original_record_id and is_copy.

Run `python3 scripts/validate_attempts.py attempts/records.jsonl` to check a file.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = "1"

OUTCOMES = ("success", "failure")
FEEDBACK_SOURCES = ("original", "rerun")

# Coarse failure categories derived deterministically from SkillOpt's fail_reason.
# "none" is reserved for successful attempts.
ERROR_CATEGORIES = (
    "none",
    "llm_call_failed",
    "no_code",
    "exec_error",
    "timeout",
    "no_output",
    "wrong_sheet",
    "wrong_values",
    "setup_error",
    "other",
)

# field -> (accepted types, required)
FIELDS: dict[str, tuple[tuple[type, ...], bool]] = {
    "record_id": ((str,), True),
    "task_id": ((str,), True),
    "source_family": ((str,), True),
    "split": ((str,), True),
    "workbook_hash": ((str,), True),
    "env_version": ((str,), True),
    "feedback_source": ((str,), True),
    "outcome": ((str,), True),
    "error_category": ((str,), True),
    "error_detail": ((str,), False),
    "fail_reason": ((str,), True),
    "instruction": ((str,), True),
    "task_type": ((str,), True),
    "n_turns": ((int,), True),
    "tool_events": ((list,), True),
    "token_count": ((int,), True),
    "trajectory_path": ((str,), True),
    # sha256 of the trajectory content; identical attempts share it (exact deduplication).
    "trajectory_sha256": ((str,), True),
    # Filled by the trajectory parser; null until then.
    "summary": ((str, type(None)), True),
    "embedding": ((list, type(None)), True),
    # Present only on pool occurrences.
    "pool_record_id": ((str,), False),
    "original_record_id": ((str,), False),
    "is_copy": ((bool,), False),
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def categorize_failure(fail_reason: str) -> tuple[str, str]:
    """Map a SkillOpt SpreadsheetBench fail_reason to (error_category, error_detail).

    The detail is a short stable token (e.g. an exception class) that finer
    "failure behavior" grouping can use; it is empty when nothing reliable is available.
    """
    reason = (fail_reason or "").strip()
    if not reason:
        return "none", ""
    low = reason.lower()
    if low.startswith("llm-call-failed"):
        return "llm_call_failed", _exception_name(reason)
    if low.startswith("empty-code-block"):
        return "no_code", ""
    if low.startswith("exec-error"):
        if "timeout after" in low:
            return "timeout", ""
        return "exec_error", _exception_name(reason)
    if low.startswith("timeout") or "timed out" in low:
        return "timeout", ""
    if low.startswith("output-not-found") or "output file was not created" in low:
        return "no_output", ""
    if low.startswith("eval-mismatch"):
        if "worksheet not found" in low:
            return "wrong_sheet", ""
        if "load error" in low:
            return "no_output", "unreadable_output"
        return "wrong_values", ""
    if low.startswith(("no-test-cases", "unsafe-task-id")):
        return "setup_error", low.split(":", 1)[0]
    return "other", ""


def model_call_failures(results: list[dict]) -> list[dict]:
    """Rollouts where the model call itself failed (rate limit, overload), so the
    task was never attempted. These must not be scored or used as feedback."""
    return [r for r in results if categorize_failure(r.get("fail_reason", ""))[0] == "llm_call_failed"]


def _exception_name(text: str) -> str:
    match = re.search(r"\b([A-Z][A-Za-z]*(?:Error|Exception|Exit|Interrupt))\b", text)
    return match.group(1) if match else ""


def estimate_tokens(text: str) -> int:
    """Model-agnostic token estimate (about 4 characters per token) used for feedback budgets."""
    return math.ceil(len(text) / 4) if text else 0


def validate_record(record: object, *, require_derived: bool = False) -> list[str]:
    """Return a list of problems with one record; an empty list means it is valid.

    require_derived=True also requires summary and embedding to be filled in,
    which selectors that use semantic similarity need.
    """
    if not isinstance(record, dict):
        return ["record is not a JSON object"]
    errors: list[str] = []
    for name, (types, required) in FIELDS.items():
        if name not in record:
            if required:
                errors.append(f"missing field: {name}")
            continue
        value = record[name]
        # bool is a subclass of int; reject it for integer fields.
        if isinstance(value, bool) and bool not in types:
            errors.append(f"{name}: expected {_type_names(types)}, got bool")
        elif not isinstance(value, types):
            errors.append(f"{name}: expected {_type_names(types)}, got {type(value).__name__}")
    if errors:
        return errors

    for name in ("record_id", "task_id", "source_family", "env_version", "trajectory_path"):
        if not record[name].strip():
            errors.append(f"{name}: must be non-empty")
    if record["split"] != "dev":
        errors.append("split: feedback records must come from the development split")
    for name in ("workbook_hash", "trajectory_sha256"):
        if not _SHA256.match(record[name]):
            errors.append(f"{name}: expected a lowercase sha256 hex digest")
    if record["feedback_source"] not in FEEDBACK_SOURCES:
        errors.append(f"feedback_source: expected one of {FEEDBACK_SOURCES}")
    if record["outcome"] not in OUTCOMES:
        errors.append(f"outcome: expected one of {OUTCOMES}")
    if record["error_category"] not in ERROR_CATEGORIES:
        errors.append(f"error_category: expected one of {ERROR_CATEGORIES}")
    elif (record["outcome"] == "success") != (record["error_category"] == "none"):
        errors.append("error_category: must be 'none' exactly when outcome is 'success'")
    if record["n_turns"] < 0:
        errors.append("n_turns: must be >= 0")
    if record["token_count"] <= 0:
        errors.append("token_count: must be > 0")
    if not all(isinstance(e, (str, dict)) for e in record["tool_events"]):
        errors.append("tool_events: items must be strings or objects")
    path = PurePosixPath(record["trajectory_path"])
    if path.is_absolute() or ".." in path.parts:
        errors.append("trajectory_path: must be relative to the attempts root without '..'")

    embedding = record["embedding"]
    if embedding is not None:
        if not embedding or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in embedding
        ):
            errors.append("embedding: expected a non-empty list of finite numbers")
    if require_derived:
        if not (record["summary"] or "").strip():
            errors.append("summary: required but empty")
        if embedding is None:
            errors.append("embedding: required but null")

    pool_fields = [f for f in ("pool_record_id", "original_record_id", "is_copy") if f in record]
    if pool_fields and len(pool_fields) != 3:
        errors.append("pool fields: pool_record_id, original_record_id and is_copy must appear together")
    elif pool_fields and record["original_record_id"] != record["record_id"]:
        errors.append("original_record_id: must equal record_id (copies keep the original identity)")
    return errors


def validate_records(records: list[dict], *, require_derived: bool = False) -> list[str]:
    """Validate a list of records, including checks that span records."""
    errors: list[str] = []
    occurrence_key = "pool_record_id" if records and "pool_record_id" in records[0] else "record_id"
    seen: set[str] = set()
    family_of_task: dict[str, str] = {}
    dims: set[int] = set()
    for i, record in enumerate(records, 1):
        problems = validate_record(record, require_derived=require_derived)
        errors.extend(f"line {i}: {p}" for p in problems)
        if problems:
            continue
        key = record.get(occurrence_key, "")
        if key in seen:
            errors.append(f"line {i}: duplicate {occurrence_key} {key!r}")
        seen.add(key)
        family = family_of_task.setdefault(record["task_id"], record["source_family"])
        if family != record["source_family"]:
            errors.append(f"line {i}: task {record['task_id']} has inconsistent source_family")
        if record["embedding"] is not None:
            dims.add(len(record["embedding"]))
    if len(dims) > 1:
        errors.append(f"embeddings have inconsistent dimensions: {sorted(dims)}")
    return errors


def load_jsonl(path: str | Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON ({exc.msg})") from None
    return records


def trajectory_digest(conversation: list[dict]) -> str:
    """sha256 of a conversation in canonical JSON form."""
    canonical = json.dumps(conversation, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tool_events_from_conversation(conversation: list[dict]) -> list[str]:
    """Reduce a SkillOpt codegen conversation to an ordered list of coarse events."""
    events: list[str] = []
    for message in conversation:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "")
        content = str(message.get("content", ""))
        if role == "assistant":
            events.append("write_code" if "```" in content else "respond")
        elif role == "system" and content.startswith("[POST-EXECUTION VERIFICATION]"):
            if "ERROR:" in content:
                events.append("exec_error")
            elif "FAIL" in content:
                events.append("check_fail")
            else:
                events.append("check_pass")
        elif role == "user" and events:
            events.append("feedback")
    return events


def record_from_rollout(
    result: dict,
    *,
    record_id: str,
    source_family: str,
    workbook_hash: str,
    env_version: str,
    feedback_source: str,
    trajectory_path: str,
    conversation: list[dict],
    feedback_text: str,
) -> dict:
    """Build the deterministic fields of a record from one SkillOpt rollout result.

    feedback_text is the trajectory as the optimizer will read it; its size sets
    token_count. summary and embedding are left null for the trajectory parser.
    """
    category, detail = categorize_failure(result.get("fail_reason", ""))
    outcome = "success" if result.get("hard") else "failure"
    if outcome == "success":
        category, detail = "none", ""
    elif category == "none":
        category = "other"
    record = {
        "record_id": record_id,
        "task_id": str(result["id"]),
        "source_family": source_family,
        "split": "dev",
        "workbook_hash": workbook_hash,
        "env_version": env_version,
        "feedback_source": feedback_source,
        "outcome": outcome,
        "error_category": category,
        "fail_reason": str(result.get("fail_reason", "")),
        "instruction": str(result.get("task_description", "")),
        "task_type": str(result.get("task_type", "")),
        "n_turns": int(result.get("n_turns", 0) or 0),
        "tool_events": tool_events_from_conversation(conversation),
        "token_count": max(estimate_tokens(feedback_text), 1),
        "trajectory_path": trajectory_path,
        "trajectory_sha256": trajectory_digest(conversation),
        "summary": None,
        "embedding": None,
    }
    if detail:
        record["error_detail"] = detail
    return record


def _type_names(types: tuple[type, ...]) -> str:
    return " or ".join("null" if t is type(None) else t.__name__ for t in types)
