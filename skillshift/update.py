"""Single-update SkillOpt pipeline for one (feedback pool, selector) pair.

Stages, in order:
  1. load and validate the pool's attempt records
  2. run the selector, then sample its weighted output into the fixed token budget
  3. hand the sampled trajectories to SkillOpt's reflect -> merge -> select stages
  4. apply the resulting edits to the parent skill
  5. score parent and child on the validation split and apply the gate
  6. score the test split per evaluation.test_policy, written to a sealed file

The executor, optimizer, prompts, starting skill and budgets come from the config and
are identical for every selector.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
from pathlib import Path

from skillshift import config as _config
from skillshift.gate import decide, no_edit_decision, per_task_hard
from skillshift.sampling import sample_to_budget
from skillshift.schema import load_jsonl, validate_records
from skillshift.selection import load_selector, normalise_output

TRAJECTORY_FILES = (
    "conversation.json",
    "target_system_prompt.txt",
    "target_user_prompt.txt",
    "spreadsheet_preview.txt",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Model and task setup ─────────────────────────────────────────────────────


def configure_models(cfg: dict) -> None:
    """Point SkillOpt's optimizer and target at the configured OpenAI-compatible endpoint."""
    m = cfg["model"]
    missing = [k for k in ("base_url", "optimizer_model", "target_model") if not m.get(k)]
    if missing:
        raise ValueError(f"model settings not filled in: {', '.join(missing)}")

    from skillopt import model as sk_model

    api_key = os.environ.get(m["api_key_env"], "")
    sk_model.set_backend("openai_chat")
    sk_model.configure_azure_openai(endpoint=m["base_url"], auth_mode="openai_compatible", api_key=api_key or None)
    sk_model.set_optimizer_deployment(m["optimizer_model"])
    sk_model.set_target_deployment(m["target_model"])
    sk_model.set_reasoning_effort(m.get("reasoning_effort"))


def starting_skill(cfg: dict) -> tuple[str, str]:
    """Return (skill text, source description)."""
    path = cfg["skill"]["starting_skill"]
    if path:
        p = _config.resolve(path)
        return p.read_text(encoding="utf-8"), str(path)
    import skillopt

    p = Path(skillopt.__file__).parent / "envs" / "spreadsheetbench" / "skills" / "initial.md"
    return p.read_text(encoding="utf-8"), "skillopt:envs/spreadsheetbench/skills/initial.md"


def load_tasks(cfg: dict) -> list[dict]:
    with open(_config.resolve(cfg["dataset"]["task_manifest"]), encoding="utf-8") as f:
        tasks = json.load(f)
    if not isinstance(tasks, list):
        raise ValueError("task manifest must be a JSON array")
    return tasks


def task_items(tasks: list[dict], split: str, limit_ids: list[str] | None = None) -> list[dict]:
    """SkillOpt SpreadsheetBench items for one split, in manifest order."""
    wanted = set(limit_ids) if limit_ids is not None else None
    items = []
    for task in tasks:
        if task.get("split") != split or task.get("eligible_for_execution") is False:
            continue
        if wanted is not None and str(task["id"]) not in wanted:
            continue
        items.append({
            "id": str(task["id"]),
            "instruction": task["instruction"],
            "instruction_type": task.get("instruction_type", ""),
            "answer_position": task.get("answer_position", ""),
            "spreadsheet_path": task.get("spreadsheet_path", f"spreadsheet/{task['id']}"),
        })
    if wanted is not None and len(items) != len(wanted):
        found = {i["id"] for i in items}
        raise ValueError(f"tasks not found in split {split}: {sorted(wanted - found)[:5]}")
    return items


def _eval_settings_hash(cfg: dict) -> str:
    """Hash of the settings that affect a skill's score, so cached scores stay valid."""
    relevant = {k: cfg[k] for k in ("dataset", "model", "executor")}
    return _config.config_hash(relevant)


def evaluate_skill(cfg: dict, skill: str, items: list[dict], cache_root: Path, split: str) -> list[dict]:
    """Run the executor on every item with this skill. Results are cached on disk."""
    from skillopt.envs.spreadsheetbench.rollout import run_spreadsheet_batch_codegen

    out_dir = cache_root / _eval_settings_hash(cfg) / split / sha256_text(skill)[:16]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "skill.md").write_text(skill, encoding="utf-8")
    ex = cfg["executor"]
    results = run_spreadsheet_batch_codegen(
        items=items,
        data_root=str(_config.resolve(cfg["dataset"]["data_root"])),
        out_root=str(out_dir),
        skill_content=skill,
        mode=ex["mode"],
        max_turns=ex["max_turns"],
        max_completion_tokens=ex["max_completion_tokens"],
        max_api_workers=ex["workers"],
        task_timeout=ex["exec_timeout"],
    )
    # The batch runner resumes from results.jsonl but leaves writing it to the caller.
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    wanted = {i["id"] for i in items}
    return [r for r in results if str(r["id"]) in wanted]


