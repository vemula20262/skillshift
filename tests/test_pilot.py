"""Offline checks for the validation-only pilot runner, results table and cost ledger.

Pools are built with the team's scripts/build_pools.py from synthetic records, and
skillshift.update.run_update is replaced by a stand-in that writes a run log in the
same format. No model, workbook or skillopt install is needed. These outputs live
in temporary directories and never mix with real results.
"""
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skillshift import pilot  # noqa: E402
from skillshift.config import load_config  # noqa: E402
from skillshift.update import load_tasks  # noqa: E402
from skillshift.usage import Ledger, Pricing, burn_chart_svg, summarize, totals  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_pools", ROOT / "scripts" / "build_pools.py")
build_pools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_pools)

QUIET = {"log": lambda *_: None}


def synthetic_records(tasks):
    dev = [t for t in tasks if t["split"] == "dev"]
    records = []
    for i, task in enumerate(dev):
        success = i % 3 == 0
        records.append({
            "record_id": f"dev_original-{task['id']}", "task_id": task["id"], "source_family": task["family_id"],
            "split": "dev", "workbook_hash": task["initial_audit"]["sha256"], "env_version": "test",
            "feedback_source": "original", "outcome": "success" if success else "failure",
            "error_category": "none" if success else "wrong_values", "fail_reason": "" if success else "eval-mismatch",
            "instruction": "x", "task_type": "cell_level", "n_turns": 1, "tool_events": ["write_code"],
            "token_count": 100, "trajectory_path": f"raw/dev_original/predictions/{task['id']}",
            "trajectory_sha256": hashlib.sha256(task["id"].encode()).hexdigest(),
            "summary": "Outcome: failure.", "embedding": None,
        })
    return records


