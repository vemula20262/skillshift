"""Offline checks for the grid runner, with a stand-in run_update."""
import copy
import csv
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skillshift import grid  # noqa: E402
from skillshift.config import load_config  # noqa: E402
from skillshift.update import load_tasks  # noqa: E402
from skillshift.usage import Ledger  # noqa: E402
from test_pilot import synthetic_records  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_pools", ROOT / "scripts" / "build_pools.py")
build_pools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_pools)

_cli = importlib.util.spec_from_file_location("run_grid", ROOT / "scripts" / "run_grid.py")
run_grid = importlib.util.module_from_spec(_cli)
_cli.loader.exec_module(run_grid)

QUIET = {"log": lambda *_: None}
SPEC = {"pools": {"C0": "0", "C1_50": "1/2"}, "selectors": ["unfiltered", "source_balanced"], "seeds": [0, 1]}


class FakeRunUpdate:
    """Writes run.json (and a sealed test file when the policy asks) like run_update."""

    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def __call__(self, cfg, *, pool_path, selector_name, attempts_root, out_root, seed, val_ids):
        run_id = f"{pool_path.stem}__{selector_name}__seed{seed}"
        run_dir = out_root / "runs" / run_id
        run_dir.mkdir(parents=True)
        self.calls.append(run_id)
        if run_id in self.fail_on:
            raise RuntimeError("simulated endpoint failure")
        parent = {t: 0 for t in val_ids}
        child = {t: int(i < 3 + seed) for i, t in enumerate(sorted(val_ids))}
        accepted = sum(child.values()) - sum(parent.values()) >= cfg["gate"]["margin_tasks"]
        tested = cfg["evaluation"]["test_policy"] == "all" or (cfg["evaluation"]["test_policy"] == "accepted" and accepted)
        if tested:
            (out_root / "sealed").mkdir(exist_ok=True)
            (out_root / "sealed" / f"{run_id}.json").write_text(json.dumps(
                {"run_id": run_id, "parent": {"t1": 0, "t2": 1}, "child": {"t1": 1, "t2": 1}}))
        log = {
            "run_id": run_id, "pool_sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
            "selector": selector_name, "seed": seed, "config_hash": "c", "models": {"target": "m"},
            "parent_skill_sha256": "p", "token_budget": cfg["feedback"]["token_budget"], "feedback_tokens": 4000,
            "edited": True, "val_task_ids": sorted(val_ids), "val_per_task": {"parent": parent, "child": child},
            "gate": {"accepted": accepted, "margin_tasks": cfg["gate"]["margin_tasks"], "n_tasks": len(val_ids),
                     "parent_solved": 0, "child_solved": sum(child.values())},
            "test_evaluated": tested, "api_usage": {"_total": {"calls": 35, "total_tokens": 5000}},
        }
        (run_dir / "run.json").write_text(json.dumps(log))
        return log


