"""Synthetic fixtures only; these are not experimental results."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skillshift import gate, selection  # noqa: E402
from skillshift.sampling import sample_to_budget  # noqa: E402


def recs(n, tokens=10):
    return [{"record_id": f"r{i}", "token_count": tokens} for i in range(n)]


class SamplingTests(unittest.TestCase):
    def test_respects_budget_and_is_deterministic(self):
        records = recs(20, tokens=7)
        a = sample_to_budget(records, [1.0] * 20, 50, seed=3)
        b = sample_to_budget(records, [1.0] * 20, 50, seed=3)
        self.assertEqual([s.record["record_id"] for s in a], [s.record["record_id"] for s in b])
        self.assertEqual(len(a), 7)
        self.assertLessEqual(sum(s.record["token_count"] for s in a), 50)

    def test_zero_weight_never_chosen(self):
        records = recs(5)
        chosen = sample_to_budget(records, [0, 1, 0, 1, 0], 1000, seed=0)
        self.assertEqual(sorted(s.record["record_id"] for s in chosen), ["r1", "r3"])

    def test_heavier_records_come_first_more_often(self):
        records = recs(2, tokens=10)
        first_heavy = sum(
            sample_to_budget(records, [9.0, 1.0], 10, seed=s)[0].record["record_id"] == "r0" for s in range(500)
        )
        # Probability r0 is drawn first is 9/10.
        self.assertGreater(first_heavy, 420)

    def test_skips_records_that_do_not_fit(self):
        records = [{"record_id": "big", "token_count": 90}, {"record_id": "small", "token_count": 10}]
        chosen = sample_to_budget(records, [1.0, 1.0], 95, seed=0)
        self.assertEqual(len(chosen), 1)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            sample_to_budget(recs(2), [1.0], 10, seed=0)
        with self.assertRaises(ValueError):
            sample_to_budget(recs(1), [float("nan")], 10, seed=0)
        with self.assertRaises(ValueError):
            sample_to_budget(recs(1), [1.0], 0, seed=0)


class GateTests(unittest.TestCase):
    def test_accepts_only_at_margin(self):
        parent = {"a": 0, "b": 1, "c": 0}
        self.assertTrue(gate.decide(parent, {"a": 1, "b": 1, "c": 0}, 1).accepted)
        self.assertFalse(gate.decide(parent, {"a": 1, "b": 0, "c": 0}, 1).accepted)
        self.assertFalse(gate.decide(parent, {"a": 1, "b": 1, "c": 0}, 2).accepted)

    def test_records_paired_changes(self):
        d = gate.decide({"a": 0, "b": 1}, {"a": 1, "b": 0}, 1)
        self.assertEqual((d.child_only_wins, d.parent_only_wins), (["a"], ["b"]))
        self.assertEqual(d.child_solved - d.parent_solved, 0)

    def test_rejects_mismatched_tasks(self):
        with self.assertRaises(ValueError):
            gate.decide({"a": 1}, {"b": 1}, 1)
        with self.assertRaises(ValueError):
            gate.decide({"a": 1}, {"a": 1}, 0)

    def test_per_task_hard(self):
        self.assertEqual(gate.per_task_hard([{"id": 1, "hard": 1}, {"id": "2", "hard": 0}]), {"1": 1, "2": 0})
        with self.assertRaises(ValueError):
            gate.per_task_hard([{"id": "1"}, {"id": "1"}])

    def test_no_edit(self):
        d = gate.no_edit_decision({"a": 1, "b": 0}, 1)
        self.assertFalse(d.accepted)
        self.assertEqual(d.child_solved, d.parent_solved)


class SelectionTests(unittest.TestCase):
    pool = [{"pool_record_id": "p:original:0", "record_id": "r0"},
            {"pool_record_id": "p:copy:failure:0", "record_id": "r0"}]

    def test_output_shapes(self):
        expected = (self.pool, [1.0, 0.5])
        shapes = [
            (self.pool, [1, 0.5]),
            {"records": self.pool, "weights": [1, 0.5]},
            list(zip(self.pool, [1, 0.5])),
            [dict(r, weight=w) for r, w in zip(self.pool, [1, 0.5])],
        ]
        for shape in shapes:
            records, weights = selection.normalise_output(shape, self.pool)
            self.assertEqual([r["pool_record_id"] for r in records], [r["pool_record_id"] for r in expected[0]])
            self.assertEqual(weights, expected[1])

    def test_rejects_bad_output(self):
        with self.assertRaises(ValueError):
            selection.normalise_output((self.pool, [1.0]), self.pool)
        with self.assertRaises(ValueError):
            selection.normalise_output((self.pool, [1.0, -1.0]), self.pool)
        with self.assertRaises(ValueError):
            selection.normalise_output(([{"pool_record_id": "invented"}], [1.0]), self.pool)
        with self.assertRaises(TypeError):
            selection.normalise_output("nope", self.pool)

    def test_load_selector(self):
        select = selection.load_selector("skillshift.selection:passthrough")
        self.assertEqual(select(self.pool, 10), (self.pool, [1.0, 1.0]))
        with self.assertRaises(ValueError):
            selection.load_selector("no-colon")


if __name__ == "__main__":
    unittest.main()