class FakeRunUpdate:
    """Writes run.json the way skillshift.update.run_update does, with scripted gate results."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = set(fail_on or ())

    def __call__(self, cfg, *, pool_path, selector_name, attempts_root, out_root, seed, val_ids):
        run_id = f"{pool_path.stem}__{selector_name}__seed{seed}"
        run_dir = out_root / "runs" / run_id
        if run_dir.exists():
            raise FileExistsError(run_dir)
        run_dir.mkdir(parents=True)
        self.calls.append((run_id, list(val_ids), cfg["evaluation"]["test_policy"]))
        if run_id in self.fail_on:
            raise RuntimeError("simulated failure after the run directory was created")
        edited = selector_name != "exact_dedup"
        child = 12 if selector_name == "unfiltered" else 10
        n = len(val_ids)
        log = {
            "run_id": run_id, "pool_sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
            "selector": selector_name, "seed": seed, "config_hash": "c", "models": {"target": "m"},
            "parent_skill_sha256": "p", "token_budget": cfg["feedback"]["token_budget"],
            "feedback_tokens": 4000, "edited": edited, "val_task_ids": sorted(val_ids),
            "gate": {"accepted": edited and child > 10, "margin_tasks": cfg["gate"]["margin_tasks"], "n_tasks": n,
                     "parent_solved": 10, "child_solved": child if edited else 10},
            "test_evaluated": cfg["evaluation"]["test_policy"] != "none",
            "api_usage": {"_total": {"calls": 31, "total_tokens": 5000}},
        }
        (run_dir / "run.json").write_text(json.dumps(log))
        return log


class PilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.tasks = load_tasks(cls.cfg)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.records_path = self.root / "records.jsonl"
        records = synthetic_records(self.tasks)
        self.records_path.write_text("".join(json.dumps(r) + "\n" for r in records))
        dominant = [r["task_id"] for r in records[:4]]
        config = build_pools.apply_task_manifest({
            "status": "approved", "dominant_task_ids": dominant,
            "pools": [{"name": "C0", "mechanism": "exact_copy", "repeat_fraction": 0},
                      {"name": "C1_50", "mechanism": "exact_copy", "repeat_fraction": 0.5}],
        }, self.tasks)
        self.pool_dir = self.root / "pools"
        build_pools.write_outputs(build_pools.build_pools(records, config), config, self.records_path, self.pool_dir)
        self.pools = {name: self.pool_dir / f"{name}.jsonl" for name in pilot.POOLS}
        self.out = self.root / "pilot"
        self.ledger = Ledger(self.root / "cost.csv")
        self.val_ids = [t["id"] for t in self.tasks if t["split"] == "val"]

    def tearDown(self):
        self.tmp.cleanup()

    def run_pilot(self, fake, **kwargs):
        return pilot.run_pilot(self.cfg, pools=self.pools, attempts_root=self.root, out_root=self.out,
                               ledger=self.ledger, val_ids=self.val_ids, run_update=fake, **kwargs, **QUIET)

    def pool_problems(self, name, records_path=None):
        return pilot.pool_problems(self.pools[name], records_path or self.records_path, pilot.POOLS[name],
                                   self.pool_dir / "manifest.json", self.pool_dir / "pool_stats.csv")

    def test_grid_is_six_unique_combinations(self):
        self.assertEqual(len(pilot.GRID), 6)
        self.assertEqual(len(set(pilot.GRID)), 6)
        self.assertEqual({p for p, _ in pilot.GRID}, {"C0", "C1_50"})
        self.assertEqual({s for _, s in pilot.GRID}, {"unfiltered", "exact_dedup", "source_balanced"})
        for selector in pilot.SELECTORS:
            self.assertIn(selector, self.cfg["selectors"])

    def test_pilot_config_disables_test_without_touching_shared_config(self):
        self.assertEqual(pilot.pilot_config(self.cfg)["evaluation"]["test_policy"], "none")
        self.assertEqual(self.cfg["evaluation"]["test_policy"], "accepted")

    def test_pool_provenance_and_repeat_fractions(self):
        for name in pilot.POOLS:
            self.assertEqual(self.pool_problems(name), [])
        c1 = [json.loads(l) for l in self.pools["C1_50"].read_text().splitlines()]
        self.assertEqual(Fraction(sum(r["is_copy"] for r in c1), len(c1)), Fraction(1, 2))

    def test_pool_from_other_records_is_rejected(self):
        other = self.root / "other.jsonl"
        lines = self.records_path.read_text().splitlines()
        changed = json.loads(lines[0])
        changed["summary"] = "different"
        other.write_text("\n".join([json.dumps(changed)] + lines[1:]) + "\n")
        problems = self.pool_problems("C0", other)
        self.assertTrue(any("differs from its source record" in p for p in problems))
        self.assertTrue(any("pool manifest was built from attempts" in p for p in problems))

    def test_wrong_repeat_fraction_is_rejected(self):
        problems = pilot.pool_problems(self.pools["C1_50"], self.records_path, Fraction(1, 4))
        self.assertTrue(any("repeat fraction" in p for p in problems))

    def test_six_runs_validation_only_with_identical_settings(self):
        fake = FakeRunUpdate()
        outcome = self.run_pilot(fake)
        self.assertEqual(len(fake.calls), 6)
        self.assertTrue(all(policy == "none" for _, _, policy in fake.calls))
        self.assertEqual({tuple(v) for _, v, _ in fake.calls}, {tuple(self.val_ids)})
        self.assertTrue(all(o["state"] == "completed" and not o["problems"] for o in outcome.values()))
        self.assertEqual(pilot.consistency_problems(self.out, self.cfg["seed"]), [])
        rows = self.ledger.rows()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["phase"] == "update" and r["feedback_tokens_estimate"] == "4000" for r in rows))

    def test_restart_skips_completed_and_surfaces_partial(self):
        broken = pilot.run_id_for("C1_50", "source_balanced", self.cfg["seed"])
        first = FakeRunUpdate(fail_on=[broken])
        outcome = self.run_pilot(first)
        self.assertEqual(outcome[broken]["state"], "failed")
        failed_rows = [r for r in self.ledger.rows() if r["status"] == "failed"]
        self.assertEqual([r["label"] for r in failed_rows], [broken])

        second = FakeRunUpdate()
        outcome = self.run_pilot(second)
        self.assertEqual(second.calls, [])
        self.assertEqual(outcome[broken]["state"], "partial")
        self.assertEqual(sum(o["state"] == "skipped_completed" for o in outcome.values()), 5)
        self.assertEqual(len(self.ledger.rows()), 6)

        third = FakeRunUpdate()
        outcome = self.run_pilot(third, retry_partial=True)
        self.assertEqual([c[0] for c in third.calls], [broken])
        self.assertTrue((self.out / "partial" / broken).is_dir())
        self.assertEqual([r["event_id"] for r in self.ledger.rows() if r["label"] == broken],
                         [f"update:{broken}:1", f"update:{broken}:2"])
        rows, missing = pilot.results_table(self.out, self.cfg["seed"])
        self.assertEqual((len(rows), missing), (6, []))

    def test_completed_run_with_test_evaluation_is_flagged(self):
        self.run_pilot(FakeRunUpdate())
        path = self.out / "runs" / pilot.run_id_for("C0", "unfiltered", self.cfg["seed"]) / "run.json"
        log = json.loads(path.read_text())
        log["test_evaluated"] = True
        path.write_text(json.dumps(log))
        self.assertTrue(pilot.consistency_problems(self.out, self.cfg["seed"]))
        _, problems = pilot.run_state(self.out, self.pools["C0"], "unfiltered", self.cfg["seed"])
        self.assertTrue(any("test_evaluated" in p for p in problems))

    def test_results_table_distinguishes_unchanged_from_rejected(self):
        self.run_pilot(FakeRunUpdate(), only=[("C0", "unfiltered"), ("C0", "exact_dedup"), ("C0", "source_balanced")])
        rows, missing = pilot.results_table(self.out, self.cfg["seed"])
        self.assertEqual(missing, ["C1_50 x unfiltered", "C1_50 x exact_dedup", "C1_50 x source_balanced"])
        by_selector = {r["selector"]: r for r in rows}
        self.assertEqual(by_selector["unfiltered"]["gate_decision"], "accepted")
        self.assertEqual(by_selector["exact_dedup"]["gate_decision"], "no edit (skill unchanged)")
        self.assertEqual(by_selector["exact_dedup"]["child_val"], "")
        self.assertEqual(by_selector["source_balanced"]["gate_decision"], "rejected by gate")
        self.assertEqual(by_selector["source_balanced"]["child_val"], "10/30")
        self.assertEqual(by_selector["unfiltered"]["parent_val"], "10/30")


class CallEstimateTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_feedback_bound_uses_smallest_records_that_fit(self):
        pool = [{"token_count": n} for n in (500, 100, 300, 200)]
        self.assertEqual(pilot.max_feedback_records(pool, 600), 3)  # 100 + 200 + 300
        self.assertEqual(pilot.max_feedback_records(pool, 50), 0)

    def test_estimate_counts_validation_and_optimizer_stages(self):
        turns = self.cfg["executor"]["max_turns"]
        cached = pilot.estimate_run_calls(self.cfg, 30, 16, 0)
        uncached = pilot.estimate_run_calls(self.cfg, 30, 16, 30)
        self.assertEqual(uncached - cached, 30 * turns)
        self.assertGreaterEqual(cached, 30 * turns + 3 + 2 + 2)  # reflect, merges, final merge and rank
        self.assertGreater(pilot.estimate_run_calls(self.cfg, 30, 60, 0), cached)

    def test_cached_parent_validation_is_counted(self):
        from skillshift.update import _eval_settings_hash, sha256_text

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(pilot.cached_val_count(self.cfg, out, "skill", ["a", "b"]), 0)
            cache = out / "eval_cache" / _eval_settings_hash(self.cfg) / "val" / sha256_text("skill")[:16]
            cache.mkdir(parents=True)
            (cache / "results.jsonl").write_text(json.dumps({"id": "a"}) + "\n" + json.dumps({"id": "z"}) + "\n")
            self.assertEqual(pilot.cached_val_count(self.cfg, out, "skill", ["a", "b"]), 1)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name) / "cost.csv")
        self.usage = {"target": {"calls": 3, "prompt_tokens": 300, "completion_tokens": 30, "total_tokens": 330},
                      "_total": {"calls": 3, "prompt_tokens": 300, "completion_tokens": 30, "total_tokens": 330}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_totals_ignore_the_total_entry(self):
        self.assertEqual(totals(self.usage), {"api_calls": 3, "input_tokens": 300, "output_tokens": 30,
                                              "total_tokens": 330})

    def test_duplicate_event_is_not_counted_twice(self):
        self.assertTrue(self.ledger.record("e1", phase="collection", label="a", status="completed", summary=self.usage))
        self.assertFalse(self.ledger.record("e1", phase="collection", label="a", status="completed", summary=self.usage))
        self.assertEqual(len(self.ledger.rows()), 1)

    def test_feedback_estimate_kept_out_of_provider_totals(self):
        self.ledger.record("u1", phase="update", label="r", status="completed", summary=self.usage,
                           feedback_tokens_estimate=99999)
        summary = summarize(self.ledger.rows(), Pricing())
        self.assertEqual(summary["overall"]["total_tokens"], 330)
        self.assertIsNone(summary["overall"]["cost_usd"])

    def test_cost_and_chart_with_and_without_pricing(self):
        self.ledger.record("c1", phase="collection", label="a", status="partial", summary=self.usage)
        rows = self.ledger.rows()
        priced = summarize(rows, Pricing(1.0, 10.0, cap_usd=1.0))
        self.assertAlmostEqual(priced["overall"]["cost_usd"], (300 * 1 + 30 * 10) / 1e6)
        self.assertIn("cap_used_fraction", priced)
        self.assertIn("Cumulative cost (USD)", burn_chart_svg(rows, Pricing(1.0, 10.0, 1.0)))
        self.assertIn("pricing not set", burn_chart_svg(rows, Pricing()))
        self.assertIn("No measured usage yet", burn_chart_svg([], Pricing()))

    def test_csv_columns(self):
        self.ledger.record("c1", phase="collection", label="a", status="completed", summary={})
        with open(self.ledger.path, newline="") as f:
            header = next(csv.reader(f))
        self.assertIn("feedback_tokens_estimate", header)
        self.assertIn("infra_failures", header)


if __name__ == "__main__":
    unittest.main()
