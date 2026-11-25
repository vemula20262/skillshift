"""Write the pilot results table, cost summary and budget burn chart from measured data.

The table is built only from completed run.json files; the cost figures come only
from cost.csv. Dollar amounts appear only when pricing is passed in; otherwise the
summary reports measured usage and marks the cost as not set.

Example:
  python3 scripts/pilot_report.py --price-input 0.30 --price-output 2.50 --cap-usd 50
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillshift import pilot  # noqa: E402
from skillshift.config import DEFAULT_CONFIG, load_config  # noqa: E402
from skillshift.usage import Ledger, Pricing, burn_chart_svg, summarize  # noqa: E402


def markdown_table(rows: list[dict], columns: tuple[str, ...]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in columns) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "pilot")
    parser.add_argument("--cost-csv", type=Path, default=ROOT / "results" / "cost.csv")
    parser.add_argument("--report-dir", type=Path, default=None, help="default: <out>/report")
    parser.add_argument("--price-input", type=float, default=None, help="approved USD per 1M input tokens")
    parser.add_argument("--price-output", type=float, default=None, help="approved USD per 1M output tokens")
    parser.add_argument("--cap-usd", type=float, default=None, help="approved API budget cap in USD")
    args = parser.parse_args(argv)

    seed = load_config(args.config)["seed"]
    report_dir = args.report_dir or args.out / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    rows, missing = pilot.results_table(args.out, seed)
    with open(report_dir / "pilot_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=pilot.TABLE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    consistency = pilot.consistency_problems(args.out, seed)
    notes = [f"Completed runs: {len(rows)} of {len(pilot.GRID)}."]
    if missing:
        notes.append("Missing combinations: " + ", ".join(missing) + ".")
    notes += [f"Consistency problem: {p}." for p in consistency]
    (report_dir / "pilot_results.md").write_text(
        "# Pilot results (validation only)\n\n" + markdown_table(rows, pilot.TABLE_COLUMNS) + "\n"
        + "\n".join(notes) + "\n", encoding="utf-8")

    pricing = Pricing(args.price_input, args.price_output, args.cap_usd)
    ledger_rows = Ledger(args.cost_csv).rows()
    summary = summarize(ledger_rows, pricing)
    summary["notes"] = [
        "Provider usage counts only calls that returned a response; requests that failed after all retries "
        "are not reported by the tracker and appear as infra_failures on collection rows.",
        "feedback_tokens_estimate is the pipeline's feedback size estimate, not provider usage.",
    ]
    if not pricing.known:
        summary["notes"].append("Pricing not set: cost in USD is not reported.")
    if pricing.cap_usd is None:
        summary["notes"].append("Budget cap not set.")
    (report_dir / "cost_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (report_dir / "budget_burn.svg").write_text(
        burn_chart_svg(ledger_rows, pricing, title="SkillShift API usage to date"), encoding="utf-8")

    print(json.dumps({"report_dir": str(report_dir), "completed_runs": len(rows), "missing": missing,
                      "consistency_problems": consistency, "cost": summary["overall"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
