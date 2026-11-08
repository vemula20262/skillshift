"""Provider usage ledger (cost.csv) shared by attempt collection and update runs.

Each row is one unit of work: a collection batch or one update run. Rows are
append-only and keyed by event_id, so re-running a report or resuming a job never
counts the same usage twice. Provider usage comes from SkillOpt's token tracker,
which records only calls that returned a response; requests that fail after all
retries are not observable there and are counted separately as infra failures.

feedback_tokens_estimate is the pipeline's own estimate of the feedback shown to
the optimizer (record token_count units). It is not provider usage and is never
added to the token totals.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

COLUMNS = (
    "event_id",
    "timestamp_utc",
    "phase",
    "label",
    "status",
    "api_calls",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "infra_failures",
    "feedback_tokens_estimate",
    "usage_by_stage",
    "note",
)
PHASES = ("collection", "update")
STATUSES = ("completed", "partial", "failed")


def usage_snapshot() -> dict:
    """Current SkillOpt token summary for this process ({} if skillopt is unavailable)."""
    try:
        from skillopt import model as sk_model
    except ImportError:
        return {}
    return sk_model.get_token_summary()


def reset_usage() -> None:
    try:
        from skillopt import model as sk_model
    except ImportError:
        return
    sk_model.reset_token_tracker()


def totals(summary: dict) -> dict:
    """Calls and tokens from a SkillOpt token summary, summed over stages."""
    stages = {k: v for k, v in summary.items() if k != "_total" and isinstance(v, dict)}
    calls = sum(int(v.get("calls", 0)) for v in stages.values())
    prompt = sum(int(v.get("prompt_tokens", 0)) for v in stages.values())
    completion = sum(int(v.get("completion_tokens", 0)) for v in stages.values())
    return {"api_calls": calls, "input_tokens": prompt, "output_tokens": completion,
            "total_tokens": prompt + completion}


class Ledger:
    """Append-only cost.csv with event_id deduplication."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def rows(self) -> list[dict]:
        if not self.path.is_file():
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def has(self, event_id: str) -> bool:
        return any(r["event_id"] == event_id for r in self.rows())

    def record(
        self,
        event_id: str,
        *,
        phase: str,
        label: str,
        status: str,
        summary: dict,
        infra_failures: int = 0,
        feedback_tokens_estimate: int | None = None,
        note: str = "",
    ) -> bool:
        """Append one row; returns False (and writes nothing) if event_id is already present."""
        if phase not in PHASES:
            raise ValueError(f"phase must be one of {PHASES}")
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if self.has(event_id):
            return False
        stages = {k: v for k, v in summary.items() if k != "_total"}
        row = {
            "event_id": event_id,
            "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "phase": phase,
            "label": label,
            "status": status,
            **totals(summary),
            "infra_failures": infra_failures,
            "feedback_tokens_estimate": "" if feedback_tokens_estimate is None else feedback_tokens_estimate,
            "usage_by_stage": json.dumps(stages, sort_keys=True, separators=(",", ":")),
            "note": note,
        }
        new_file = not self.path.is_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        return True


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens. None means no approved figure is available."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cap_usd: float | None = None

    @property
    def known(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if not self.known:
            return None
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1_000_000


def summarize(rows: list[dict], pricing: Pricing) -> dict:
    """Totals by phase and overall, with cost only when pricing is known."""
    def add(acc: dict, row: dict) -> None:
        for key in ("api_calls", "input_tokens", "output_tokens", "total_tokens", "infra_failures"):
            acc[key] = acc.get(key, 0) + int(row.get(key) or 0)
        acc["events"] = acc.get("events", 0) + 1

    by_phase: dict[str, dict] = {}
    overall: dict = {}
    for row in rows:
        add(by_phase.setdefault(row["phase"], {}), row)
        add(overall, row)
    for block in [*by_phase.values(), overall]:
        cost = pricing.cost(block.get("input_tokens", 0), block.get("output_tokens", 0))
        block["cost_usd"] = None if cost is None else round(cost, 4)
    out = {"overall": overall, "by_phase": by_phase,
           "pricing": {"input_per_mtok": pricing.input_per_mtok, "output_per_mtok": pricing.output_per_mtok},
           "cap_usd": pricing.cap_usd}
    if pricing.cap_usd and overall.get("cost_usd") is not None:
        out["cap_used_fraction"] = round(overall["cost_usd"] / pricing.cap_usd, 4)
    return out


def burn_chart_svg(rows: list[dict], pricing: Pricing, title: str = "Budget burn") -> str:
    """Cumulative measured usage per ledger event as a standalone SVG.

    Plots cost in USD when pricing is known, otherwise total tokens, and draws the
    cap line only when both pricing and a cap are set.
    """
    width, height, left, right, top, bottom = 720, 360, 80, 24, 48, 56
    use_cost = pricing.known
    series, running = [], 0.0
    for row in rows:
        if use_cost:
            running += pricing.cost(int(row["input_tokens"] or 0), int(row["output_tokens"] or 0))
        else:
            running += int(row["total_tokens"] or 0)
        series.append(running)
    cap = pricing.cap_usd if use_cost else None
    y_max = max([*series, cap or 0, 1e-9])
    plot_w, plot_h = width - left - right, height - top - bottom

    def x(i: int) -> float:
        return left + (plot_w * (i + 1) / max(len(series), 1))

    def y(v: float) -> float:
        return top + plot_h - plot_h * v / y_max

    unit = "Cumulative cost (USD)" if use_cost else "Cumulative tokens (pricing not set)"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="12">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="24" font-size="15" font-weight="bold">{_esc(title)}</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#444"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#444"/>',
        f'<text x="{left + plot_w / 2}" y="{height - 16}" text-anchor="middle">Ledger events (collection batches, update runs)</text>',
        f'<text transform="translate(18 {top + plot_h / 2}) rotate(-90)" text-anchor="middle">{unit}</text>',
    ]
    for frac in (0, 0.5, 1):
        v = y_max * frac
        label = f"${v:,.2f}" if use_cost else f"{v:,.0f}"
        parts.append(f'<text x="{left - 6}" y="{y(v) + 4}" text-anchor="end">{label}</text>')
    if cap:
        parts.append(f'<line x1="{left}" y1="{y(cap)}" x2="{left + plot_w}" y2="{y(cap)}" '
                     f'stroke="#c0392b" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{left + plot_w - 4}" y="{y(cap) - 6}" text-anchor="end" fill="#c0392b">cap ${cap:,.2f}</text>')
    if series:
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(series))
        parts.append(f'<polyline points="{left},{y(0):.1f} {points}" fill="none" stroke="#2c6fbb" stroke-width="2"/>')
        for i, (v, row) in enumerate(zip(series, rows)):
            color = "#2c6fbb" if row["phase"] == "update" else "#27ae60"
            parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" fill="{color}"/>')
    else:
        parts.append(f'<text x="{left + plot_w / 2}" y="{top + plot_h / 2}" text-anchor="middle">No measured usage yet</text>')
    parts.append(f'<circle cx="{left + 8}" cy="{top - 10}" r="4" fill="#27ae60"/>'
                 f'<text x="{left + 16}" y="{top - 6}">collection</text>'
                 f'<circle cx="{left + 98}" cy="{top - 10}" r="4" fill="#2c6fbb"/>'
                 f'<text x="{left + 106}" y="{top - 6}">update</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
