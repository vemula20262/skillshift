"""Collect one evaluated original attempt per development task, resumably.

Reads the development task IDs from the task manifest, runs the shared starting
skill on each pending task in small chunks, and appends one cost.csv row per chunk.
Re-running continues where the last run stopped.

Examples:
  python3 scripts/collect_dev_attempts.py --check
  python3 scripts/collect_dev_attempts.py --call-limit 75
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift import config as _config  # noqa: E402
from skillshift.collection import Collector, coverage_problems, dev_task_ids  # noqa: E402
from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.usage import Ledger  # noqa: E402

BATCH = "dev_original"


def collection_calls(ledger: Ledger) -> int:
    return sum(int(r["api_calls"] or 0) for r in ledger.rows() if r["phase"] == "collection")


def prerequisite_problems(cfg: dict) -> list[str]:
    problems = []
    data_root = _config.resolve(cfg["dataset"]["data_root"])
    if not (data_root / "spreadsheet").is_dir():
        problems.append(f"workbook archive not extracted at {data_root} (see datasets/120/README.md)")
    if not os.environ.get(cfg["model"]["api_key_env"]):
        problems.append(f"{cfg['model']['api_key_env']} is not set")
    try:
        import skillopt  # noqa: F401
    except ImportError:
        problems.append("skillopt is not installed (pip install -r requirements.txt)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--attempts-root", type=Path, default=ROOT / "attempts")
    parser.add_argument("--cost-csv", type=Path, default=ROOT / "results" / "cost.csv")
    parser.add_argument("--chunk-size", type=int, default=None, help="tasks per chunk (default: executor.workers)")
    parser.add_argument("--max-chunks", type=int, default=None, help="stop after this many chunks")
    parser.add_argument("--max-infra-attempts", type=int, default=3)
    parser.add_argument("--call-limit", type=int, default=None,
                        help="team-approved API call allowance for collection, counted from collection rows in cost.csv")
    parser.add_argument("--check", action="store_true", help="report prerequisites and progress only; no model calls")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    from skillshift.update import load_tasks

    tasks = load_tasks(cfg)
    wanted = dev_task_ids(tasks)
    ledger = Ledger(args.cost_csv)
    problems = prerequisite_problems(cfg)

    def report(collector: Collector | None) -> dict:
        evaluated = collector.evaluated_ids() if collector else []
        status = collector.status(wanted) if collector else {"pending": wanted}
        return {
            "manifest_dev_tasks": len(wanted),
            "evaluated": len(set(evaluated) & set(wanted)),
            "pending": len(status["pending"]),
            "infra_failures": status.get("infra_failures", 0),
            "infra_exhausted": status.get("infra_exhausted", []),
            "coverage_problems": coverage_problems(wanted, evaluated),
            "collection_api_calls_so_far": collection_calls(ledger),
            "prerequisite_problems": problems,
        }

    skill = None
    if not problems:
        from skillshift.update import configure_models, starting_skill

        skill, _ = starting_skill(cfg)
    collector = Collector(cfg, tasks, skill or "", args.attempts_root, BATCH, ledger,
                          max_infra_attempts=args.max_infra_attempts) if not problems or args.check else None

    if args.check or problems:
        print(json.dumps(report(collector), indent=2))
        return 0 if args.check else 1
    if args.call_limit is None:
        print("refusing to make model calls without --call-limit (the team-approved allowance)")
        return 1

    configure_models(cfg)
    chunk = args.chunk_size or cfg["executor"]["workers"]
    # Each task makes at most max_turns successful target calls, so a chunk is sized
    # to fit what is left of the allowance and successful calls never pass the limit.
    per_task = max(int(cfg["executor"]["max_turns"]), 1)
    chunks = 0
    while args.max_chunks is None or chunks < args.max_chunks:
        used = collection_calls(ledger)
        room = (args.call_limit - used) // per_task
        if room <= 0:
            print(f"collection call limit reached ({used} of {args.call_limit}); stopping")
            break
        if not collector.status(wanted)["pending"]:
            break
        collector.run(wanted, min(chunk, room), max_chunks=1)
        chunks += 1

    final = report(collector)
    print(json.dumps(final, indent=2))
    return 0 if not final["coverage_problems"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
