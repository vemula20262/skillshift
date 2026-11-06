"""Run one single-update experiment: feedback pool + selector -> gated child skill.

Example:
  python3 scripts/run_update.py --pool pools/C3_50.jsonl --selector source_family
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.update import configure_models, run_update  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", required=True, type=Path, help="pool JSONL from scripts/build_pools.py")
    parser.add_argument("--selector", required=True, help="selector name from config 'selectors'")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--attempts-root", type=Path, default=ROOT / "attempts",
                        help="directory that record trajectory_path values are relative to")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--seed", type=int, default=None, help="overrides config seed")
    parser.add_argument("--val-ids", nargs="*", default=None, help="restrict validation tasks (pilot only)")
    parser.add_argument("--test-ids", nargs="*", default=None, help="restrict test tasks (pilot only)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    configure_models(cfg)
    log = run_update(
        cfg,
        pool_path=args.pool,
        selector_name=args.selector,
        attempts_root=args.attempts_root,
        out_root=args.out,
        seed=args.seed,
        val_ids=args.val_ids,
        test_ids=args.test_ids,
    )
    gate = log["gate"]
    print(json.dumps({
        "run_id": log["run_id"],
        "edited": log["edited"],
        "accepted": gate["accepted"],
        "val_parent": f"{gate['parent_solved']}/{gate['n_tasks']}",
        "val_child": f"{gate['child_solved']}/{gate['n_tasks']}",
        "feedback_tokens": log["feedback_tokens"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
