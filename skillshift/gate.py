"""Validation gate for a single skill update.

The child skill is kept only if it solves at least `margin_tasks` more validation
tasks than its parent, both scored on the same validation tasks with the hard
(all test cases pass) metric. With margin_tasks = 1 this is strict improvement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    reason: str
    margin_tasks: int
    n_tasks: int
    parent_solved: int
    child_solved: int
    parent_score: float
    child_score: float
    child_only_wins: list[str]
    parent_only_wins: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def per_task_hard(results: list[dict]) -> dict[str, int]:
    """Map task id -> 1/0 from SkillOpt rollout results; duplicate ids are an error."""
    scores: dict[str, int] = {}
    for result in results:
        task_id = str(result["id"])
        if task_id in scores:
            raise ValueError(f"duplicate result for task {task_id}")
        scores[task_id] = 1 if result.get("hard") else 0
    return scores


def decide(parent: dict[str, int], child: dict[str, int], margin_tasks: int) -> GateDecision:
    """Compare parent and child per-task scores on the same task set."""
    if margin_tasks < 1:
        raise ValueError("margin_tasks must be at least 1")
    if set(parent) != set(child):
        missing = sorted(set(parent) ^ set(child))
        raise ValueError(f"parent and child were scored on different tasks: {missing[:5]}")
    if not parent:
        raise ValueError("no validation tasks were scored")

    n = len(parent)
    parent_solved = sum(parent.values())
    child_solved = sum(child.values())
    child_only = sorted(t for t in parent if child[t] and not parent[t])
    parent_only = sorted(t for t in parent if parent[t] and not child[t])
    gain = child_solved - parent_solved
    accepted = gain >= margin_tasks
    reason = (
        f"child solved {gain:+d} tasks vs parent (needs >= +{margin_tasks})"
    )
    return GateDecision(
        accepted=accepted,
        reason=reason,
        margin_tasks=margin_tasks,
        n_tasks=n,
        parent_solved=parent_solved,
        child_solved=child_solved,
        parent_score=parent_solved / n,
        child_score=child_solved / n,
        child_only_wins=child_only,
        parent_only_wins=parent_only,
    )


def no_edit_decision(parent: dict[str, int], margin_tasks: int) -> GateDecision:
    """Decision recorded when the optimizer produced no applicable edit."""
    n = len(parent)
    solved = sum(parent.values())
    return GateDecision(
        accepted=False,
        reason="no applicable edit; skill unchanged",
        margin_tasks=margin_tasks,
        n_tasks=n,
        parent_solved=solved,
        child_solved=solved,
        parent_score=solved / n if n else 0.0,
        child_score=solved / n if n else 0.0,
        child_only_wins=[],
        parent_only_wins=[],
    )
