"""Load and check config/config.yaml."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "config.yaml"

_SCHEMA: dict[str, dict[str, tuple[type, ...]]] = {
    "dataset": {"version": (str,), "task_manifest": (str,), "data_root": (str,)},
    "model": {
        "base_url": (str, type(None)),
        "api_key_env": (str,),
        "optimizer_model": (str, type(None)),
        "target_model": (str, type(None)),
        "reasoning_effort": (str, type(None)),
    },
    "executor": {
        "mode": (str,),
        "max_turns": (int,),
        "max_completion_tokens": (int,),
        "exec_timeout": (int,),
        "workers": (int,),
    },
    "skill": {"starting_skill": (str, type(None))},
    "feedback": {
        "token_budget": (int,),
        "failure_only": (bool,),
        "minibatch_size": (int,),
        "edit_budget": (int,),
    },
    "gate": {"margin_tasks": (int,)},
    "evaluation": {"test_policy": (str,)},
}


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    problems = check_config(cfg)
    if problems:
        raise ValueError("invalid config:\n  " + "\n  ".join(problems))
    return cfg


def check_config(cfg: object) -> list[str]:
    if not isinstance(cfg, dict):
        return ["config must be a mapping"]
    problems: list[str] = []
    for section, fields in _SCHEMA.items():
        block = cfg.get(section)
        if not isinstance(block, dict):
            problems.append(f"missing section: {section}")
            continue
        for name, types in fields.items():
            if name not in block:
                problems.append(f"missing {section}.{name}")
                continue
            value = block[name]
            if isinstance(value, bool) and bool not in types:
                problems.append(f"{section}.{name}: bool is not allowed")
            elif not isinstance(value, types):
                problems.append(f"{section}.{name}: wrong type {type(value).__name__}")
    if not isinstance(cfg.get("seed"), int) or isinstance(cfg.get("seed"), bool):
        problems.append("seed must be an integer")
    selectors = cfg.get("selectors")
    if not isinstance(selectors, dict) or not selectors:
        problems.append("selectors must map at least one name to 'module:attribute'")
    else:
        for name, entry in selectors.items():
            spec = entry.get("spec") if isinstance(entry, dict) else entry
            if not isinstance(spec, str) or ":" not in spec:
                problems.append(f"selectors.{name}: expected 'module:attribute' or {{spec, kwargs}}")
            elif isinstance(entry, dict) and not isinstance(entry.get("kwargs", {}), dict):
                problems.append(f"selectors.{name}.kwargs must be a mapping")
    if problems:
        return problems

    if cfg["executor"]["mode"] not in ("single", "multi"):
        problems.append("executor.mode must be 'single' or 'multi'")
    if cfg["evaluation"]["test_policy"] not in ("accepted", "all", "none"):
        problems.append("evaluation.test_policy must be accepted, all or none")
    if cfg["gate"]["margin_tasks"] < 1:
        problems.append("gate.margin_tasks must be at least 1")
    for name in ("token_budget", "minibatch_size", "edit_budget"):
        if cfg["feedback"][name] < 1:
            problems.append(f"feedback.{name} must be positive")
    for name in ("max_turns", "max_completion_tokens", "exec_timeout", "workers"):
        if cfg["executor"][name] < 1:
            problems.append(f"executor.{name} must be positive")
    return problems


def config_hash(cfg: dict) -> str:
    """Stable hash of the settings, used to tag runs and cache parent scores."""
    canonical = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve(path: str, root: Path = REPO_ROOT) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p
