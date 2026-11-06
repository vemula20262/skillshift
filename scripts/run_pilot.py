"""Run the six validation-only pilot updates: C0 and C1_50 x unfiltered, exact_dedup, source_balanced.

Checks both pool files against the handed-off records before any model call, then
runs each pending combination through skillshift.update.run_update with test
evaluation turned off. Completed runs are skipped on restart.

Examples:
  python3 scripts/run_pilot.py --pool-dir pools/pilot --check
  python3 scripts/run_pilot.py --pool-dir pools/pilot --call-limit 400
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift import pilot  # noqa: E402
from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.update import load_tasks  # noqa: E402
from skillshift.usage import Ledger  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool-dir", type=Path, required=True,
                        help="directory with C0.jsonl, C1_50.jsonl and, if built with build_pools.py, manifest.json and pool_stats.csv")
    parser.add_argument("--records", type=Path, default=ROOT / "attempts" / "records.jsonl",
                        help="the records file the pools were built from")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--attempts-root", type=Path, default=ROOT / "attempts")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "pilot")
    parser.add_argument("--cost-csv", type=Path, default=ROOT / "results" / "cost.csv")
    parser.add_argument("--call-limit", type=int, default=None,
                        help="team-approved API call allowance; no run starts once cost.csv reaches it")
    parser.add_argument("--retry-partial", action="store_true", help="move partial runs aside and rerun them")
    parser.add_argument("--check", action="store_true", help="verify pools and report run states only; no model calls")
    args = parser.parse_args(argv)

    cfg = pilot.pilot_config(load_config(args.config))
    seed = cfg["seed"]
    pools = {name: args.pool_dir / f"{name}.jsonl" for name in pilot.POOLS}
    manifest = args.pool_dir / "manifest.json"
    stats = args.pool_dir / "pool_stats.csv"

    problems = [f"missing pool file {p}" for p in pools.values() if not p.is_file()]
    if not args.records.is_file():
        problems.append(f"missing records file {args.records}")
    if not problems:
        for name, fraction in pilot.POOLS.items():
            problems += pilot.pool_problems(pools[name], args.records, fraction,
                                            manifest if manifest.is_file() else None,
                                            stats if stats.is_file() else None)
    states = {}
    for pool_name, selector in pilot.GRID:
        state, run_problems = pilot.run_state(args.out, pools[pool_name], selector, seed)
        states[pilot.run_id_for(pool_name, selector, seed)] = {"state": state, "problems": run_problems}
    ledger = Ledger(args.cost_csv)
    used = sum(int(r["api_calls"] or 0) for r in ledger.rows())
    print(json.dumps({"pool_problems": problems, "runs": states, "api_calls_so_far": used,
                      "provenance_files": {"manifest.json": manifest.is_file(), "pool_stats.csv": stats.is_file()}},
                     indent=2))
    if args.check or problems:
        return 0 if args.check and not problems else 1
    if args.call_limit is None:
        print("refusing to make model calls without --call-limit (the team-approved allowance)")
        return 1

    from skillshift.update import configure_models

    configure_models(cfg)
    val_ids = [str(t["id"]) for t in load_tasks(cfg) if t["split"] == "val" and t.get("eligible_for_execution") is not False]
    for combo in pilot.GRID:
        used = sum(int(r["api_calls"] or 0) for r in ledger.rows())
        if used >= args.call_limit:
            print(f"call limit reached ({used} >= {args.call_limit}); stopping before {combo}")
            break
        pilot.run_pilot(cfg, pools=pools, attempts_root=args.attempts_root, out_root=args.out, ledger=ledger,
                        val_ids=val_ids, retry_partial=args.retry_partial, only=[combo])

    rows, missing = pilot.results_table(args.out, seed)
    print(json.dumps({"completed": len(rows), "missing": missing,
                      "consistency_problems": pilot.consistency_problems(args.out, seed)}, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
