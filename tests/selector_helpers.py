"""Synthetic feedback fixtures for selector tests."""
import importlib.util
from pathlib import Path

# Load scripts/build_pools.py by path: an installed package named "scripts"
# (SkillOpt ships one) would otherwise shadow the repo's scripts folder.
_spec = importlib.util.spec_from_file_location(
    "build_pools", Path(__file__).resolve().parents[1] / "scripts" / "build_pools.py")
build_pools_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_pools_module)

def record(i, family="A", summary="Wrong range", vector=None, outcome="failure"):
    return dict(record_id=str(i), task_id=f"task-{family}", source_family=family,
                summary=summary, embedding=vector or [1.0, 0.0], outcome=outcome,
                error_category="range" if outcome == "failure" else None,
                token_count=10, feedback_source="evaluator", env_version="test-v1",
                workbook_hash=f"hash-{family}", tool_events=[], split="dev")
