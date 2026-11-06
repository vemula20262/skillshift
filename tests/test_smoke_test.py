"""Offline run of scripts/smoke_test.py with a scripted model."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_update_pipeline import DATA_ROOT, HAVE_DATA, HAVE_SKILLOPT, FakeClient  # noqa: E402


@unittest.skipUnless(HAVE_SKILLOPT and HAVE_DATA, "needs skillopt and extracted SpreadsheetBench workbooks")
class SmokeTestScriptTests(unittest.TestCase):
    def test_runs_end_to_end_without_touching_test_split(self):
        import yaml
        from skillopt.model import azure_openai

        spec = importlib.util.spec_from_file_location("smoke_test", ROOT / "scripts" / "smoke_test.py")
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text())
            cfg["dataset"]["data_root"] = str(DATA_ROOT)
            cfg["dataset"]["task_manifest"] = str(ROOT / cfg["dataset"]["task_manifest"])
            cfg["model"].update(optimizer_model="fake-optimizer", target_model="fake-target")
            config_path = tmp / "config.yaml"
            config_path.write_text(yaml.safe_dump(cfg))

            client = FakeClient("fake-target")
            saved = azure_openai._make_client
            azure_openai._make_client = lambda role: client
            azure_openai._optimizer_client = azure_openai._target_client = None
            try:
                with mock.patch.dict(os.environ, {cfg["model"]["api_key_env"]: "offline-test"}):
                    code = smoke.main(["--config", str(config_path), "--out", str(tmp / "smoke"),
                                       "--tasks", "3", "--val-limit", "2"])
            finally:
                azure_openai._make_client = saved
                azure_openai._optimizer_client = azure_openai._target_client = None

            self.assertEqual(code, 0)
            summary = json.loads((tmp / "smoke" / "smoke_summary.json").read_text())
            self.assertEqual(summary["attempts_solved"], "0/3")
            self.assertTrue(summary["accepted"])
            self.assertEqual(summary["val_child"], "2/2")
            self.assertFalse((tmp / "smoke" / "sealed").exists())
            self.assertTrue((tmp / "smoke" / "pools" / "smoke_C0.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
