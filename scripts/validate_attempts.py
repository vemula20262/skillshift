"""Check attempt or pool JSONL files against the shared attempt record schema.

Example:
  python3 scripts/validate_attempts.py attempts/records.jsonl
  python3 scripts/validate_attempts.py pools/C3_50.jsonl --require-derived
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillshift.schema import load_jsonl, validate_records  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--require-derived", action="store_true",
                        help="also require summary and embedding to be filled in")
    args = parser.parse_args()

    failed = False
    for path in args.paths:
        try:
            records = load_jsonl(path)
        except (OSError, ValueError) as exc:
            print(f"{path}: {exc}")
            failed = True
            continue
        errors = validate_records(records, require_derived=args.require_derived)
        if errors:
            failed = True
            print(f"{path}: {len(errors)} problem(s)")
            for err in errors[:50]:
                print(f"  {err}")
            if len(errors) > 50:
                print(f"  ... {len(errors) - 50} more")
        else:
            print(f"{path}: {len(records)} records OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
