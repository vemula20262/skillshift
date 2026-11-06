"""Checks that the configured selectors plug into the pipeline."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skillshift import schema  # noqa: E402
from skillshift.config import load_config  # noqa: E402
from skillshift.sampling import sample_to_budget  # noqa: E402
from skillshift.selection import load_selector, normalise_output  # noqa: E402


def pool_record(i, task, family, vec, copy=False):
    record = {
        "record_id": f"attempt-{task}-{i}",
        "task_id": task,
        "source_family": family,
        "split": "dev",
        "workbook_hash": "b" * 64,
        "env_version": "fixture",
        "feedback_source": "original",
        "outcome": "failure",
        "error_category": "wrong_values",
        "fail_reason": "eval-mismatch: value@Sheet1!A1",
        "instruction": "Fill A1.",
        "task_type": "cell_level",
        "n_turns": 1,
        "tool_events": ["write_code", "check_fail"],
        "token_count": 50,
        "trajectory_path": f"raw/fixture/predictions/{task}",
        "trajectory_sha256": "c" * 64,
        "summary": f"Wrote the wrong value for task {task}.",
        "embedding": vec,
    }
    record.update(original_record_id=record["record_id"], pool_record_id=f"pool:{task}:{i}:{int(copy)}", is_copy=copy)
    return record


class SelectorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        # Two copies of one task's failure plus one failure from another task.
        original = pool_record(0, "T1", "F1", [1.0, 0.0])
        duplicate = dict(original, pool_record_id="pool:T1:0:1", is_copy=True)
        self.pool = [original, duplicate, pool_record(0, "T2", "F2", [0.0, 1.0])]
        self.assertEqual(schema.validate_records(self.pool, require_derived=True), [])

    def run_selector(self, name, **kwargs):
        entry = dict(self.cfg["selectors"][name])
        entry["kwargs"] = dict(entry["kwargs"], **kwargs)
        records, weights = normalise_output(load_selector(entry)(self.pool, 1000), self.pool)
        return records, weights

    def test_every_configured_method_loads_and_returns_pool_records(self):
        expected = {"unfiltered": 3, "exact_dedup": 2, "source_balanced": 3}
        for name, n in expected.items():
            with self.subTest(name=name):
                records, weights = self.run_selector(name)
                self.assertEqual(len(records), n)
        for name in ("semantic_dedup", "source_behavior"):
            with self.subTest(name=name):
                records, _ = self.run_selector(name, threshold=0.9)
                self.assertTrue(records)

    def test_source_balanced_weights_reach_the_sampler(self):
        records, weights = self.run_selector("source_balanced")
        by_family = {}
        for r, w in zip(records, weights):
            by_family[r["source_family"]] = by_family.get(r["source_family"], 0) + w
        self.assertEqual(by_family, {"F1": 1.0, "F2": 1.0})
        chosen = sample_to_budget(records, weights, 100, seed=0)
        self.assertEqual(len(chosen), 2)

    def test_semantic_methods_refuse_without_threshold(self):
        with self.assertRaises(ValueError):
            load_selector(self.cfg["selectors"]["semantic_dedup"])


if __name__ == "__main__":
    unittest.main()
