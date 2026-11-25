"""Dataset-size independence and manifest-bound development selection."""
import json
import math
from pathlib import Path
import unittest

from skillshift.io import validate_dev
from skillshift.selectors import METHODS, get_selector
from selector_helpers import build_pools_module
apply_task_manifest = build_pools_module.apply_task_manifest
build_pools = build_pools_module.build_pools

ROOT = Path(__file__).resolve().parents[1]


def attempts(manifest):
    return [dict(record_id=f"attempt-{task['id']}", task_id=task['id'],
                 source_family=task['family_id'], split='dev', summary='Wrong range',
                 outcome='failure', error_category='range', feedback_source='synthetic',
                 env_version='test-v1', token_count=4, embedding=[1.0, 0.0],
                 embedding_model='handcrafted-test-vectors', synthetic=True)
            for task in manifest if task['split'] == 'dev']


class SplitCompatibilityTests(unittest.TestCase):
    def test_all_selectors_process_both_complete_development_partitions(self):
        for variant, expected in [('120', 60), ('400', 198)]:
            with self.subTest(variant=variant):
                manifest = json.loads((ROOT / f'datasets/{variant}/task_manifest.json').read_text())
                rows = attempts(manifest)
                self.assertEqual(len(rows), expected)
                validate_dev(rows, manifest)
                config = apply_task_manifest(dict(status='approved',
                    dominant_task_ids=[rows[0]['task_id']], pools=[
                        dict(name='repeat', mechanism='exact_copy', repeat_fraction=.5)]), manifest)
                pooled = build_pools(rows, config)['repeat']['records']
                validate_dev(pooled, manifest)
                families = {r['source_family'] for r in rows}
                for method in METHODS:
                    result = get_selector(method, 1.0).select(pooled)
                    self.assertEqual(result.input_count, 2 * expected)
                    if method in ('exact_dedup', 'semantic_dedup'):
                        self.assertEqual(len(result.items), 1)
                        self.assertEqual(set(result.items[0].families), families)
                    else:
                        self.assertEqual(len(result.items), 2 * expected)
                        weights = math.fsum(item.weight for item in result.items)
                        self.assertAlmostEqual(weights, 2 * expected if method == 'unfiltered' else len(families))

    def test_custom_sizes_and_multiple_tasks_per_family(self):
        for sizes in [(1, 1, 1), (7, 2, 4), (13, 5, 2)]:
            manifest = [dict(id=f'{split}-{i}', family_id=f'{split}-family-{i // 2}',
                             split_group_id=f'{split}-block-{i // 2}', split=split)
                        for split, count in zip(('dev', 'val', 'test'), sizes) for i in range(count)]
            rows = attempts(manifest)
            validate_dev(rows, manifest)
            families = {r['source_family'] for r in rows}
            for method in METHODS:
                with self.subTest(sizes=sizes, method=method):
                    result = get_selector(method, .9).select(rows)
                    self.assertEqual(result.input_count, sizes[0])
                    if method in ('source_balanced', 'source_behavior'):
                        self.assertAlmostEqual(math.fsum(i.weight for i in result.items), len(families))
            raw = {split: [t['id'] for t in manifest if t['split'] == split]
                   for split in ('dev', 'val', 'test')}
            for mapping in (raw, {'splits': raw}, dict(dev=raw['dev'], validation=raw['val'], test=raw['test'])):
                validate_dev(rows, mapping)

    def test_validation_and_test_records_are_rejected_for_each_variant(self):
        for variant in ('120', '400'):
            manifest = json.loads((ROOT / f'datasets/{variant}/task_manifest.json').read_text())
            sample = attempts(manifest)[0]
            for split in ('val', 'test'):
                task = next(t for t in manifest if t['split'] == split)
                # Even a record falsely labelled dev must fail manifest membership.
                row = dict(sample, task_id=task['id'], source_family=task['family_id'])
                with self.subTest(variant=variant, split=split), self.assertRaisesRegex(ValueError, 'Non-development'):
                    validate_dev([row], manifest)



if __name__ == '__main__':
    unittest.main()