# ── Feedback ─────────────────────────────────────────────────────────────────


def materialize_feedback(sampled: list, attempts_root: Path, prediction_dir: Path) -> list[dict]:
    """Lay out the sampled trajectories the way SkillOpt's reflect stage reads them.

    Each pool occurrence gets its own directory, so a repeated record is shown to
    the optimizer once per occurrence, exactly as the selector and sampler chose.
    """
    from skillopt.envs.task_output import task_output_segment

    prediction_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for item in sampled:
        record = item.record
        occurrence_id = record.get("pool_record_id", record["record_id"])
        source = (attempts_root / record["trajectory_path"]).resolve()
        if not source.is_relative_to(attempts_root.resolve()):
            raise ValueError(f"trajectory_path escapes the attempts root: {record['trajectory_path']}")
        if not (source / "conversation.json").is_file():
            raise FileNotFoundError(f"missing conversation.json for record {record['record_id']} at {source}")
        target = prediction_dir / task_output_segment(occurrence_id, map_unsafe=True)
        target.mkdir(parents=True, exist_ok=True)
        for name in TRAJECTORY_FILES:
            if (source / name).is_file():
                shutil.copyfile(source / name, target / name)
        success = record["outcome"] == "success"
        results.append({
            "id": occurrence_id,
            "hard": 1 if success else 0,
            "soft": 1.0 if success else 0.0,
            "task_description": record["instruction"],
            "task_type": record["task_type"],
            "fail_reason": "" if success else record["fail_reason"],
            "n_turns": record["n_turns"],
        })
    return results


def _split_patches(raw_patches: list) -> tuple[list[dict], list[dict]]:
    """Unwrap analyst output into failure and success patch lists.

    Mirrors skillopt.engine.trainer._normalise_patches for the default patch mode.
    """
    failure: list[dict] = []
    success: list[dict] = []
    for p in raw_patches:
        if not isinstance(p, dict):
            continue
        inner = p.get("patch", p)
        if not isinstance(inner, dict):
            continue
        edits = inner.get("edits")
        if not isinstance(edits, list) or not edits:
            continue
        support = max(int(p.get("batch_size", 0) or 0), 1)
        for edit in edits:
            if isinstance(edit, dict):
                edit.setdefault("source_type", p.get("source_type", "failure"))
                edit.setdefault("support_count", support)
        (success if p.get("source_type", "failure") == "success" else failure).append(inner)
    return failure, success


def propose_edit(cfg: dict, skill: str, results: list[dict], prediction_dir: Path, work_dir: Path, seed: int) -> dict:
    """Run SkillOpt's reflect, merge and select stages and apply the edits once."""
    from skillopt.gradient.aggregate import merge_patches
    from skillopt.gradient.reflect import run_minibatch_reflect
    from skillopt.optimizer.clip import rank_and_select
    from skillopt.optimizer.skill import apply_patch_with_report

    fb = cfg["feedback"]
    raw = run_minibatch_reflect(
        results=results,
        skill_content=skill,
        prediction_dir=str(prediction_dir),
        patches_dir=str(work_dir / "patches"),
        workers=cfg["executor"]["workers"],
        failure_only=fb["failure_only"],
        minibatch_size=fb["minibatch_size"],
        edit_budget=fb["edit_budget"],
        random_seed=seed,
    )
    failure, success = _split_patches(raw)
    if not failure and not success:
        return {"candidate": skill, "patch": {"edits": []}, "apply_report": [], "n_raw_patches": len(raw)}
    merged = merge_patches(skill, failure, success, workers=cfg["executor"]["workers"], verbose=False)
    selected = rank_and_select(skill, merged, max_edits=fb["edit_budget"])
    candidate, report = apply_patch_with_report(skill, selected)
    return {"candidate": candidate, "patch": selected, "apply_report": report, "n_raw_patches": len(raw)}


# ── Orchestration ────────────────────────────────────────────────────────────


