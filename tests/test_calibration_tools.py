"""Offline calibration and trajectory identity regressions."""
import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from skillshift.tuning import tune
from skillshift.__main__ import calibration_provenance
from skillshift.io import write_json
from skillshift.selectors import get_selector
from selector_helpers import record

class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [record(1), record(2), record(3, vector=[0, 1])]
        for row in self.rows:
            row['embedding_model'] = 'fixture@revision'
        self.pairs = [dict(left_id='1', right_id='2', equivalent=True),
                      dict(left_id='1', right_id='3', equivalent=False)]
        self.manifest = {'dev': ['task-A'], 'val': ['v'], 'test': ['t']}

    def test_development_calibration_and_leakage(self):
        result = tune(self.rows, self.pairs, [.5, 1.0], self.manifest)
        self.assertEqual(result['threshold'], 1.0)
        self.assertEqual(result['embedding_model'], 'fixture@revision')
        self.rows[0]['split'] = 'test'
        with self.assertRaises(ValueError):
            tune(self.rows, self.pairs, [.5], self.manifest)

    def test_pooled_and_one_class_pairs_rejected(self):
        with self.assertRaises(ValueError):
            tune(self.rows, self.pairs[:1], [.5], self.manifest)
        self.rows[0]['pool_record_id'] = 'pool:1'
        with self.assertRaises(ValueError):
            tune(self.rows, self.pairs, [.5], self.manifest)

    def test_zero_f1_has_no_threshold(self):
        self.rows[1]['embedding'] = [-1, 0]
        result = tune(self.rows, self.pairs, [.5], self.manifest)
        self.assertIsNone(result['threshold'])
        self.assertEqual(result['status'], 'no_informative_threshold')

    def test_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            write_json(path, {'original': True})
            with self.assertRaises(FileExistsError):
                write_json(path, {})
            self.assertEqual(json.loads(path.read_text()), {'original': True})

    def test_hash_required_and_true_copies_merge(self):
        rows = [record(1), record(2)]
        rows[1]['summary'] = 'Alternative derived summary'
        self.assertEqual(len(get_selector('exact_dedup').select(rows).items), 1)
        for value in [None, '', 'bad', 'g' * 64]:
            rows[1]['trajectory_sha256'] = value
            with self.assertRaises(ValueError):
                get_selector('exact_dedup').select(rows)

    def test_cli_tune_select_and_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records, pairs, manifest, calibrated = [root / name for name in
                ('records.jsonl', 'pairs.jsonl', 'manifest.json', 'calibration.json')]
            records.write_text(''.join(json.dumps(r) + '\n' for r in self.rows))
            pairs.write_text(''.join(json.dumps(r) + '\n' for r in self.pairs))
            manifest.write_text(json.dumps(self.manifest))
            command = [sys.executable, '-m', 'skillshift', 'tune', '--input', str(records),
                       '--pairs', str(pairs), '--task-manifest', str(manifest),
                       '--candidates', '.5', '1', '--output', str(calibrated)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(calibrated.read_text())
            self.assertEqual(artifact['input_sha256'], hashlib.sha256(records.read_bytes()).hexdigest())
            args = SimpleNamespace(threshold=None, calibration=str(calibrated))
            calibration_provenance(args, self.rows, manifest)
            self.assertEqual(args.threshold, 1.0)
            self.rows[0]['embedding_model'] = 'other@revision'
            with self.assertRaises(ValueError):
                calibration_provenance(args, self.rows, manifest)
            self.rows[0]['embedding_model'] = 'fixture@revision'
            manifest.write_text(json.dumps(self.manifest) + ' ')
            with self.assertRaises(ValueError):
                calibration_provenance(args, self.rows, manifest)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('Traceback', result.stderr)

    def test_synthetic_pairs_cannot_be_disguised_by_unpaired_real_record(self):
        for row in self.rows:
            row['synthetic'] = True
        artifact = tune(self.rows, self.pairs, [.5, 1.0], self.manifest)
        self.assertTrue(artifact['synthetic'])
        real = record(4)
        real['embedding_model'] = 'fixture@revision'
        with self.assertRaisesRegex(ValueError, 'mix synthetic and real'):
            tune(self.rows + [real], self.pairs, [.5, 1.0], self.manifest)
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            manifest.write_text(json.dumps(self.manifest))
            artifact['manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            path = Path(directory) / 'calibration.json'
            write_json(path, artifact)
            args = SimpleNamespace(threshold=None, calibration=str(path))
            with self.assertRaisesRegex(ValueError, 'Synthetic calibration'):
                calibration_provenance(args, [real], manifest)

    def test_synthetic_markers_must_be_boolean(self):
        for invalid in ['false', 'true', 0, 1, None, []]:
            with self.subTest(marker=invalid):
                self.rows[0]['synthetic'] = invalid
                with self.assertRaisesRegex(ValueError, 'markers must be boolean'):
                    tune(self.rows, self.pairs, [.5], self.manifest)

    def test_cli_invalid_pairs_report_errors_without_output(self):
        malformed = [None, [], {}, {'left_id': '1', 'right_id': '2'},
                     dict(left_id=[], right_id='2', equivalent=True),
                     dict(left_id='1', right_id={}, equivalent=True),
                     dict(left_id='', right_id='2', equivalent=True),
                     dict(left_id=' ', right_id='2', equivalent=True),
                     dict(left_id='1', right_id='2', equivalent='true'),
                     dict(left_id='1', right_id='missing', equivalent=True)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records, pairs, manifest, output = [root / name for name in
                ('records.jsonl', 'pairs.jsonl', 'manifest.json', 'result.json')]
            records.write_text(''.join(json.dumps(r) + '\n' for r in self.rows))
            manifest.write_text(json.dumps(self.manifest))
            for bad in malformed:
                with self.subTest(pair=bad):
                    pairs.write_text(json.dumps(bad) + '\n')
                    result = subprocess.run(
                        [sys.executable, '-m', 'skillshift', 'tune', '--input', str(records),
                         '--pairs', str(pairs), '--task-manifest', str(manifest),
                         '--candidates', '.5', '--output', str(output)],
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn('Pair 1:', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertFalse(output.exists())
