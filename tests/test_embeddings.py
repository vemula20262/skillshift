import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from skillshift.embeddings import encode
from skillshift.selectors import METHODS, get_selector
from selector_helpers import build_pools_module
build_pools = build_pools_module.build_pools


def attempt(i):
    return dict(record_id=str(i), task_id="dev-task", source_family="family-A",
                summary="Range endpoint is wrong", outcome="failure", error_category="range",
                token_count=10, feedback_source="evaluator", env_version="synthetic-v1",
                embedding=[1.0, 0.0], split="dev")


class Vector(list):
    def tolist(self):
        return list(self)


def fake_encoder(vectors):
    return SimpleNamespace(SentenceTransformer=lambda *a, **kw:
                           SimpleNamespace(encode=lambda *a, **kw: vectors))


class EmbeddingTests(unittest.TestCase):
    def test_embedding_pool_selector_round_trip(self):
        originals = [attempt(1), attempt(2)]
        with patch.dict(sys.modules, {"sentence_transformers": fake_encoder([Vector([1, 0])] * 2)}):
            embedded = encode(originals, "fake-model", "fake-revision", "unused")
        config = dict(status="approved", split_tasks={"dev": ["dev-task"], "val": [], "test": []},
                      dominant_task_ids=["dev-task"], pools=[
                          dict(name="zero", mechanism="exact_copy", repeat_fraction=0),
                          dict(name="half", mechanism="exact_copy", repeat_fraction=0.5)])
        for name, pool in build_pools(embedded, config).items():
            rows = pool["records"]
            for method in METHODS:
                result = get_selector(method, 0.9).select(rows)
                self.assertEqual(result.input_count, 2 if name == "zero" else 4)
                for item in result.items:
                    self.assertEqual(item.record["occurrence_id"], item.record["pool_record_id"])
            self.assertEqual(len(get_selector("unfiltered").select(rows).items), len(rows))
        self.assertNotIn("occurrence_id", originals[0])

    def test_embedding_count_mismatch_cannot_reuse_stale_vectors(self):
        # All old vectors deliberately have the same model metadata; shape
        # validation alone previously accepted a partially refreshed result.
        rows = [dict(attempt(i), embedding_model="fake@revision") for i in (1, 2)]
        for vectors in ([Vector([0, 1])], [Vector([0, 1])] * 3):
            with patch.dict(sys.modules, {"sentence_transformers": fake_encoder(vectors)}):
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    encode(rows, "fake", "revision", "unused")
