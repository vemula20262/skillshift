"""Validation-only pilot: two pools x three selectors through the shared update pipeline.

Every run uses the same config, seed, validation task IDs, starting skill, feedback
budget and gate margin; only the pool and selector change. Test evaluation is turned
off in memory (evaluation.test_policy = "none") and every run log is checked for
test_evaluated = false.

Restart behavior: a combination whose run.json exists and verifies is skipped. A run
directory without run.json is a partial run; it is reported and left in place unless
retry_partial is set, in which case it is moved to <out>/partial/ before the rerun.
"""
from __future__ import annotations

import copy
import csv
import datetime as _dt
import hashlib
import json
import shutil
from fractions import Fraction
from pathlib import Path

from skillshift.schema import load_jsonl, validate_records
from skillshift.usage import Ledger, reset_usage, usage_snapshot

POOLS = {"C0": Fraction(0), "C1_50": Fraction(1, 2)}
SELECTORS = ("unfiltered", "exact_dedup", "source_balanced")
GRID = tuple((pool, selector) for pool in POOLS for selector in SELECTORS)
POOL_FIELDS = ("pool_record_id", "original_record_id", "is_copy")


def pilot_config(cfg: dict) -> dict:
    out = copy.deepcopy(cfg)
    out["evaluation"]["test_policy"] = "none"
    return out


def cached_val_count(cfg: dict, out_root: Path, skill: str, val_ids: list[str]) -> int:
    """How many of val_ids already have a cached result for this skill (no model call needed)."""
    from skillshift.update import _eval_settings_hash, sha256_text

    path = Path(out_root) / "eval_cache" / _eval_settings_hash(cfg) / "val" / sha256_text(skill)[:16] / "results.jsonl"
    if not path.is_file():
        return 0
    done = {str(r["id"]) for r in load_jsonl(path)}
    return len(done & set(val_ids))


def max_feedback_records(pool: list[dict], token_budget: int) -> int:
    """Most records the sampler could fit in the budget (smallest first), an upper bound."""
    used = count = 0
    for size in sorted(int(r["token_count"]) for r in pool):
        if used + size > token_budget:
            break
        used += size
        count += 1
    return count


