"""Run every pool x selector x seed in config/grid.json.

A repeat fraction in the spec ("0", "1/2") turns on the full pool check for exact-copy
pools; null only checks the schema (for C2 and C3).

Examples:
  python3 scripts/run_grid.py --pool-dir pools/final --check
  python3 scripts/run_grid.py --pool-dir pools/final --call-limit 3000
  python3 scripts/run_grid.py --pool-dir pools/final --export
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift import grid  # noqa: E402
from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.update import load_tasks  # noqa: E402
from skillshift.usage import Ledger  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool-dir", type=Path, required=True, help="directory with <pool>.jsonl for every pool in the spec")
    parser.add_argument("--spec", type=Path, default=ROOT / "config" / "grid.json")
    parser.add_argument("--records", type=Path, default=ROOT / "attempts" / "records.jsonl",
                        help="the records file the exact-copy pools were built from")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--attempts-root", type=Path, default=ROOT / "attempts")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "grid")
    parser.add_argument("--cost-csv", type=Path, default=ROOT / "results" / "cost.csv")
    parser.add_argument("--call-limit", type=int, default=None,
                        help="total API call allowance (all rows in cost.csv); a run starts only if its estimate fits")
    parser.add_argument("--retry-partial", action="store_true", help="move partial runs aside and rerun them")
    parser.add_argument("--check", action="store_true", help="verify pools, selectors and run states only; no model calls")
    parser.add_argument("--export", action="store_true",
                        help="write report tables; sealed test scores are included only when every run is complete and valid")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    spec = grid.load_spec(args.spec)
    pools = {name: args.pool_dir / f"{name}.jsonl" for name in spec["pools"]}

    problems = [f"missing pool file {p}" for p in pools.values() if not p.is_file()]
    if any(f is not None for f in spec["pools"].values()) and not args.records.is_file():
        problems.append(f"missing records file {args.records}")
    if not problems:
        for name, fraction in spec["pools"].items():
            problems += grid.pool_problems(name, pools[name], args.records, fraction, args.pool_dir)
    problems += grid.selector_problems(cfg, spec["selectors"])

    states = {}
    for seed, pool, selector in grid.combinations(spec):
        state, run_problems = grid.run_state(cfg, args.out, pools[pool], selector, seed)
        states[f"{pool}__{selector}__seed{seed}"] = {"state": state, "problems": run_problems}
    run_problems = grid.validity_problems(cfg, spec, pools, args.out)
    ledger = Ledger(args.cost_csv)
    used = sum(int(r["api_calls"] or 0) for r in ledger.rows())
    done = sum(s["state"] == "completed" for s in states.values())
    print(json.dumps({"problems": problems, "run_problems": run_problems, "completed": done,
                      "total": len(states), "api_calls_so_far": used, "runs": states}, indent=2))

    if args.export:
        if run_problems:
            print("completed runs are invalid or inconsistent; nothing exported")
            return 1
        return export(spec, pools, args.out, load_tasks(cfg))
    if args.check or problems or run_problems:
        return 0 if args.check and not problems and not run_problems else 1
    if args.call_limit is None:
        print("refusing to make model calls without --call-limit")
        return 1

    from skillshift.update import configure_models, starting_skill

    configure_models(cfg)
    tasks = load_tasks(cfg)
    val_ids = [str(t["id"]) for t in tasks if t["split"] == "val" and t.get("eligible_for_execution") is not False]
    test_ids = [str(t["id"]) for t in tasks if t["split"] == "test" and t.get("eligible_for_execution") is not False]
    parent, _ = starting_skill(cfg)
    for seed, pool, selector in grid.combinations(spec):
        state, _ = grid.run_state(cfg, args.out, pools[pool], selector, seed)
        if state == "completed":
            continue
        used = sum(int(r["api_calls"] or 0) for r in ledger.rows())
        estimate = grid.estimate_calls(
            cfg, pools[pool], len(val_ids), len(test_ids),
            len(val_ids) - grid.cached_count(cfg, args.out, parent, val_ids, "val"),
            len(test_ids) - grid.cached_count(cfg, args.out, parent, test_ids, "test"),
        )
        if used + estimate > args.call_limit:
            print(f"call limit: {used} used + about {estimate} for {pool} x {selector} seed {seed} "
                  f"would pass {args.call_limit}; stopping")
            break
        outcome = grid.run_one(cfg, seed=seed, pool=pool, selector=selector, pool_path=pools[pool],
                               attempts_root=args.attempts_root, out_root=args.out, ledger=ledger,
                               val_ids=val_ids, retry_partial=args.retry_partial)
        if outcome["state"] == "failed":
            # A failed run usually means the endpoint is down; later runs would fail the same way.
            print(f"stopping after failed run: {json.dumps(outcome)}")
            break

    rows, missing = grid.results(spec, pools, args.out)
    print(json.dumps({"completed": len(rows), "missing": len(missing),
                      "consistency_problems": grid.consistency_problems(rows, args.out)}, indent=2))
    return 0 if not missing else 2


def export(spec: dict, pools: dict, out: Path, tasks: list[dict]) -> int:
    rows, missing = grid.results(spec, pools, out)
    report = out / "report"
    grid.write_csv(report / "grid_runs.csv", rows, grid.RUN_COLUMNS)
    columns = ("run_id", "seed", "pool", "selector", "task_id", "source_family", "parent_solved", "child_solved")
    grid.write_csv(report / "val_per_task.csv", grid.per_task_rows(out, rows, tasks, "val"), columns)
    if missing:
        print(f"grid incomplete ({len(missing)} runs missing); test scores stay sealed")
        return 2
    grid.write_csv(report / "test_per_task.csv", grid.per_task_rows(out, rows, tasks, "test"), columns)
    print(f"wrote {report}/grid_runs.csv, val_per_task.csv and test_per_task.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
