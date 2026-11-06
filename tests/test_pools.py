"""Synthetic unit fixtures only; these are not experimental evidence or real pools."""
import copy
import csv
import hashlib
import json
import tempfile
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('build_pools', Path(__file__).resolve().parents[1] / 'scripts/build_pools.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.records = [dict(record_id=f'synthetic-{i}', task_id='synthetic-dev', split='dev',
                             source_family='synthetic-family', outcome='success' if i < 3 else 'failure',
                             payload={'fixture': i}) for i in range(6)]
        self.config = dict(status='approved', split_tasks={'dev': ['synthetic-dev'], 'val': ['synthetic-val'], 'test': ['synthetic-test']},
                           dominant_task_ids=['synthetic-dev'], pools=[dict(name=f'fixture_{i}', mechanism='exact_copy', repeat_fraction=r)
                           for i, r in enumerate([0, .25, .5, .75])])

    def test_exact_fractions_ratios_and_identity(self):
        before = copy.deepcopy(self.records)
        pools = module.build_pools(self.records, self.config)
        for pool, total, copies in zip(pools.values(), [6, 8, 12, 24], [0, 2, 6, 18]):
            stats = pool['stats']
            self.assertEqual((stats['total'], stats['copies'], stats['unique_originals']), (total, copies, 6))
            self.assertEqual(stats['success_fraction'], '1/2')
            self.assertEqual(stats['source_hhi'], 1)
            self.assertEqual(len({r['pool_record_id'] for r in pool['records']}), total)
            for row in pool['records']:
                payload = {k: v for k, v in row.items() if k not in ('pool_record_id', 'original_record_id', 'is_copy')}
                self.assertIn(payload, self.records)
                self.assertEqual(row['record_id'], row['original_record_id'])
        self.assertEqual(before, self.records)

    def test_rejects_leakage(self):
        for field, value in [('task_id', 'synthetic-test'), ('split', 'val')]:
            rows = copy.deepcopy(self.records)
            rows[0][field] = value
            with self.assertRaises(module.PoolError):
                module.build_pools(rows, self.config)

    def test_rejects_unresolved_or_undefined_mechanism(self):
        self.config['status'] = 'unresolved'
        with self.assertRaises(module.PoolError):
            module.build_pools(self.records, self.config)
        self.config['status'] = 'approved'
        self.config['pools'][0]['mechanism'] = 'C1'
        with self.assertRaises(module.PoolError):
            module.build_pools(self.records, self.config)

    def test_rejects_fraction_rounding(self):
        with self.assertRaisesRegex(module.PoolError, 'fraction infeasible'):
            module.build_pools(self.records[:5], self.config)

    def test_rejects_outcome_rounding(self):
        rows = copy.deepcopy(self.records)
        rows[0]['outcome'] = 'failure'
        with self.assertRaisesRegex(module.PoolError, 'ratio infeasible'):
            module.build_pools(rows, self.config)

    def test_requires_dominant_outcome_coverage(self):
        self.config['split_tasks']['dev'].append('other-dev')
        for row in self.records[3:]:
            row['task_id'] = 'other-dev'
        with self.assertRaisesRegex(module.PoolError, 'lack failure'):
            module.build_pools(self.records, self.config)

    def test_rejects_overlapping_splits(self):
        self.config['split_tasks']['val'].append('synthetic-dev')
        with self.assertRaisesRegex(module.PoolError, 'disjoint'):
            module.build_pools(self.records, self.config)

    def test_rejects_duplicate_input_identity(self):
        with self.assertRaisesRegex(module.PoolError, 'Duplicate'):
            module.build_pools(self.records + [self.records[0]], self.config)

    def test_rejects_inconsistent_task_family(self):
        self.records[0]['source_family'] = 'different-family'
        with self.assertRaisesRegex(module.PoolError, 'inconsistent'):
            module.build_pools(self.records, self.config)

    def test_task_manifest_adapter(self):
        config = {k: v for k, v in self.config.items() if k != 'split_tasks'}
        manifest = [dict(id='synthetic-dev', split='dev', family_id='synthetic-family'),
                    dict(id='synthetic-val', split='val', family_id='val-family'),
                    dict(id='synthetic-test', split='test', family_id='test-family')]
        bound = module.apply_task_manifest(config, manifest)
        module.build_pools(self.records, bound)
        rows = copy.deepcopy(self.records)
        for row in rows:
            row['source_family'] = 'wrong-family'
        with self.assertRaisesRegex(module.PoolError, 'does not match'):
            module.build_pools(rows, bound)
        conflicting = copy.deepcopy(self.config)
        conflicting['split_tasks']['dev'].append('wrong-task')
        with self.assertRaisesRegex(module.PoolError, 'disagree'):
            module.apply_task_manifest(conflicting, manifest)
        manifest[1]['split'] = 'train'
        with self.assertRaisesRegex(module.PoolError, 'dev/val/test'):
            module.apply_task_manifest(config, manifest)

    def test_manifest_rejects_family_leakage(self):
        rows = [dict(id='a', split='dev', family_id='shared'),
                dict(id='b', split='test', family_id='shared')]
        with self.assertRaisesRegex(module.PoolError, 'family crosses'):
            module.apply_task_manifest({}, rows)

    def test_csv_and_provenance(self):
        pools = module.build_pools(self.records, self.config)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'synthetic.jsonl'
            source.write_text(''.join(json.dumps(r) + '\n' for r in self.records))
            output = root / 'output'
            module.write_outputs(pools, self.config, source, output)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(manifest['provenance']['attempts']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            with (output / 'pool_stats.csv').open() as handle:
                stats = list(csv.DictReader(handle))
            self.assertEqual(len(stats), 4)
            self.assertEqual([int(r['copies']) for r in stats], [0, 2, 6, 18])
            self.assertEqual(stats[0]['pool_name'], 'fixture_0')


if __name__ == '__main__':
    unittest.main()