def estimate_run_calls(cfg: dict, n_val: int, n_feedback: int, parent_uncached: int) -> int:
    """Upper estimate of successful calls for one update run, used to stay within the allowance.

    Counts child validation (n_val tasks x max_turns) and any parent validation tasks
    not yet cached. Optimizer calls follow SkillOpt's stages: reflect splits failures
    and successes into minibatches (one call each, so at most one extra for the split),
    each group's patches are merged eight at a time, then one final merge and one
    rank-and-select call.
    """
    turns = max(int(cfg["executor"]["max_turns"]), 1)
    size = max(int(cfg["feedback"]["minibatch_size"]), 1)
    reflect = -(-n_feedback // size) + 1
    merges = 2 * -(-reflect // 7)
    return (n_val + parent_uncached) * turns + reflect + merges + 2


def run_id_for(pool: str, selector: str, seed: int) -> str:
    """Matches the run ID skillshift.update.run_update derives from the pool file name."""
    return f"{pool}__{selector}__seed{seed}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ── Pool provenance ──────────────────────────────────────────────────────────


def pool_problems(pool_path: Path, records_path: Path, expected_fraction: Fraction,
                  manifest_path: Path | None = None, stats_path: Path | None = None) -> list[str]:
    """Check that a pool was built from these records with the expected repeat fraction."""
    name = Path(pool_path).stem
    pool = load_jsonl(pool_path)
    records = {r["record_id"]: r for r in load_jsonl(records_path)}
    problems = [f"{name}: {p}" for p in validate_records(pool)[:10]]
    if not pool:
        return problems + [f"{name}: pool is empty"]
    if problems:
        return problems

    originals_seen: list[str] = []
    for row in pool:
        if any(f not in row for f in POOL_FIELDS):
            problems.append(f"{name}: occurrence without pool fields")
            break
        source = records.get(row["original_record_id"])
        if source is None:
            problems.append(f"{name}: {row['original_record_id']} is not in the handed-off records")
            continue
        if {k: v for k, v in row.items() if k not in POOL_FIELDS} != source:
            problems.append(f"{name}: occurrence {row['pool_record_id']} differs from its source record")
        if not row["is_copy"]:
            originals_seen.append(row["original_record_id"])
    if sorted(originals_seen) != sorted(records):
        problems.append(f"{name}: pool does not keep every handed-off record exactly once as an original")

    copies = sum(bool(r["is_copy"]) for r in pool)
    measured = Fraction(copies, len(pool))
    if measured != expected_fraction:
        problems.append(f"{name}: repeat fraction {measured} != expected {expected_fraction}")

    digest = sha256_file(records_path)
    if manifest_path is not None:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        recorded = manifest.get("provenance", {}).get("attempts", {}).get("sha256")
        if recorded != digest:
            problems.append(f"{name}: pool manifest was built from attempts {recorded}, not the handed-off {digest}")
        stats = manifest.get("pools", {}).get(name)
        if stats is None:
            problems.append(f"{name}: not listed in the pool manifest")
        elif Fraction(stats["repeat_fraction"]) != measured:
            problems.append(f"{name}: manifest repeat fraction {stats['repeat_fraction']} != measured {measured}")
    if stats_path is not None:
        with open(stats_path, newline="", encoding="utf-8") as f:
            row = next((r for r in csv.DictReader(f) if r["pool_name"] == name), None)
        if row is None:
            problems.append(f"{name}: not listed in pool_stats.csv")
        elif Fraction(row["repeat_fraction"]) != measured or int(row["total"]) != len(pool):
            problems.append(f"{name}: pool_stats.csv disagrees with the pool file")
    return problems


# ── Runs ─────────────────────────────────────────────────────────────────────


def run_state(out_root: Path, pool_path: Path, selector: str, seed: int) -> tuple[str, list[str]]:
    """('completed' | 'partial' | 'missing', problems) for one combination."""
    run_dir = out_root / "runs" / run_id_for(Path(pool_path).stem, selector, seed)
    log_path = run_dir / "run.json"
    if not run_dir.exists():
        return "missing", []
    if not log_path.is_file():
        return "partial", [f"{run_dir.name}: run directory exists without run.json"]
    log = json.loads(log_path.read_text(encoding="utf-8"))
    problems = []
    if log.get("test_evaluated") is not False:
        problems.append(f"{run_dir.name}: test_evaluated is not false")
    if log.get("selector") != selector:
        problems.append(f"{run_dir.name}: selector {log.get('selector')} != {selector}")
    if log.get("seed") != seed:
        problems.append(f"{run_dir.name}: seed {log.get('seed')} != {seed}")
    if Path(pool_path).is_file() and log.get("pool_sha256") != sha256_file(pool_path):
        problems.append(f"{run_dir.name}: run used a different version of the pool file")
    return "completed", problems


def run_pilot(cfg: dict, *, pools: dict[str, Path], attempts_root: Path, out_root: Path, ledger: Ledger,
              val_ids: list[str], retry_partial: bool = False, only: list[tuple[str, str]] | None = None,
              run_update=None, log=print) -> dict:
    """Run every pending combination; returns per-combination outcomes."""
    if run_update is None:
        from skillshift.update import run_update
    cfg = pilot_config(cfg)
    seed = cfg["seed"]
    outcome: dict[str, dict] = {}
    for pool, selector in GRID:
        if only is not None and (pool, selector) not in only:
            continue
        run_id = run_id_for(pool, selector, seed)
        state, problems = run_state(out_root, pools[pool], selector, seed)
        if state == "completed":
            outcome[run_id] = {"state": "skipped_completed", "problems": problems}
            log(f"[pilot] {run_id}: already completed{' with problems' if problems else ''}")
            continue
        if state == "partial":
            if not retry_partial:
                outcome[run_id] = {"state": "partial", "problems": problems}
                log(f"[pilot] {run_id}: partial run left in place (pass --retry-partial to move it aside and rerun)")
                continue
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = out_root / "partial" / run_id / stamp
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out_root / "runs" / run_id), str(dest))
            log(f"[pilot] {run_id}: moved partial run to {dest}")

        attempt = 1 + sum(1 for r in ledger.rows() if r["event_id"].startswith(f"update:{run_id}:"))
        event_id = f"update:{run_id}:{attempt}"
        reset_usage()
        status, note, run_log = "failed", "", None
        try:
            run_log = run_update(cfg, pool_path=pools[pool], selector_name=selector, attempts_root=attempts_root,
                                 out_root=out_root, seed=seed, val_ids=val_ids)
            status = "completed"
        except BaseException as exc:  # noqa: BLE001 - usage is recorded even on Ctrl-C
            status = "partial" if isinstance(exc, KeyboardInterrupt) else "failed"
            note = f"{type(exc).__name__}: {exc}"[:300]
            if isinstance(exc, KeyboardInterrupt):
                raise
            outcome[run_id] = {"state": "failed", "problems": [note]}
        finally:
            ledger.record(event_id, phase="update", label=run_id, status=status, summary=usage_snapshot(),
                          feedback_tokens_estimate=(run_log or {}).get("feedback_tokens"), note=note)
        if run_log is not None:
            _, problems = run_state(out_root, pools[pool], selector, seed)
            outcome[run_id] = {"state": "completed", "problems": problems}
            log(f"[pilot] {run_id}: completed")
    return outcome


