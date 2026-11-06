"""Run the executor on development tasks and turn the results into attempt records.

Fills the fields that follow directly from a rollout. summary and embedding stay
null for the trajectory parser.
"""
from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

from skillshift import config as _config
from skillshift.schema import record_from_rollout, validate_records


def env_version(cfg: dict) -> str:
    """Identifies the executor setup an attempt was produced with."""
    try:
        skillopt_version = metadata.version("skillopt")
    except metadata.PackageNotFoundError:
        skillopt_version = "source"
    return f"skillopt-{skillopt_version}/{cfg['model']['target_model']}/{cfg['executor']['mode']}"


def collect_attempts(
    cfg: dict,
    tasks: list[dict],
    task_ids: list[str],
    skill: str,
    attempts_root: Path,
    batch_name: str,
    feedback_source: str = "original",
) -> list[dict]:
    """Run each task once with `skill` and return schema-valid attempt records.

    Trajectories are written under attempts_root/raw/<batch_name>/predictions/<task_id>/.
    """
    from skillopt.envs.spreadsheetbench.rollout import run_spreadsheet_batch_codegen

    from skillshift.update import task_items

    batch_dir = attempts_root / "raw" / batch_name
    ex = cfg["executor"]
    results = run_spreadsheet_batch_codegen(
        items=task_items(tasks, "dev", task_ids),
        data_root=str(_config.resolve(cfg["dataset"]["data_root"])),
        out_root=str(batch_dir),
        skill_content=skill,
        mode=ex["mode"],
        max_turns=ex["max_turns"],
        max_completion_tokens=ex["max_completion_tokens"],
        max_api_workers=ex["workers"],
        task_timeout=ex["exec_timeout"],
    )
    with open(batch_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return records_from_results(cfg, tasks, results, attempts_root, batch_name, feedback_source)


def records_from_results(
    cfg: dict,
    tasks: list[dict],
    results: list[dict],
    attempts_root: Path,
    batch_name: str,
    feedback_source: str = "original",
) -> list[dict]:
    """Turn rollout results stored under attempts_root/raw/<batch_name>/ into validated records."""
    from skillopt.gradient.reflect import fmt_minibatch_trajectories

    batch_dir = attempts_root / "raw" / batch_name
    by_id = {str(t["id"]): t for t in tasks}
    version = env_version(cfg)
    records = []
    for result in sorted(results, key=lambda r: str(r["id"])):
        task = by_id[str(result["id"])]
        trajectory = batch_dir / "predictions" / str(result["id"])
        conversation_path = trajectory / "conversation.json"
        conversation = json.loads(conversation_path.read_text()) if conversation_path.is_file() else []
        records.append(record_from_rollout(
            result,
            record_id=f"{batch_name}-{result['id']}",
            source_family=task["family_id"],
            workbook_hash=task["initial_audit"]["sha256"],
            env_version=version,
            feedback_source=feedback_source,
            trajectory_path=str(trajectory.relative_to(attempts_root)),
            conversation=conversation,
            feedback_text=fmt_minibatch_trajectories([result], str(batch_dir / "predictions")),
        ))
    problems = validate_records(records)
    if problems:
        raise ValueError("collected records failed validation:\n  " + "\n  ".join(problems[:20]))
    return records
