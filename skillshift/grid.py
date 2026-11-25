"""Full experiment grid: pools x selectors x seeds through the update pipeline.

Runs go one seed at a time. Test evaluation follows the config's test_policy, and
sealed test scores are exported only once every run has finished.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import shutil
from fractions import Fraction
from pathlib import Path

from skillshift import pilot
from skillshift.schema import load_jsonl, validate_records
from skillshift.usage import Ledger, reset_usage, usage_snapshot


def load_spec(path: Path) -> dict:
    """Read the grid spec and check its shape."""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    pools = spec.get("pools")
    if not isinstance(pools, dict) or not pools:
        problems.append("pools must map pool names to a repeat fraction or null")
    else:
        for name, fraction in pools.items():
            if fraction is not None:
                try:
                    Fraction(fraction)
                except (TypeError, ValueError):
                    problems.append(f"pools.{name}: repeat fraction must be like \"0\" or \"1/2\", or null")
    if not isinstance(spec.get("selectors"), list) or not spec["selectors"]:
        problems.append("selectors must be a non-empty list")
    seeds = spec.get("seeds")
    if not isinstance(seeds, list) or not seeds or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds):
        problems.append("seeds must be a non-empty list of integers")
    if problems:
        raise ValueError("invalid grid spec:\n  " + "\n  ".join(problems))
    return spec


def combinations(spec: dict) -> list[tuple[int, str, str]]:
    """(seed, pool, selector) in run order: one full seed before the next."""
    return [(seed, pool, selector) for seed in spec["seeds"] for pool in spec["pools"] for selector in spec["selectors"]]


def pool_problems(name: str, pool_path: Path, records_path: Path, fraction, pool_dir: Path) -> list[str]:
    """Full provenance check for exact-copy pools; schema and pool fields for the rest."""
    if fraction is not None:
        manifest, stats = pool_dir / "manifest.json", pool_dir / "pool_stats.csv"
        return pilot.pool_problems(pool_path, records_path, Fraction(fraction),
                                   manifest if manifest.is_file() else None,
                                   stats if stats.is_file() else None)
    pool = load_jsonl(pool_path)
    if not pool:
        return [f"{name}: pool is empty"]
    problems = [f"{name}: {p}" for p in validate_records(pool)[:10]]
    if any(f not in row for row in pool for f in pilot.POOL_FIELDS):
        problems.append(f"{name}: occurrence without pool fields")
    return problems


def selector_problems(cfg: dict, selectors: list[str]) -> list[str]:
    """Selectors that are missing from the config or cannot be built yet (e.g. no threshold)."""
    from skillshift.selection import load_selector

    problems = []
    for name in selectors:
        if name not in cfg["selectors"]:
            problems.append(f"selector {name!r} is not listed in config selectors")
            continue
        try:
            load_selector(cfg["selectors"][name])
        except Exception as exc:  # noqa: BLE001
            problems.append(f"selector {name!r} cannot run: {exc}")
    return problems


def run_state(cfg: dict, out_root: Path, pool_path: Path, selector: str, seed: int) -> tuple[str, list[str]]:
    """('completed' | 'partial' | 'missing', problems) for one combination."""
    run_dir = out_root / "runs" / pilot.run_id_for(Path(pool_path).stem, selector, seed)
    log_path = run_dir / "run.json"
    if not run_dir.exists():
        return "missing", []
    if not log_path.is_file():
        return "partial", [f"{run_dir.name}: run directory exists without run.json"]
    log = json.loads(log_path.read_text(encoding="utf-8"))
    problems = []
    if log.get("selector") != selector:
        problems.append(f"{run_dir.name}: selector {log.get('selector')} != {selector}")
    if log.get("seed") != seed:
        problems.append(f"{run_dir.name}: seed {log.get('seed')} != {seed}")
    if Path(pool_path).is_file() and log.get("pool_sha256") != pilot.sha256_file(pool_path):
        problems.append(f"{run_dir.name}: run used a different version of the pool file")
    policy = cfg["evaluation"]["test_policy"]
    gate = log.get("gate", {})
    should_test = log.get("edited") and (policy == "all" or (policy == "accepted" and gate.get("accepted")))
    if bool(log.get("test_evaluated")) != bool(should_test):
        problems.append(f"{run_dir.name}: test_evaluated does not match test_policy {policy}")
    return "completed", problems


def cached_count(cfg: dict, out_root: Path, skill: str, task_ids: list[str], split: str) -> int:
    """How many of task_ids already have a cached result for this skill on this split."""
    from skillshift.update import _eval_settings_hash, sha256_text

    path = Path(out_root) / "eval_cache" / _eval_settings_hash(cfg) / split / sha256_text(skill)[:16] / "results.jsonl"
    if not path.is_file():
        return 0
    return len({str(r["id"]) for r in load_jsonl(path)} & set(task_ids))


def estimate_calls(cfg: dict, pool_path: Path, n_val: int, n_test: int, parent_val_uncached: int,
                   parent_test_uncached: int) -> int:
    """Upper estimate for one run: the pilot estimate plus test scoring if the child is accepted."""
    n_feedback = pilot.max_feedback_records(load_jsonl(pool_path), cfg["feedback"]["token_budget"])
    calls = pilot.estimate_run_calls(cfg, n_val, n_feedback, parent_val_uncached)
    if cfg["evaluation"]["test_policy"] != "none":
        turns = max(int(cfg["executor"]["max_turns"]), 1)
        calls += (n_test + parent_test_uncached) * turns
    return calls


def run_one(cfg: dict, *, seed: int, pool: str, selector: str, pool_path: Path, attempts_root: Path,
            out_root: Path, ledger: Ledger, val_ids: list[str], retry_partial: bool = False,
            run_update=None, log=print) -> dict:
    """Run one combination unless it is already complete; record its usage in the ledger."""
    if run_update is None:
        from skillshift.update import run_update
    run_id = pilot.run_id_for(pool, selector, seed)
    state, problems = run_state(cfg, out_root, pool_path, selector, seed)
    if state == "completed":
        log(f"[grid] {run_id}: already completed{' with problems' if problems else ''}")
        return {"state": "skipped_completed", "problems": problems}
    if state == "partial":
        if not retry_partial:
            log(f"[grid] {run_id}: partial run left in place (pass --retry-partial to move it aside and rerun)")
            return {"state": "partial", "problems": problems}
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = out_root / "partial" / run_id / stamp
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out_root / "runs" / run_id), str(dest))
        log(f"[grid] {run_id}: moved partial run to {dest}")

    attempt = 1 + sum(1 for r in ledger.rows() if r["event_id"].startswith(f"update:{run_id}:"))
    reset_usage()
    status, note, run_log = "failed", "", None
    try:
        run_log = run_update(cfg, pool_path=pool_path, selector_name=selector, attempts_root=attempts_root,
                             out_root=out_root, seed=seed, val_ids=val_ids)
        status = "completed"
    except BaseException as exc:  # noqa: BLE001 - usage is recorded even on Ctrl-C
        status = "partial" if isinstance(exc, KeyboardInterrupt) else "failed"
        note = f"{type(exc).__name__}: {exc}"[:300]
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        ledger.record(f"update:{run_id}:{attempt}", phase="update", label=run_id, status=status,
                      summary=usage_snapshot(), feedback_tokens_estimate=(run_log or {}).get("feedback_tokens"),
                      note=note)
    if run_log is None:
        return {"state": "failed", "problems": [note]}
    _, problems = run_state(cfg, out_root, pool_path, selector, seed)
    log(f"[grid] {run_id}: completed")
    return {"state": "completed", "problems": problems}


RUN_COLUMNS = ("run_id", "seed", "pool", "selector", "edited", "parent_val", "child_val", "accepted",
               "test_evaluated", "feedback_tokens", "api_calls")


def results(spec: dict, pools: dict[str, Path], out_root: Path) -> tuple[list[dict], list[str]]:
    """Validation-level row per completed run, plus missing combinations. Never reads test scores."""
    rows, missing = [], []
    for seed, pool, selector in combinations(spec):
        run_id = pilot.run_id_for(pool, selector, seed)
        path = out_root / "runs" / run_id / "run.json"
        if not path.is_file():
            missing.append(run_id)
            continue
        log = json.loads(path.read_text(encoding="utf-8"))
        gate = log["gate"]
        rows.append({
            "run_id": run_id, "seed": seed, "pool": pool, "selector": selector,
            "edited": log["edited"], "parent_val": gate["parent_solved"],
            "child_val": gate["child_solved"] if log["edited"] else "", "accepted": gate["accepted"],
            "test_evaluated": log["test_evaluated"], "feedback_tokens": log["feedback_tokens"],
            "api_calls": log.get("api_usage", {}).get("_total", {}).get("calls", ""),
        })
    return rows, missing


def consistency_problems(rows: list[dict], out_root: Path) -> list[str]:
    """Settings that must be identical across every completed run."""
    logs = [json.loads((out_root / "runs" / r["run_id"] / "run.json").read_text(encoding="utf-8")) for r in rows]
    problems = []
    for key in ("val_task_ids", "models", "parent_skill_sha256", "token_budget", "config_hash"):
        if len({json.dumps(log.get(key), sort_keys=True) for log in logs}) > 1:
            problems.append(f"{key} differs across grid runs")
    if len({log["gate"]["margin_tasks"] for log in logs}) > 1:
        problems.append("gate margin differs across grid runs")
    return problems


def write_csv(path: Path, rows: list[dict], columns) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)


def per_task_rows(out_root: Path, rows: list[dict], tasks: list[dict], split: str) -> list[dict]:
    """One row per (run, task): parent and child solved flags on val or sealed test scores."""
    family = {str(t["id"]): t["family_id"] for t in tasks}
    out = []
    for row in rows:
        run_id = row["run_id"]
        if split == "val":
            log = json.loads((out_root / "runs" / run_id / "run.json").read_text(encoding="utf-8"))
            if not log["edited"] or "val_per_task" not in log:
                continue
            parent, child = log["val_per_task"]["parent"], log["val_per_task"]["child"]
        else:
            sealed = out_root / "sealed" / f"{run_id}.json"
            if not sealed.is_file():
                continue
            data = json.loads(sealed.read_text(encoding="utf-8"))
            parent, child = data["parent"], data["child"]
        for task_id in sorted(parent):
            out.append({"run_id": run_id, "seed": row["seed"], "pool": row["pool"], "selector": row["selector"],
                        "task_id": task_id, "source_family": family.get(task_id, ""),
                        "parent_solved": int(bool(parent[task_id])), "child_solved": int(bool(child.get(task_id)))})
    return out