# ── Results ──────────────────────────────────────────────────────────────────

TABLE_COLUMNS = ("run_id", "pool", "selector", "edit_produced", "parent_val", "child_val",
                 "gate_decision", "feedback_tokens", "test_evaluated", "api_calls", "api_total_tokens")


def results_table(out_root: Path, seed: int) -> tuple[list[dict], list[str]]:
    """One row per completed run.json in the grid, plus the missing combinations."""
    rows, missing = [], []
    for pool, selector in GRID:
        path = out_root / "runs" / run_id_for(pool, selector, seed) / "run.json"
        if not path.is_file():
            missing.append(f"{pool} x {selector}")
            continue
        log = json.loads(path.read_text(encoding="utf-8"))
        gate = log["gate"]
        n = gate["n_tasks"]
        if not log["edited"]:
            decision, child = "no edit (skill unchanged)", ""
        else:
            decision = "accepted" if gate["accepted"] else "rejected by gate"
            child = f"{gate['child_solved']}/{n}"
        total = log.get("api_usage", {}).get("_total", {})
        rows.append({
            "run_id": log["run_id"],
            "pool": pool,
            "selector": log["selector"],
            "edit_produced": "yes" if log["edited"] else "no",
            "parent_val": f"{gate['parent_solved']}/{n}",
            "child_val": child,
            "gate_decision": decision,
            "feedback_tokens": log["feedback_tokens"],
            "test_evaluated": str(log["test_evaluated"]).lower(),
            "api_calls": total.get("calls", ""),
            "api_total_tokens": total.get("total_tokens", ""),
        })
    return rows, missing


def consistency_problems(out_root: Path, seed: int) -> list[str]:
    """Settings that must be identical across all completed pilot runs."""
    logs = []
    for pool, selector in GRID:
        path = out_root / "runs" / run_id_for(pool, selector, seed) / "run.json"
        if path.is_file():
            logs.append(json.loads(path.read_text(encoding="utf-8")))
    problems = []
    for key in ("val_task_ids", "seed", "models", "parent_skill_sha256", "token_budget", "config_hash"):
        values = {json.dumps(log.get(key), sort_keys=True) for log in logs}
        if len(values) > 1:
            problems.append(f"{key} differs across pilot runs")
    margins = {log["gate"]["margin_tasks"] for log in logs}
    if len(margins) > 1:
        problems.append("gate margin differs across pilot runs")
    if any(log.get("test_evaluated") is not False for log in logs):
        problems.append("a pilot run evaluated the test split")
    return problems
