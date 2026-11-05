"""Synthetic feedback fixtures for selector tests."""
def record(i, family="A", summary="Wrong range", vector=None, outcome="failure"):
    return dict(record_id=str(i), task_id=f"task-{family}", source_family=family,
                summary=summary, embedding=vector or [1.0, 0.0], outcome=outcome,
                error_category="range" if outcome == "failure" else None,
                token_count=10, feedback_source="evaluator", env_version="test-v1",
                workbook_hash=f"hash-{family}", tool_events=[], split="dev")
