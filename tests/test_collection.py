"""Offline checks for resumable development-attempt collection and record preparation.

A scripted stand-in replaces skillshift.attempts.collect_attempts, so no model or
workbook is needed. Record preparation additionally needs skillopt installed.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skillshift import summaries  # noqa: E402
from skillshift.collection import (Collector, coverage_problems, dev_task_ids,  # noqa: E402
                                   is_infra_failure, record_problems)
from skillshift.config import load_config  # noqa: E402
from skillshift.update import load_tasks  # noqa: E402
from skillshift.usage import Ledger  # noqa: E402

HAVE_SKILLOPT = importlib.util.find_spec("skillopt") is not None


def QUIET(*_):
    pass


class ScriptedCollect:
    """Mimics collect_attempts: resumes from results.jsonl and writes trajectories.

    outcomes maps task id -> list of results to return on successive attempts
    ("pass", "fail", "infra"). interrupt_after stops the call with KeyboardInterrupt
    after writing that many trajectories, before results.jsonl is updated.
    """

    def __init__(self, outcomes=None, interrupt_after=None):
        self.outcomes = outcomes or {}
        self.interrupt_after = interrupt_after
        self.model_calls: list[str] = []

    def __call__(self, cfg, tasks, task_ids, skill, attempts_root, batch_name):
        batch = Path(attempts_root) / "raw" / batch_name
        results_path = batch / "results.jsonl"
        existing = [json.loads(l) for l in results_path.read_text().splitlines()] if results_path.exists() else []
        done = {r["id"] for r in existing}
        new = []
        for n, task_id in enumerate(t for t in task_ids if t not in done):
            if self.interrupt_after is not None and n >= self.interrupt_after:
                raise KeyboardInterrupt
            self.model_calls.append(task_id)
            plan = self.outcomes.get(task_id, ["fail"])
            kind = plan.pop(0) if len(plan) > 1 else plan[0]
            pred = batch / "predictions" / task_id
            pred.mkdir(parents=True, exist_ok=True)
            if kind != "infra":
                (pred / "conversation.json").write_text(json.dumps([
                    {"role": "system", "content": "skill"},
                    {"role": "assistant", "content": "```python\nimport openpyxl\n```"}]))
                (pred / "code.py").write_text("import openpyxl\nfrom pandas import DataFrame\n")
            new.append({
                "id": task_id, "hard": 1 if kind == "pass" else 0, "n_turns": 0 if kind == "infra" else 1,
                "task_description": "do the thing", "task_type": "cell_level",
                "fail_reason": {"pass": "", "fail": f"eval-mismatch: Sheet1!A{len(task_id)} expected '7' got '3'",
                                "infra": "llm-call-failed: RateLimitError: 429"}[kind],
            })
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text("".join(json.dumps(r) + "\n" for r in existing + new))
        return []


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = load_config()
        self.tasks = load_tasks(self.cfg)
        self.wanted = dev_task_ids(self.tasks)
        self.ledger = Ledger(self.root / "cost.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def collector(self, collect, **kwargs):
        return Collector(self.cfg, self.tasks, "skill", self.root / "attempts", "dev_original",
                         self.ledger, collect=collect, **kwargs)

    def test_manifest_has_sixty_unique_dev_tasks(self):
        self.assertEqual(len(self.wanted), 60)
        self.assertEqual(len(set(self.wanted)), 60)

    def test_coverage_requires_exact_id_set(self):
        self.assertEqual(coverage_problems(self.wanted, list(self.wanted)), [])
        self.assertTrue(coverage_problems(self.wanted, self.wanted[:-1]))
        self.assertTrue(coverage_problems(self.wanted, self.wanted + [self.wanted[0]]))
        self.assertTrue(coverage_problems(self.wanted, self.wanted[:-1] + ["not-a-dev-task"]))

    def test_collects_every_dev_task_once(self):
        collect = ScriptedCollect()
        status = self.collector(collect).run(self.wanted, chunk_size=7, log=QUIET)
        self.assertEqual(status["pending"], [])
        self.assertEqual(sorted(collect.model_calls), sorted(self.wanted))
        self.assertEqual(len(self.ledger.rows()), 9)  # ceil(60 / 7) chunks, one cost row each

    def test_resume_repeats_no_completed_call(self):
        first = ScriptedCollect()
        self.collector(first).run(self.wanted, chunk_size=5, max_chunks=3, log=QUIET)
        self.assertEqual(len(first.model_calls), 15)
        second = ScriptedCollect()
        status = self.collector(second).run(self.wanted, chunk_size=5, log=QUIET)
        self.assertEqual(status["pending"], [])
        self.assertFalse(set(first.model_calls) & set(second.model_calls))
        self.assertEqual(len(first.model_calls) + len(second.model_calls), 60)

    def test_interrupted_chunk_keeps_evidence_and_records_usage(self):
        collector = self.collector(ScriptedCollect(interrupt_after=1))
        with self.assertRaises(KeyboardInterrupt):
            collector.run(self.wanted, chunk_size=3, log=QUIET)
        rows = self.ledger.rows()
        self.assertEqual([r["status"] for r in rows], ["partial"])
        interrupted_task = self.wanted[0]
        self.collector(ScriptedCollect()).run(self.wanted, chunk_size=3, max_chunks=1, log=QUIET)
        moved = self.root / "attempts/raw/dev_original/interrupted" / interrupted_task
        self.assertTrue(moved.is_dir() and any(moved.iterdir()))

    def test_infra_failures_are_separated_and_retried(self):
        flaky = self.wanted[0]
        broken = self.wanted[1]
        collect = ScriptedCollect({flaky: ["infra", "pass"], broken: ["infra"]})
        collector = self.collector(collect, max_infra_attempts=2)
        status = collector.run(self.wanted, chunk_size=10, log=QUIET)
        self.assertEqual(status["infra_exhausted"], [broken])
        self.assertIn(flaky, collector.evaluated_ids())
        self.assertNotIn(broken, collector.evaluated_ids())
        infra = collector.infra_failures()
        self.assertEqual(sorted(r["id"] for r in infra), sorted([flaky, broken, broken]))
        self.assertTrue((self.root / "attempts/raw/dev_original/infra" / broken / "2").is_dir())
        self.assertTrue(coverage_problems(self.wanted, collector.evaluated_ids()))
        self.assertEqual(sum(int(r["infra_failures"]) for r in self.ledger.rows()), 3)

    def test_failed_model_calls_stop_collection_and_are_retried(self):
        """collect_attempts raises when a model call failed and leaves that task out of
        results.jsonl; the chunk is logged as failed and the task runs again on restart."""
        down = self.wanted[1]

        def failing(cfg, tasks, task_ids, skill, attempts_root, batch_name):
            ScriptedCollect()(cfg, tasks, [t for t in task_ids if t != down], skill, attempts_root, batch_name)
            if down in task_ids:
                raise RuntimeError("1 of 2 attempts got no model response (llm-call-failed: 429)")
            return []

        with self.assertRaises(RuntimeError):
            self.collector(failing).run(self.wanted, chunk_size=2, log=QUIET)
        rows = self.ledger.rows()
        self.assertEqual([r["status"] for r in rows], ["failed"])
        self.assertIn("no model response", rows[0]["note"])
        retry = ScriptedCollect()
        status = self.collector(retry).run(self.wanted, chunk_size=10, log=QUIET)
        self.assertEqual(status["pending"], [])
        self.assertIn(down, retry.model_calls)
        self.assertNotIn(self.wanted[0], retry.model_calls)

    def test_infra_classification(self):
        self.assertTrue(is_infra_failure({"hard": 0, "fail_reason": "llm-call-failed: APIError"}))
        self.assertTrue(is_infra_failure({"hard": 0, "fail_reason": "task-timeout-120s"}))
        self.assertFalse(is_infra_failure({"hard": 0, "fail_reason": "exec-error: timeout after 120s"}))
        self.assertFalse(is_infra_failure({"hard": 0, "fail_reason": "eval-mismatch: A1"}))
        self.assertFalse(is_infra_failure({"hard": 1, "fail_reason": ""}))

    @unittest.skipUnless(HAVE_SKILLOPT, "needs skillopt")
    def test_records_are_selector_ready(self):
        from skillshift.collection import build_records

        outcomes = {t: ["pass"] for t in self.wanted[::4]}
        self.collector(ScriptedCollect(outcomes)).run(self.wanted, chunk_size=10, log=QUIET)
        records = build_records(self.cfg, self.tasks, self.root / "attempts", "dev_original")
        self.assertEqual(record_problems(records, self.wanted, self.cfg["selectors"]), [])
        self.assertEqual(len(records), 60)
        again = build_records(self.cfg, self.tasks, self.root / "attempts", "dev_original")
        self.assertEqual([r["summary"] for r in records], [r["summary"] for r in again])
        for r in records:
            self.assertTrue(r["summary"].strip())
            self.assertIsNone(r["embedding"])
            for identifier in (r["task_id"], r["record_id"], r["source_family"], r["workbook_hash"]):
                self.assertNotIn(identifier, r["summary"])
        failures = {r["summary"] for r in records if r["outcome"] == "failure"}
        self.assertEqual(len(failures), 1, "same behavior on different tasks should give one summary")

    @unittest.skipUnless(HAVE_SKILLOPT, "needs skillopt")
    def test_record_problems_flags_empty_summary_and_missing_task(self):
        from skillshift.collection import build_records

        self.collector(ScriptedCollect()).run(self.wanted, chunk_size=20, log=QUIET)
        records = build_records(self.cfg, self.tasks, self.root / "attempts", "dev_original")
        records[0]["summary"] = " "
        problems = record_problems(records[1:] + [records[0]], self.wanted, self.cfg["selectors"])
        self.assertTrue(any("empty summary" in p for p in problems))
        problems = record_problems(records[1:], self.wanted, self.cfg["selectors"])
        self.assertTrue(any("no evaluated attempt" in p for p in problems))


class SummaryTests(unittest.TestCase):
    def base(self, **kw):
        record = {"outcome": "failure", "error_category": "exec_error", "error_detail": "KeyError",
                  "task_type": "cell_level", "n_turns": 1, "tool_events": ["write_code", "exec_error"],
                  "fail_reason": "exec-error: KeyError 'Sheet2' at /tmp/x/y/123_pred.xlsx line 42"}
        record.update(kw)
        return record

    def test_fixed_template_strips_paths_values_and_numbers(self):
        text = summaries.behavior_summary(self.base(), "import openpyxl\n")
        self.assertEqual(text, (
            "Outcome: failure. Error category: exec_error (KeyError). Task type: cell_level. Turns: 1. "
            "Events: write_code -> exec_error. Code imports: openpyxl. "
            "Evaluator: exec-error: KeyError <value> at <path> line <n>."))

    def test_success_and_missing_code(self):
        text = summaries.behavior_summary(self.base(outcome="success", error_category="none", error_detail="",
                                                    fail_reason=""), None)
        self.assertIn("Outcome: success.", text)
        self.assertNotIn("Code imports", text)
        self.assertIn("all checked answer cells matched", text)

    def test_code_features(self):
        self.assertEqual(summaries.code_features("import pandas as pd\nfrom openpyxl.styles import Font\n"),
                         ["openpyxl", "pandas"])
        self.assertEqual(summaries.code_features(""), ["no code"])
        self.assertEqual(summaries.code_features("def ("), ["unparseable code"])


if __name__ == "__main__":
    unittest.main()
