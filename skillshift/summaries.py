"""Fixed-template behavior summaries for attempt records.

The summary describes what the agent did and how the evaluator judged it, using only
fields already on the record plus the generated code. It is deterministic: the same
record and code always give the same text. Identifiers (record, task, family, hashes,
paths) stay in their structured fields and never appear in the summary, so two
attempts that behaved the same way get the same summary even on different tasks.
"""
from __future__ import annotations

import ast
import re

_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}")
_QUOTED = re.compile(r"('[^']*'|\"[^\"]*\")")
_CELL = re.compile(r"\$?\b[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?\b")
_NUMBER = re.compile(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?")
_SPACE = re.compile(r"\s+")


def normalize_reason(fail_reason: str, limit: int = 160) -> str:
    """Strip paths, quoted values, cell references and numbers so the reason reflects the kind of failure."""
    text = _PATH.sub("<path>", fail_reason or "")
    text = _QUOTED.sub("<value>", text)
    text = _CELL.sub("<cell>", text)
    text = _NUMBER.sub("<n>", text)
    text = _SPACE.sub(" ", text).strip()
    return text[:limit].rstrip()


def code_features(code: str | None) -> list[str]:
    """Sorted top-level modules the generated code imports, or a parse marker."""
    if code is None:
        return []
    if not code.strip():
        return ["no code"]
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ["unparseable code"]
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return sorted(modules)


def _events(tool_events: list) -> str:
    names = [e if isinstance(e, str) else str(e.get("type", e.get("name", "event"))) for e in tool_events]
    return " -> ".join(names) if names else "none"


def behavior_summary(record: dict, code: str | None = None) -> str:
    """One-paragraph summary in a fixed field order."""
    outcome = record["outcome"]
    category = record["error_category"]
    detail = record.get("error_detail", "")
    lines = [
        f"Outcome: {outcome}.",
        f"Error category: {category}{f' ({detail})' if detail else ''}.",
        f"Task type: {record.get('task_type') or 'unspecified'}.",
        f"Turns: {record['n_turns']}.",
        f"Events: {_events(record['tool_events'])}.",
    ]
    features = code_features(code)
    if code is not None:
        lines.append(f"Code imports: {', '.join(features) if features else 'none'}.")
    if outcome == "failure":
        reason = normalize_reason(record.get("fail_reason", ""))
        lines.append(f"Evaluator: {reason or 'no reason given'}.")
    else:
        lines.append("Evaluator: all checked answer cells matched.")
    return " ".join(lines)
