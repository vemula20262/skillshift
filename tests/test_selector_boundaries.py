import random
import unittest
from skillshift.selectors import get_selector
from skillshift.selectors.base import cosine, prepare
from skillshift.embeddings import encode
from selector_helpers import build_pools_module
build_pools = build_pools_module.build_pools
from selector_helpers import record


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(record(1), embedding_model="test@revision"),
                     dict(record(2), embedding_model="test@revision"),
                     dict(record(3, vector=[0, 1]), embedding_model="test@revision")]
        self.splits = dict(dev=["task-A"], val=[], test=[])

    def pool(self, rows):
        config = dict(status="approved", split_tasks=self.splits, dominant_task_ids=["task-A"],
                      pools=[dict(name="repeat", mechanism="exact_copy", repeat_fraction=.75)])
        return build_pools(rows, config)["repeat"]["records"]

    def test_identical_high_dimensional_vectors_at_one(self):
        rng = random.Random(41)
        for _ in range(100):
            vector = [rng.uniform(-1, 1) for _ in range(384)]
            self.assertEqual(cosine(vector, vector[:]), 1.0)
        rows = [dict(r, embedding=vector[:]) for r in self.rows[:2]]
        pooled = self.pool(rows)
        self.assertEqual(len(get_selector("semantic_dedup", 1).select(pooled).items), 1)
        result = get_selector("source_behavior", 1).select(pooled)
        self.assertAlmostEqual(sum(i.weight for i in result.items), 1)


    def test_dedup_prefers_original_on_ties(self):
        for method in ("exact_dedup", "semantic_dedup"):
            result = get_selector(method, 1).select(self.pool(self.rows[:2]))
            self.assertFalse(result.items[0].record["is_copy"])

    def test_mixed_original_and_pool_rejected(self):
        with self.assertRaisesRegex(ValueError, "mix original"):
            prepare(self.rows[:1] + self.pool(self.rows[:1]))

    def test_embedding_rejects_pool_before_model_load(self):
        with self.assertRaisesRegex(ValueError, "before pool"):
            encode(self.pool(self.rows[:1]), "unused", "unused", "unused")
