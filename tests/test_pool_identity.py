import unittest
from skillshift.selectors.base import prepare


def attempt(i):
    return dict(record_id=str(i), task_id="dev-task", source_family="family-A",
                summary="Range endpoint is wrong", outcome="failure", error_category="range",
                token_count=10, feedback_source="evaluator", env_version="synthetic-v1",
                embedding=[1.0, 0.0], split="dev")


class PoolIdentityTests(unittest.TestCase):
    def test_unknown_occurrence_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "occurrence_id conflicts"):
            prepare([dict(attempt(1), occurrence_id="wrong")])

    def test_pool_identity_and_original_payload_cannot_disagree(self):
        a = dict(attempt(1), pool_record_id="p:0", original_record_id="1", is_copy=False)
        b = dict(a, pool_record_id="p:1", is_copy=True, summary="Changed evidence")
        with self.assertRaisesRegex(ValueError, "identical original"):
            prepare([a, b])
        for row in (dict(a, original_record_id="wrong"), dict(a, is_copy="false"),
                    dict(attempt(1), pool_record_id="p:0")):
            with self.assertRaises(ValueError):
                prepare([row])
