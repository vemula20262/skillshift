"""Tests for the attempt record schema."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skillshift import schema  # noqa: E402

HASH = "a" * 64


def make_record(i=0, **overrides):
    record = {
        "record_id": f"synthetic-{i}",
        "task_id": "synthetic-task",
        "source_family": "observed-synthetic-task",
        "split": "dev",
        "workbook_hash": HASH,
        "env_version": "skillopt-test",
        "feedback_source": "original",
        "outcome": "failure",
        "error_category": "wrong_values",
        "fail_reason": "eval-mismatch: value@Sheet1!A1: gt=1 pred=2",
        "instruction": "Fill A1.",
        "task_type": "cell_level",
        "n_turns": 1,
        "tool_events": ["write_code", "check_fail"],
        "token_count": 120,
        "trajectory_path": f"raw/fixture/predictions/synthetic-{i}",
        "trajectory_sha256": "c" * 64,
        "summary": None,
        "embedding": None,
    }
    record.update(overrides)
    return record


class CategorizeTests(unittest.TestCase):
    def test_known_fail_reasons(self):
        cases = {
            "": ("none", ""),
            "llm-call-failed: RuntimeError: LLM call failed": ("llm_call_failed", "RuntimeError"),
            "empty-code-block": ("no_code", ""),
            "exec-error: KeyError: 'Sheet2'": ("exec_error", "KeyError"),
            "exec-error: timeout after 120s": ("timeout", ""),
            "output-not-found": ("no_output", ""),
            "eval-mismatch: worksheet not found: Summary": ("wrong_sheet", ""),
            "eval-mismatch: load error: bad zip": ("no_output", "unreadable_output"),
            "eval-mismatch: value@Sheet1!B2: gt=3 pred=4": ("wrong_values", ""),
            "no-test-cases": ("setup_error", "no-test-cases"),
            "something new": ("other", ""),
        }
        for reason, expected in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(schema.categorize_failure(reason), expected)
                self.assertIn(expected[0], schema.ERROR_CATEGORIES)


class ModelCallFailureTests(unittest.TestCase):
    def test_only_llm_call_failures_are_picked(self):
        results = [
            {"id": "a", "fail_reason": "llm-call-failed: RuntimeError: Error code: 429"},
            {"id": "b", "fail_reason": "eval-mismatch: values differ"},
            {"id": "c", "fail_reason": ""},
        ]
        self.assertEqual([r["id"] for r in schema.model_call_failures(results)], ["a"])


class ValidateTests(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(schema.validate_record(make_record()), [])

    def test_type_and_value_errors(self):
        bad = [
            ({"split": "val"}, "development split"),
            ({"outcome": "maybe"}, "outcome"),
            ({"error_category": "none"}, "exactly when"),
            ({"workbook_hash": "ABC"}, "sha256"),
            ({"trajectory_sha256": "short"}, "trajectory_sha256"),
            ({"token_count": 0}, "token_count"),
            ({"token_count": True}, "bool"),
            ({"trajectory_path": "../outside"}, "trajectory_path"),
            ({"embedding": [0.1, float("nan")]}, "embedding"),
            ({"feedback_source": "copy"}, "feedback_source"),
        ]
        for overrides, fragment in bad:
            with self.subTest(overrides=overrides):
                problems = schema.validate_record(make_record(**overrides))
                self.assertTrue(any(fragment in p for p in problems), problems)

    def test_missing_field(self):
        record = make_record()
        del record["token_count"]
        self.assertIn("missing field: token_count", schema.validate_record(record))

    def test_success_needs_none_category(self):
        ok = make_record(outcome="success", error_category="none", fail_reason="")
        self.assertEqual(schema.validate_record(ok), [])

    def test_require_derived(self):
        problems = schema.validate_record(make_record(), require_derived=True)
        self.assertTrue(any("summary" in p for p in problems))
        filled = make_record(summary="Wrote values to the wrong column.", embedding=[0.1, 0.2])
        self.assertEqual(schema.validate_record(filled, require_derived=True), [])

    def test_cross_record_checks(self):
        records = [make_record(0), make_record(0)]
        self.assertTrue(any("duplicate record_id" in e for e in schema.validate_records(records)))
        records = [make_record(0), make_record(1, source_family="other-family")]
        self.assertTrue(any("inconsistent source_family" in e for e in schema.validate_records(records)))
        records = [make_record(0, embedding=[0.1]), make_record(1, embedding=[0.1, 0.2])]
        self.assertTrue(any("dimensions" in e for e in schema.validate_records(records)))

    def test_pool_fields_must_appear_together(self):
        partial = make_record(pool_record_id="p:original:0")
        self.assertTrue(any("together" in p for p in schema.validate_record(partial)))


class PoolBuilderCompatibilityTests(unittest.TestCase):
    """Records that pass this schema must also go through scripts/build_pools.py."""

    def test_pool_output_still_valid(self):
        spec = importlib.util.spec_from_file_location("build_pools", ROOT / "scripts" / "build_pools.py")
        build_pools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_pools)
        records = [
            make_record(i, outcome="success", error_category="none", fail_reason="") if i < 3 else make_record(i)
            for i in range(6)
        ]
        before = copy.deepcopy(records)
        self.assertEqual(schema.validate_records(records), [])
        config = {
            "status": "approved",
            "split_tasks": {"dev": ["synthetic-task"], "val": ["synthetic-val"], "test": ["synthetic-test"]},
            "dominant_task_ids": ["synthetic-task"],
            "pools": [{"name": "fixture", "mechanism": "exact_copy", "repeat_fraction": 0.5}],
        }
        pool = build_pools.build_pools(records, config)["fixture"]["records"]
        self.assertEqual(len(pool), 12)
        self.assertEqual(schema.validate_records(pool), [])
        self.assertEqual(records, before)


class HelperTests(unittest.TestCase):
    def test_record_from_rollout(self):
        conversation = [
            {"role": "system", "content": "skill"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "```python\nprint(1)\n```"},
            {"role": "system", "content": "[POST-EXECUTION VERIFICATION]\n\n## Eval Result (case 1): FAIL"},
        ]
        result = {"id": "123", "hard": 0, "fail_reason": "exec-error: ValueError: bad", "task_description": "Do it",
                  "task_type": "cell_level", "n_turns": 1}
        record = schema.record_from_rollout(
            result, record_id="r1", source_family="observed-123", workbook_hash=HASH, env_version="v",
            feedback_source="original", trajectory_path="raw/x/predictions/123", conversation=conversation,
            feedback_text="x" * 401,
        )
        self.assertEqual(record["error_category"], "exec_error")
        self.assertEqual(record["error_detail"], "ValueError")
        self.assertEqual(record["tool_events"], ["write_code", "check_fail"])
        self.assertEqual(record["token_count"], 101)
        self.assertEqual(record["trajectory_sha256"], schema.trajectory_digest(conversation))
        self.assertNotEqual(record["trajectory_sha256"], schema.trajectory_digest(conversation[:-1]))
        self.assertEqual(schema.validate_record(record), [])

    def test_load_jsonl_reports_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text(json.dumps(make_record()) + "\n{not json}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, ":2:"):
                schema.load_jsonl(path)


if __name__ == "__main__":
    unittest.main()
