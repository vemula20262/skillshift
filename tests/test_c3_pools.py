import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_pools import build_pools, PoolError

class C3Tests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(record_id=str(i), task_id=str(i), source_family=str(i), split='dev',
                          outcome='success' if i == 0 else 'failure',
                          error_category='none' if i == 0 else ('exec_error' if i < 3 else 'wrong_values'))
                     for i in range(4)]
        self.config = dict(status='approved', split_tasks={'dev':['0','1','2','3'],'val':[],'test':[]},
                           dominant_task_ids=['0','3'], pools=[dict(name='C3',mechanism='exact_copy',
                           repeat_fraction=.5,dominant_task_ids=['0','1','2'],failure_category='exec_error')])
    def test_copies_preserve_outcomes_and_target_category(self):
        before = copy.deepcopy(self.rows)
        rows = build_pools(self.rows,self.config)['C3']['records']
        copies = [r for r in rows if r['is_copy']]
        self.assertEqual(len(rows),8)
        self.assertEqual(sum(r['outcome']=='success' for r in copies),1)
        self.assertEqual({r['task_id'] for r in copies if r['outcome']=='failure'},{'1','2'})
        self.assertEqual(self.rows,before)
    def test_reject_wrong_category_or_single_failure_task(self):
        for ids in (['0','1','3'],['0','1']):
            self.config['pools'][0]['dominant_task_ids']=ids
            with self.assertRaises(PoolError): build_pools(self.rows,self.config)
    def test_reject_nondev_override(self):
        self.config['pools'][0]['dominant_task_ids']=['0','outside']
        with self.assertRaises(PoolError): build_pools(self.rows,self.config)
