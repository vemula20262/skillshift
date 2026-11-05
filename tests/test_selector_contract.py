import json
from pathlib import Path
import unittest
from skillshift.io import validate_dev
from skillshift.selectors.base import prepare
from selector_helpers import record


class ContractTests(unittest.TestCase):
    def test_invalid_schema_and_duplicate_ids(self):
        for field, value in (("source_family", ""), ("token_count", -1),
                             ("outcome", "unknown"), ("error_category", None)):
            row = record(1)
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare([row])
        with self.assertRaises(ValueError):
            prepare([record(1), record(1)])

    def test_generated_ids_keep_duplicate_occurrences(self):
        rows = [record(1), record(1)]
        for row in rows:
            del row["record_id"]
        result = prepare(rows)
        self.assertNotEqual(result[0]["record_id"], result[1]["record_id"])

    def test_actual_dataset_manifest_formats(self):
        root = Path(__file__).resolve().parents[1]
        for variant in ("120", "400"):
            path = root / "datasets" / variant
            manifest = json.loads((path / "task_manifest.json").read_text())
            dev = next(x for x in manifest if x["split"] == "dev")
            row = record(1)
            row.update(task_id=dev["id"], source_family=dev["family_id"])
            validate_dev([row], manifest)
            validate_dev([row], json.loads((path / "splits.json").read_text()))
            row["source_family"] = "incorrect"
            with self.assertRaises(ValueError):
                validate_dev([row], manifest)

    def test_family_and_precautionary_block_leakage_rejected(self):
        for shared_field in ("family_id", "split_group_id"):
            manifest = [dict(id="task-A", family_id="A", split_group_id="block-A", split="dev"),
                        dict(id="task-B", family_id="B", split_group_id="block-B", split="test")]
            manifest[1][shared_field] = manifest[0][shared_field]
            with self.assertRaises(ValueError):
                validate_dev([record(1)], manifest)
