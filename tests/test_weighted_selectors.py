import unittest
from skillshift.selectors import get_selector
from selector_helpers import record


class WeightedTests(unittest.TestCase):
    def setUp(self):
        self.rows = [record(1), record(2), record(3, "B"),
                     record(4, summary="Different formula issue", vector=[0, 1])]

    def test_family_mass_is_one(self):
        result = get_selector("source_balanced").select(self.rows)
        for family in ("A", "B"):
            self.assertAlmostEqual(sum(x.weight for x in result.items
                                       if x.record["source_family"] == family), 1)

    def test_family_behavior_mass_is_one_and_families_are_recorded(self):
        result = get_selector("source_behavior", 0.9).select(self.rows)
        weights = {x.record["record_id"]: x.weight for x in result.items}
        self.assertEqual(weights, {"1": 0.5, "2": 0.5, "3": 1, "4": 1})
        shared = next(x for x in result.items if x.record["record_id"] == "1")
        self.assertEqual(shared.families, ["A", "B"])

    def test_repeat_invariance_of_weighted_group_mass(self):
        rows = [record(i) for i in range(20)] + [record(21, "B")]
        result = get_selector("source_behavior", 0.9).select(rows)
        self.assertAlmostEqual(sum(x.weight for x in result.items), 2)

    def test_order_independence_for_semantic_methods_with_explicit_ids(self):
        for method in ("semantic_dedup", "source_behavior"):
            selector = get_selector(method, 0.9)
            self.assertEqual(selector.select(self.rows).to_dict(), selector.select(self.rows[::-1]).to_dict())

    def test_pool_builder_integration_keeps_every_copy(self):
        from scripts.build_pools import build_pools
        originals = [record(i, outcome="success" if i < 3 else "failure") for i in range(6)]
        config = dict(status="approved", split_tasks={"dev": ["task-A"], "val": [], "test": []},
                      dominant_task_ids=["task-A"],
                      pools=[dict(name="synthetic", mechanism="exact_copy", repeat_fraction=0.5)])
        pool = build_pools(originals, config)["synthetic"]["records"]
        result = get_selector("unfiltered").select(pool)
        self.assertEqual(len(result.items), 12)
        self.assertEqual(len({x.record["record_id"] for x in result.items}), 6)
        self.assertEqual(len({x.record["occurrence_id"] for x in result.items}), 12)
        dedup = get_selector("exact_dedup").select(pool)
        self.assertEqual(len(dedup.items), 2)
        self.assertEqual(sum(len(x.member_ids) for x in dedup.items), 12)
        self.assertAlmostEqual(sum(x.weight for x in get_selector("source_balanced").select(pool).items), 1)
