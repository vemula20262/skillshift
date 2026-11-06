"""Offline end-to-end check of the single-update pipeline.

Runs the real SkillOpt rollout, reflection, patching and evaluation code on real
SpreadsheetBench workbooks, with the model API replaced by a scripted fake. No
network calls are made.

Skipped unless skillopt is importable and the extracted workbooks are present.
Point SKILLSHIFT_DATA_ROOT at the extracted spreadsheetbench_verified_400 folder,
or extract it to data/raw/spreadsheetbench_verified_400.
"""
import copy
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skillshift import schema, update  # noqa: E402
from skillshift.config import load_config  # noqa: E402

DATA_ROOT = Path(os.environ.get("SKILLSHIFT_DATA_ROOT", ROOT / "data/raw/spreadsheetbench_verified_400"))
FIXTURE_RULE = "SKILLSHIFT_FIXTURE_RULE"


def _ensure_openai_importable() -> None:
    """skillopt imports the openai SDK at import time. The fake client below replaces
    every call, so a bare placeholder is enough where the SDK is not installed."""
    if importlib.util.find_spec("openai") is None:
        placeholder = types.ModuleType("openai")
        placeholder.OpenAI = placeholder.AzureOpenAI = object
        sys.modules["openai"] = placeholder


_ensure_openai_importable()
HAVE_SKILLOPT = importlib.util.find_spec("skillopt") is not None
HAVE_DATA = (DATA_ROOT / "spreadsheet").is_dir()


class FakeClient:
    """Scripted stand-in for the OpenAI chat API.

    Target: copies the input workbook (wrong answer) unless the skill contains the
    fixture rule, in which case it copies the reference workbook to simulate a
    correct solution. Optimizer: proposes appending the fixture rule, or returns
    unusable text when optimizer_ok is False.
    """

    def __init__(self, target_model: str, optimizer_ok: bool = True):
        self.target_model = target_model
        self.optimizer_ok = optimizer_ok
        self.target_down = False
        self.calls = {"target": 0, "optimizer": 0}
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, *, model, messages, **_kwargs):
        system = messages[0]["content"] if messages else ""
        if model == self.target_model:
            if self.target_down:
                raise RuntimeError("Error code: 429")
            self.calls["target"] += 1
            source = "INPUT_PATH.replace('_init.xlsx', '_golden.xlsx')" if FIXTURE_RULE in system else "INPUT_PATH"
            text = f"```python\nimport shutil\nshutil.copyfile({source}, OUTPUT_PATH)\n```"
        else:
            self.calls["optimizer"] += 1
            if self.optimizer_ok:
                edits = [{"op": "append", "target": "", "content": f"## {FIXTURE_RULE}\nCheck the answer cells."}]
                text = json.dumps({"reasoning": "fixture", "patch": {"edits": edits}, "edits": edits})
            else:
                text = "no structured answer"
        usage = types.SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        message = types.SimpleNamespace(content=text)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=usage)


