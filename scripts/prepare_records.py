"""Build attempts/records.jsonl from the collected development attempts.

Adds a fixed-template behavior summary to each record, then checks that the file is
schema-valid, covers exactly the manifest's development tasks once each, has no
empty summaries, and can be consumed by the pilot selectors. The file is written
only if every check passes; the printed checksum identifies it for pool building.

Example:
  python3 scripts/prepare_records.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift.collection import build_records, dev_task_ids, record_problems  # noqa: E402
from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.update import load_tasks  # noqa: E402

BATCH = "dev_original"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--attempts-root", type=Path, default=ROOT / "attempts")
    parser.add_argument("--batch", default=BATCH)
    parser.add_argument("--output", type=Path, default=None, help="default: <attempts-root>/records.jsonl")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    tasks = load_tasks(cfg)
    expected = dev_task_ids(tasks)
    records = build_records(cfg, tasks, args.attempts_root, args.batch)
    problems = record_problems(records, expected, cfg["selectors"], budget=cfg["feedback"]["token_budget"])
    if problems:
        print(f"records not written: {len(problems)} problem(s)")
        for p in problems[:50]:
            print(f"  {p}")
        return 1

    output = args.output or args.attempts_root / "records.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    solved = sum(r["outcome"] == "success" for r in records)
    summary = {
        "path": str(output),
        "sha256": digest,
        "records": len(records),
        "tasks": len({r["task_id"] for r in records}),
        "families": len({r["source_family"] for r in records}),
        "success": solved,
        "failure": len(records) - solved,
        "trajectories": str(args.attempts_root / "raw" / args.batch),
    }
    (output.parent / "records_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
