"""Resumable collection of one original attempt per development task.

Wraps skillshift.attempts.collect_attempts. Tasks run in small chunks into one batch
directory, attempts/raw/<batch>/. SkillOpt's batch runner skips tasks already in
results.jsonl, so a restart repeats no completed model call; an interruption loses
at most the chunk in flight, whose partial trajectories are moved aside, not
overwritten.

Infrastructure failures (the model call failed after retries, the harness timed out
or crashed, or the task could not be set up) are not evaluated attempts. They are
moved out of results.jsonl into infra_failures.jsonl, with their trajectories under
infra/<task_id>/<n>/, and the task is retried on the next chunk up to a limit.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import uuid
from pathlib import Path

from skillshift.usage import Ledger, reset_usage, usage_snapshot

# fail_reason prefixes written by SkillOpt's rollout when no evaluated attempt exists.
INFRA_PREFIXES = ("llm-call-failed", "agent-error", "task-timeout-", "unexpected:", "no-test-cases", "unsafe-task-id")
# Selectors the pilot uses; none of them needs embeddings.
PILOT_SELECTORS = ("unfiltered", "exact_dedup", "source_balanced")


def is_infra_failure(result: dict) -> bool:
    if result.get("hard"):
        return False
    return str(result.get("fail_reason", "")).strip().lower().startswith(INFRA_PREFIXES)


def dev_task_ids(tasks: list[dict]) -> list[str]:
    """Runnable development task IDs in manifest order."""
    return [str(t["id"]) for t in tasks if t.get("split") == "dev" and t.get("eligible_for_execution") is not False]


def coverage_problems(expected: list[str], got: list[str]) -> list[str]:
    """Exact ID-set equality and uniqueness between the manifest and collected attempts."""
    problems = []
    if len(expected) != len(set(expected)):
        problems.append("manifest lists a development task more than once")
    dupes = sorted({i for i in got if got.count(i) > 1})
    if dupes:
        problems.append(f"duplicate attempts for tasks: {dupes[:10]}")
    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    if missing:
        problems.append(f"{len(missing)} development tasks have no evaluated attempt: {missing[:10]}")
    if extra:
        problems.append(f"{len(extra)} attempts are for tasks outside the development manifest: {extra[:10]}")
    return problems


def _utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class Collector:
    def __init__(self, cfg: dict, tasks: list[dict], skill: str, attempts_root: Path, batch_name: str,
                 ledger: Ledger, max_infra_attempts: int = 3, collect=None):
        self.cfg = cfg
        self.tasks = tasks
        self.skill = skill
        self.attempts_root = Path(attempts_root)
        self.batch_name = batch_name
        self.batch_dir = self.attempts_root / "raw" / batch_name
        self.ledger = ledger
        self.max_infra_attempts = max_infra_attempts
        if collect is None:
            from skillshift.attempts import collect_attempts as collect
        self._collect = collect

    # ── State on disk ────────────────────────────────────────────────────

    @property
    def results_path(self) -> Path:
        return self.batch_dir / "results.jsonl"

    @property
    def infra_path(self) -> Path:
        return self.batch_dir / "infra_failures.jsonl"

    def results(self) -> list[dict]:
        return _read_jsonl(self.results_path)

    def infra_failures(self) -> list[dict]:
        return _read_jsonl(self.infra_path)

    def evaluated_ids(self) -> list[str]:
        return [str(r["id"]) for r in self.results()]

    def infra_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.infra_failures():
            counts[str(row["id"])] = counts.get(str(row["id"]), 0) + 1
        return counts

    def status(self, wanted: list[str]) -> dict:
        done = set(self.evaluated_ids())
        infra = self.infra_counts()
        exhausted = sorted(i for i in wanted if i not in done and infra.get(i, 0) >= self.max_infra_attempts)
        pending = [i for i in wanted if i not in done and i not in exhausted]
        return {"wanted": len(wanted), "evaluated": len(done & set(wanted)), "pending": pending,
                "infra_exhausted": exhausted, "infra_failures": sum(infra.values())}

    # ── Running ──────────────────────────────────────────────────────────

    def run(self, wanted: list[str], chunk_size: int, max_chunks: int | None = None, log=print) -> dict:
        """Collect pending tasks chunk by chunk; returns the final status."""
        chunks = 0
        while True:
            pending = self.status(wanted)["pending"]
            if not pending or (max_chunks is not None and chunks >= max_chunks):
                break
            chunk = pending[:chunk_size]
            self._run_chunk(chunk, log)
            chunks += 1
        return self.status(wanted)

    def _run_chunk(self, chunk: list[str], log) -> None:
        self._move_aside_unrecorded(chunk)
        event_id = f"collection:{self.batch_name}:{_utc_stamp()}:{uuid.uuid4().hex[:8]}"
        label = f"{self.batch_name}:{chunk[0]}..{chunk[-1]} ({len(chunk)} tasks)"
        reset_usage()
        status, infra, note = "failed", 0, ""
        try:
            self._collect(self.cfg, self.tasks, chunk, self.skill, self.attempts_root, self.batch_name)
            infra = self._separate_infra_failures(chunk)
            status = "completed"
            note = f"{len(chunk) - infra} evaluated, {infra} infra failures"
        except BaseException as exc:  # noqa: BLE001 - usage is recorded even on Ctrl-C
            status = "partial" if isinstance(exc, KeyboardInterrupt) else "failed"
            note = f"{type(exc).__name__}: {exc}"[:300]
            raise
        finally:
            self.ledger.record(event_id, phase="collection", label=label, status=status,
                               summary=usage_snapshot(), infra_failures=infra, note=note)
            log(f"[collect] {label}: {status} {note}")

    def _separate_infra_failures(self, chunk: list[str]) -> int:
        """Move infra failures for this chunk out of results.jsonl so they are retried."""
        results = self.results()
        keep, infra = [], []
        for r in results:
            (infra if str(r["id"]) in chunk and is_infra_failure(r) else keep).append(r)
        if not infra:
            return 0
        counts = self.infra_counts()
        stamp = _utc_stamp()
        with open(self.infra_path, "a", encoding="utf-8") as f:
            for r in infra:
                task_id = str(r["id"])
                n = counts.get(task_id, 0) + 1
                counts[task_id] = n
                src = self.batch_dir / "predictions" / task_id
                dest = self.batch_dir / "infra" / task_id / str(n)
                if src.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dest))
                f.write(json.dumps({"id": task_id, "attempt": n, "recorded_utc": stamp,
                                    "fail_reason": r.get("fail_reason", ""), "phase": r.get("phase", ""),
                                    "trajectory_path": str(dest.relative_to(self.attempts_root)),
                                    "result": r}, ensure_ascii=False) + "\n")
        _write_jsonl_atomic(self.results_path, keep)
        return len(infra)

    def _move_aside_unrecorded(self, chunk: list[str]) -> None:
        """Preserve trajectories left by an interrupted chunk instead of overwriting them."""
        recorded = set(self.evaluated_ids())
        for task_id in chunk:
            src = self.batch_dir / "predictions" / task_id
            if task_id not in recorded and src.exists():
                dest = self.batch_dir / "interrupted" / task_id / _utc_stamp()
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))


# ── Selector-ready records ───────────────────────────────────────────────────


def build_records(cfg: dict, tasks: list[dict], attempts_root: Path, batch_name: str,
                  feedback_source: str = "original") -> list[dict]:
    """Records for every evaluated attempt in the batch, with behavior summaries filled in."""
    from skillshift.attempts import records_from_results
    from skillshift.summaries import behavior_summary

    attempts_root = Path(attempts_root)
    results = _read_jsonl(attempts_root / "raw" / batch_name / "results.jsonl")
    records = records_from_results(cfg, tasks, results, attempts_root, batch_name, feedback_source)
    for record in records:
        code_path = attempts_root / record["trajectory_path"] / "code.py"
        code = code_path.read_text(encoding="utf-8") if code_path.is_file() else None
        record["summary"] = behavior_summary(record, code)
    return records


def record_problems(records: list[dict], expected_ids: list[str], selectors: dict,
                    selector_names: tuple[str, ...] = PILOT_SELECTORS, budget: int = 24000) -> list[str]:
    """Checks a records file must pass before it is handed to pool construction."""
    from skillshift.schema import validate_records
    from skillshift.selection import load_selector, normalise_output

    problems = list(validate_records(records))
    problems += coverage_problems(expected_ids, [r["task_id"] for r in records])
    if any(r.get("feedback_source") != "original" for r in records):
        problems.append("records must all be original attempts")
    empty = [r["record_id"] for r in records if not (r.get("summary") or "").strip()]
    if empty:
        problems.append(f"{len(empty)} records have an empty summary: {empty[:5]}")
    for name in selector_names:
        if name not in selectors:
            problems.append(f"selector {name} is not in the config")
            continue
        try:
            kept, weights = normalise_output(load_selector(selectors[name])(records, budget), records)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            problems.append(f"selector {name} cannot consume the records: {type(exc).__name__}: {exc}")
            continue
        if not kept:
            problems.append(f"selector {name} kept no records")
    return problems


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)