class GridTests(unittest.TestCase):
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
        config = build_pools.apply_task_manifest({
            "status": "approved", "dominant_task_ids": [r["task_id"] for r in records[:4]],
            "pools": [{"name": "C0", "mechanism": "exact_copy", "repeat_fraction": 0},
                      {"name": "C1_50", "mechanism": "exact_copy", "repeat_fraction": 0.5}],
        }, self.tasks)
        self.pool_dir = self.root / "pools"
        build_pools.write_outputs(build_pools.build_pools(records, config), config, self.records_path, self.pool_dir)
        self.pools = {name: self.pool_dir / f"{name}.jsonl" for name in SPEC["pools"]}
        self.out = self.root / "grid"
        self.ledger = Ledger(self.root / "cost.csv")
        self.val_ids = [t["id"] for t in self.tasks if t["split"] == "val"]
        self.spec_path = self.root / "grid.json"
        self.spec_path.write_text(json.dumps(SPEC))

    def tearDown(self):
        self.tmp.cleanup()

    def run_all(self, fake, cfg=None):
        out = {}
        for seed, pool, selector in grid.combinations(SPEC):
            out[(seed, pool, selector)] = grid.run_one(
                cfg or self.cfg, seed=seed, pool=pool, selector=selector, pool_path=self.pools[pool],
                attempts_root=self.root, out_root=self.out, ledger=self.ledger, val_ids=self.val_ids,
                run_update=fake, **QUIET)
        return out

    def test_spec_is_checked(self):
        self.assertEqual(grid.load_spec(self.spec_path)["seeds"], [0, 1])
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"pools": {"C0": "half"}, "selectors": [], "seeds": [True]}))
        with self.assertRaisesRegex(ValueError, "repeat fraction"):
            grid.load_spec(bad)

    def test_runs_go_one_seed_at_a_time(self):
        combos = grid.combinations(SPEC)
        self.assertEqual(len(combos), 8)
        self.assertEqual([c[0] for c in combos], [0, 0, 0, 0, 1, 1, 1, 1])

    def test_pool_checks(self):
        for name, fraction in SPEC["pools"].items():
            self.assertEqual(grid.pool_problems(name, self.pools[name], self.records_path, fraction, self.pool_dir), [])
        # A pool without a repeat fraction (C2, C3) is only checked for schema and pool fields.
        loose = self.root / "C3.jsonl"
        rows = [json.loads(l) for l in self.pools["C0"].read_text().splitlines()]
        loose.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual(grid.pool_problems("C3", loose, self.records_path, None, self.pool_dir), [])
        for r in rows:
            r.pop("is_copy")
        loose.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertIn("C3: occurrence without pool fields",
                      grid.pool_problems("C3", loose, self.records_path, None, self.pool_dir))

    def test_untuned_semantic_selectors_are_reported(self):
        problems = grid.selector_problems(self.cfg, ["unfiltered", "semantic_dedup", "source_behavior", "nope"])
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("semantic_dedup" in p for p in problems))

    def test_full_run_then_restart_skips_completed(self):
        fake = FakeRunUpdate()
        outcomes = self.run_all(fake)
        self.assertTrue(all(o["state"] == "completed" and not o["problems"] for o in outcomes.values()))
        self.assertEqual(len(self.ledger.rows()), 8)
        again = FakeRunUpdate()
        self.assertTrue(all(o["state"] == "skipped_completed" for o in self.run_all(again).values()))
        self.assertEqual(again.calls, [])

    def test_failed_run_is_logged_and_left_partial(self):
        fake = FakeRunUpdate(fail_on={"C0__unfiltered__seed0"})
        outcome = self.run_all(fake)[(0, "C0", "unfiltered")]
        self.assertEqual(outcome["state"], "failed")
        failed = [r for r in self.ledger.rows() if r["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        state, _ = grid.run_state(self.cfg, self.out, self.pools["C0"], "unfiltered", 0)
        self.assertEqual(state, "partial")

    def test_test_policy_mismatch_is_flagged(self):
        none_cfg = copy.deepcopy(self.cfg)
        none_cfg["evaluation"]["test_policy"] = "none"
        self.run_all(FakeRunUpdate(), cfg=none_cfg)
        _, problems = grid.run_state(self.cfg, self.out, self.pools["C0"], "unfiltered", 0)
        self.assertTrue(any("test_policy" in p for p in problems))

    def test_estimate_includes_test_scoring(self):
        with_test = grid.estimate_calls(self.cfg, self.pools["C0"], 30, 30, 0, 30)
        none_cfg = copy.deepcopy(self.cfg)
        none_cfg["evaluation"]["test_policy"] = "none"
        without = grid.estimate_calls(none_cfg, self.pools["C0"], 30, 30, 0, 30)
        self.assertEqual(with_test - without, 60)

    def test_export_keeps_test_sealed_until_complete(self):
        fake = FakeRunUpdate(fail_on={"C1_50__source_balanced__seed1"})
        self.run_all(fake)
        argv = ["--pool-dir", str(self.pool_dir), "--spec", str(self.spec_path), "--records", str(self.records_path),
                "--out", str(self.out), "--cost-csv", str(self.root / "cost.csv"), "--export"]
        self.assertEqual(run_grid.main(argv), 2)
        report = self.out / "report"
        self.assertTrue((report / "grid_runs.csv").is_file())
        self.assertFalse((report / "test_per_task.csv").exists())

        shutil.rmtree(self.out / "runs" / "C1_50__source_balanced__seed1")
        self.run_all(FakeRunUpdate())
        self.assertEqual(run_grid.main(argv), 0)
        with open(report / "val_per_task.csv", newline="") as f:
            val_rows = list(csv.DictReader(f))
        self.assertEqual(len(val_rows), 8 * len(self.val_ids))
        with open(report / "test_per_task.csv", newline="") as f:
            test_rows = list(csv.DictReader(f))
        self.assertEqual(len(test_rows), 8 * 2)
        self.assertEqual({r["task_id"] for r in test_rows}, {"t1", "t2"})


if __name__ == "__main__":
    unittest.main()
