"""End-to-end smoke test on the 10 pilot tasks with the configured model.

Checks the model endpoint, collects one attempt per pilot task, builds a no-repeat
pool with scripts/build_pools.py, and runs one update with the pass-through
selector against the validation split. The test split is not evaluated.

Example:
  export GEMINI_API_KEY=...
  python3 scripts/smoke_test.py
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift.attempts import collect_attempts  # noqa: E402
from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.update import configure_models, load_tasks, run_update, starting_skill  # noqa: E402

POOL_NAME = "smoke_C0"


def check_endpoint() -> None:
    """One short call so a bad key, model name or parameter fails fast."""
    from skillopt.model import chat_optimizer

    try:
        chat_optimizer(system="Reply with the single word OK.", user="ping",
                       max_completion_tokens=64, retries=1, stage="preflight")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"model endpoint check failed: {exc}") from None


def build_pool(records: list[dict], tasks: list[dict], pool_dir: Path) -> Path:
    spec = importlib.util.spec_from_file_location("build_pools", ROOT / "scripts" / "build_pools.py")
    build_pools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pools)
    config = build_pools.apply_task_manifest({
        "status": "approved",
        "dominant_task_ids": [records[0]["task_id"]],
        "pools": [{"name": POOL_NAME, "mechanism": "exact_copy", "repeat_fraction": 0}],
    }, tasks)
    pool = build_pools.build_pools(records, config)[POOL_NAME]["records"]
    pool_dir.mkdir(parents=True, exist_ok=True)
    path = pool_dir / f"{POOL_NAME}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pool), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "smoke")
    parser.add_argument("--tasks", type=int, default=10, help="number of pilot tasks to use")
    parser.add_argument("--val-limit", type=int, default=None, help="score only the first N validation tasks")
    args = parser.parse_args(argv)

    cfg = copy.deepcopy(load_config(args.config))
    cfg["evaluation"]["test_policy"] = "none"
    if args.out.exists():
        raise SystemExit(f"{args.out} already exists; remove it or pass --out")
    started = time.time()

    configure_models(cfg)
    check_endpoint()
    print("model endpoint OK")

    tasks = load_tasks(cfg)
    pilot = json.loads((ROOT / "datasets" / "120" / "pilot_10.json").read_text())[: args.tasks]
    skill, _ = starting_skill(cfg)
    attempts_root = args.out / "attempts"
    records = collect_attempts(cfg, tasks, pilot, skill, attempts_root, "smoke")
    solved = sum(r["outcome"] == "success" for r in records)
    print(f"collected {len(records)} attempts, {solved} solved")

    pool_path = build_pool(records, tasks, args.out / "pools")
    val_ids = None
    if args.val_limit:
        val_ids = [t["id"] for t in tasks if t["split"] == "val"][: args.val_limit]
    log = run_update(cfg, pool_path=pool_path, selector_name="passthrough", attempts_root=attempts_root,
                     out_root=args.out, val_ids=val_ids)

    gate = log["gate"]
    summary = {
        "run_id": log["run_id"],
        "models": log["models"],
        "pilot_tasks": pilot,
        "attempts_solved": f"{solved}/{len(records)}",
        "feedback_tokens": log["feedback_tokens"],
        "edits_applied": log["n_edits"],
        "val_parent": f"{gate['parent_solved']}/{gate['n_tasks']}",
        "val_child": f"{gate['child_solved']}/{gate['n_tasks']}",
        "accepted": gate["accepted"],
        "api_calls": log["api_usage"].get("_total", {}).get("calls"),
        "api_tokens": log["api_usage"].get("_total", {}).get("total_tokens"),
        "minutes": round((time.time() - started) / 60, 1),
    }
    (args.out / "smoke_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