@unittest.skipUnless(HAVE_SKILLOPT and HAVE_DATA, "needs skillopt and extracted SpreadsheetBench workbooks")
class UpdatePipelineTests(unittest.TestCase):
    def setUp(self):
        from skillopt.model import azure_openai

        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        cfg = load_config()
        cfg = copy.deepcopy(cfg)
        cfg["dataset"]["data_root"] = str(DATA_ROOT)
        cfg["model"].update(base_url="http://fake.invalid/v1", optimizer_model="fake-optimizer",
                            target_model="fake-target", api_key_env="SKILLSHIFT_TEST_KEY")
        os.environ.setdefault("SKILLSHIFT_TEST_KEY", "offline-test")
        cfg["executor"]["workers"] = 2
        cfg["feedback"]["token_budget"] = 1_000_000
        self.cfg = cfg
        update.configure_models(cfg)

        self.azure_openai = azure_openai
        self.saved_factory = azure_openai._make_client
        self.client = FakeClient("fake-target")
        azure_openai._make_client = lambda role: self.client
        azure_openai._optimizer_client = None
        azure_openai._target_client = None

        tasks = update.load_tasks(cfg)
        self.dev_ids = json.loads((ROOT / "datasets/120/pilot_10.json").read_text())[:4]
        self.val_ids = [t["id"] for t in tasks if t["split"] == "val"][:3]
        self.test_ids = [t["id"] for t in tasks if t["split"] == "test"][:2]
        self.pool_path = self._collect_attempts_and_build_pool(tasks)

    def tearDown(self):
        self.azure_openai._make_client = self.saved_factory
        self.azure_openai._optimizer_client = None
        self.azure_openai._target_client = None
        self.tmp.cleanup()

    def _collect_attempts_and_build_pool(self, tasks):
        """Minimal attempt collection for the fixture; the real collector lives elsewhere."""
        from skillopt.envs.spreadsheetbench.rollout import run_spreadsheet_batch_codegen
        from skillopt.gradient.reflect import fmt_minibatch_trajectories

        attempts_root = self.work / "attempts"
        batch_dir = attempts_root / "raw" / "fixture"
        skill, _ = update.starting_skill(self.cfg)
        items = update.task_items(tasks, "dev", self.dev_ids)
        results = run_spreadsheet_batch_codegen(
            items=items, data_root=str(DATA_ROOT), out_root=str(batch_dir), skill_content=skill,
            mode="single", max_turns=1, max_completion_tokens=1024, max_api_workers=2, task_timeout=120,
        )
        by_id = {t["id"]: t for t in tasks}
        records = []
        for result in results:
            task = by_id[str(result["id"])]
            traj = batch_dir / "predictions" / str(result["id"])
            conversation = json.loads((traj / "conversation.json").read_text())
            records.append(schema.record_from_rollout(
                result,
                record_id=f"fixture-{result['id']}",
                source_family=task["family_id"],
                workbook_hash=task["initial_audit"]["sha256"],
                env_version="fixture",
                feedback_source="original",
                trajectory_path=str(traj.relative_to(attempts_root)),
                conversation=conversation,
                feedback_text=fmt_minibatch_trajectories([result], str(batch_dir / "predictions")),
            ))
        self.assertEqual(schema.validate_records(records), [])
        self.assertTrue(all(r["outcome"] == "failure" for r in records))

        spec = importlib.util.spec_from_file_location("build_pools", ROOT / "scripts" / "build_pools.py")
        build_pools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_pools)
        config = {
            "status": "approved",
            "split_tasks": {"dev": self.dev_ids, "val": self.val_ids, "test": self.test_ids},
            "dominant_task_ids": self.dev_ids[:1],
            "pools": [{"name": "fixture_pool", "mechanism": "exact_copy", "repeat_fraction": 0.5}],
        }
        pool = build_pools.build_pools(records, config)["fixture_pool"]["records"]
        pool_path = self.work / "fixture_pool.jsonl"
        pool_path.write_text("".join(json.dumps(r) + "\n" for r in pool), encoding="utf-8")
        self.attempts_root = attempts_root
        return pool_path

    def _run(self, **kwargs):
        return update.run_update(
            self.cfg, pool_path=self.pool_path, selector_name="passthrough", attempts_root=self.attempts_root,
            out_root=self.work / "results", val_ids=self.val_ids, test_ids=self.test_ids, **kwargs,
        )

    def test_accepted_update_end_to_end(self):
        log = self._run()
        run_dir = self.work / "results" / "runs" / log["run_id"]

        self.assertEqual(log["pool_occurrences"], 8)
        self.assertEqual(log["sampled"], 8)
        self.assertTrue(log["edited"])
        self.assertIn(FIXTURE_RULE, (run_dir / "child_skill.md").read_text())
        self.assertEqual(log["gate"]["n_tasks"], 3)
        self.assertGreater(log["gate"]["child_solved"], log["gate"]["parent_solved"])
        self.assertTrue(log["gate"]["accepted"])

        # Test scores are written only to the sealed folder, never to the run log.
        self.assertTrue(log["test_evaluated"])
        sealed = json.loads((self.work / "results" / "sealed" / f"{log['run_id']}.json").read_text())
        self.assertEqual(set(sealed["child"]), set(self.test_ids))
        self.assertNotIn("test", json.dumps(log["gate"]))

        selection = json.loads((run_dir / "selection.json").read_text())
        self.assertEqual(sum(s["token_count"] for s in selection), log["feedback_tokens"])
        self.assertGreater(log["api_usage"]["_total"]["calls"], 0)

        # Re-running the same pool, selector and seed must not overwrite a finished run.
        with self.assertRaises(FileExistsError):
            self._run()

        # Parent validation scores are cached across runs with the same settings.
        calls_before = self.client.calls["target"]
        self._run(seed=1)
        self.assertEqual(self.client.calls["target"], calls_before)

    def test_failed_model_calls_are_not_scored(self):
        from unittest import mock

        tasks = update.load_tasks(self.cfg)
        items = update.task_items(tasks, "val", self.val_ids)
        skill, _ = update.starting_skill(self.cfg)
        cache = self.work / "cache"
        self.client.target_down = True
        with mock.patch("skillopt.model.azure_openai.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "3 of 3 val tasks got no model response"):
                update.evaluate_skill(self.cfg, skill, items, cache, "val")
        results_files = list(cache.rglob("results.jsonl"))
        self.assertEqual(len(results_files), 1)
        self.assertEqual(results_files[0].read_text(), "")

        # Once the API is back, the same call retries every task instead of reusing the failures.
        self.client.target_down = False
        results = update.evaluate_skill(self.cfg, skill, items, cache, "val")
        self.assertEqual(len(results), 3)
        self.assertEqual(schema.model_call_failures(results), [])

    def test_budget_limits_feedback(self):
        sizes = sorted(json.loads(line)["token_count"] for line in self.pool_path.read_text().splitlines())
        self.cfg["feedback"]["token_budget"] = sizes[0] + sizes[1]
        log = self._run()
        self.assertGreaterEqual(log["sampled"], 1)
        self.assertLess(log["sampled"], log["pool_occurrences"])
        self.assertLessEqual(log["feedback_tokens"], self.cfg["feedback"]["token_budget"])

    def test_unusable_optimizer_output_leaves_skill_unchanged(self):
        self.client.optimizer_ok = False
        log = self._run()
        self.assertFalse(log["edited"])
        self.assertFalse(log["gate"]["accepted"])
        self.assertFalse(log["test_evaluated"])
        self.assertFalse((self.work / "results" / "sealed").exists())


if __name__ == "__main__":
    unittest.main()
