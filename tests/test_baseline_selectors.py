import copy
import math
import unittest
from skillshift.selectors import METHODS, get_selector
from skillshift.selectors.base import prepare, semantic_groups
from selector_helpers import record


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.rows = [record(1), record(2), record(3, "B"),
                     record(4, summary="Different formula issue", vector=[0, 1])]

    def test_unfiltered_preserves_all_without_mutation(self):
        original = copy.deepcopy(self.rows)
        result = get_selector("unfiltered").select(self.rows)
        self.assertEqual([x.weight for x in result.items], [1, 1, 1, 1])
        result.items[0].record["summary"] = "changed"
        self.assertEqual(self.rows, original)

    def test_exact_merges_across_families_and_retains_provenance(self):
        result = get_selector("exact_dedup").select(self.rows)
        self.assertEqual(len(result.items), 2)
        merged = next(x for x in result.items if len(x.member_ids) == 3)
        self.assertEqual(merged.families, ["A", "B"])
        self.assertEqual(merged.weight, 1)

    def test_exact_keeps_tool_evidence_and_literal_text_differences(self):
        rows = [record(1), record(2), record(3, summary="Wrong range ")]
        rows[1]["tool_events"] = [{"error": "different"}]
        self.assertEqual(len(get_selector("exact_dedup").select(rows).items), 3)

    def test_semantic_merges_paraphrases(self):
        rows = [record(1), record(2, "B", "The selected cell range is incorrect", [0.99, 0.01])]
        result = get_selector("semantic_dedup", 0.9).select(rows)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].families, ["A", "B"])

    def test_semantic_uses_medoid_not_first_record(self):
        rows = [record(1, summary="a", vector=[1, 0]),
                record(2, summary="b", vector=[0.98, 0.2]),
                record(3, summary="c", vector=[0.92, 0.39])]
        result = get_selector("semantic_dedup", 0.9).select(rows)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].record["record_id"], "2")

    def test_no_similarity_chaining(self):
        rows = [record(i, summary=str(i), vector=[math.cos(a), math.sin(a)])
                for i, a in enumerate([0, 0.4, 0.8])]
        groups = semantic_groups(prepare(rows, True), 0.9)
        self.assertEqual(sorted(map(len, groups)), [1, 2])

    def test_outcomes_categories_environments_sources_stay_separate(self):
        for key, value in (("outcome", "success"), ("error_category", "formula"),
                           ("env_version", "v2"), ("feedback_source", "reflection")):
            with self.subTest(key=key):
                rows = [record(1), record(2)]
                rows[1][key] = value
                for name in ("exact_dedup", "semantic_dedup"):
                    self.assertEqual(len(get_selector(name, 0.9).select(rows).items), 2)

    def test_invalid_embeddings_are_rejected(self):
        for vector in ([0, 0], [float("nan"), 0], [float("inf"), 0], [], [True, 0]):
            rows = [record(1)]
            rows[0]["embedding"] = vector
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                get_selector("semantic_dedup", 0.9).select(rows)
        with self.assertRaises(ValueError):
            get_selector("semantic_dedup", 0.9).select([record(1), record(2, vector=[1, 0, 0])])

    def test_empty_pools_and_missing_or_invalid_threshold(self):
        for method in METHODS:
            self.assertEqual(get_selector(method, 0.9).select([]).items, [])
        with self.assertRaises(ValueError):
            get_selector("semantic_dedup")
        for threshold in (float("nan"), 1.1, -1.1):
            with self.assertRaises(ValueError):
                get_selector("semantic_dedup", threshold).select(self.rows)

    def test_mixed_embedding_models_rejected(self):
        self.rows[0]["embedding_model"] = "one-model"
        with self.assertRaises(ValueError):
            get_selector("semantic_dedup", 0.9).select(self.rows)