def run_update(
    cfg: dict,
    *,
    pool_path: Path,
    selector_name: str,
    attempts_root: Path,
    out_root: Path,
    seed: int | None = None,
    val_ids: list[str] | None = None,
    test_ids: list[str] | None = None,
) -> dict:
    """Run one update and return the run log. val_ids/test_ids restrict splits for pilots."""
    from skillopt import model as sk_model

    seed = cfg["seed"] if seed is None else seed
    if selector_name not in cfg["selectors"]:
        raise KeyError(f"selector {selector_name!r} is not listed in config selectors")

    pool = load_jsonl(pool_path)
    problems = validate_records(pool)
    if problems:
        raise ValueError("pool failed schema validation:\n  " + "\n  ".join(problems[:20]))
    if not pool:
        raise ValueError("pool is empty")

    run_id = f"{pool_path.stem}__{selector_name}__seed{seed}"
    run_dir = out_root / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"{run_dir} already exists; remove it or use another seed")
    run_dir.mkdir(parents=True)
    sk_model.reset_token_tracker()

    # Selection and sampling
    select = load_selector(cfg["selectors"][selector_name])
    budget = cfg["feedback"]["token_budget"]
    records, weights = normalise_output(select(pool, budget), pool)
    sampled = sample_to_budget(records, weights, budget, seed)
    selection = [
        {
            "occurrence_id": s.record.get("pool_record_id", s.record["record_id"]),
            "record_id": s.record["record_id"],
            "task_id": s.record["task_id"],
            "source_family": s.record["source_family"],
            "outcome": s.record["outcome"],
            "weight": s.weight,
            "token_count": s.record["token_count"],
        }
        for s in sampled
    ]
    _write_json(run_dir / "selection.json", selection)

    # Proposed edit
    parent, parent_source = starting_skill(cfg)
    feedback_results = materialize_feedback(sampled, attempts_root, run_dir / "feedback" / "predictions")
    proposal = propose_edit(cfg, parent, feedback_results, run_dir / "feedback" / "predictions", run_dir, seed)
    child = proposal["candidate"]
    (run_dir / "child_skill.md").write_text(child, encoding="utf-8")
    _write_json(run_dir / "patch.json", proposal["patch"])
    _write_json(run_dir / "apply_report.json", proposal["apply_report"])
    edited = child != parent

    # Validation gate
    tasks = load_tasks(cfg)
    cache_root = out_root / "eval_cache"
    val_items = task_items(tasks, "val", val_ids)
    parent_val = per_task_hard(evaluate_skill(cfg, parent, val_items, cache_root, "val"))
    margin = cfg["gate"]["margin_tasks"]
    if edited:
        child_val = per_task_hard(evaluate_skill(cfg, child, val_items, cache_root, "val"))
        decision = decide(parent_val, child_val, margin)
    else:
        decision = no_edit_decision(parent_val, margin)

    # Sealed test evaluation
    policy = cfg["evaluation"]["test_policy"]
    sealed = None
    if edited and (policy == "all" or (policy == "accepted" and decision.accepted)):
        test_items = task_items(tasks, "test", test_ids)
        parent_test = per_task_hard(evaluate_skill(cfg, parent, test_items, cache_root, "test"))
        child_test = per_task_hard(evaluate_skill(cfg, child, test_items, cache_root, "test"))
        sealed = {"run_id": run_id, "parent": parent_test, "child": child_test}
        sealed_dir = out_root / "sealed"
        sealed_dir.mkdir(parents=True, exist_ok=True)
        _write_json(sealed_dir / f"{run_id}.json", sealed)

    log = {
        "run_id": run_id,
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "pool": str(pool_path),
        "pool_sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
        "selector": selector_name,
        "selector_spec": cfg["selectors"][selector_name],
        "seed": seed,
        "config_hash": _config.config_hash(cfg),
        "dataset_version": cfg["dataset"]["version"],
        "models": {"optimizer": cfg["model"]["optimizer_model"], "target": cfg["model"]["target_model"]},
        "parent_skill_source": parent_source,
        "parent_skill_sha256": sha256_text(parent),
        "child_skill_sha256": sha256_text(child),
        "pool_occurrences": len(pool),
        "selector_kept": len(records),
        "sampled": len(sampled),
        "feedback_tokens": sum(s.record["token_count"] for s in sampled),
        "token_budget": budget,
        "n_raw_patches": proposal["n_raw_patches"],
        "n_edits": len(proposal["patch"].get("edits", [])),
        "edited": edited,
        "gate": decision.to_dict(),
        "test_evaluated": sealed is not None,
        "val_task_ids": sorted(parent_val),
        "api_usage": sk_model.get_token_summary(),
    }
    _write_json(run_dir / "run.json", log)
    return log


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
