import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from prepare_full_dataset import allocate,UNCERTAIN
class FullDatasetTests(unittest.TestCase):
    def test_full_allocation_is_complete_deterministic_and_group_safe(self):
        ids=sorted({x for pair in UNCERTAIN for x in pair})
        ids += [f'fixture-{i}' for i in range(400-len(ids))]
        rows=[{'id':i,'initial_audit':{'sha256':i,'cell_content_sha256':i}} for i in ids]
        a=allocate(rows);b=allocate(list(reversed(rows)))
        mapping=lambda rs:{r['id']:(r['split'],r['split_group_id']) for r in rs}
        self.assertEqual(mapping(a),mapping(b))
        self.assertEqual(len(mapping(a)),400)
        for split,n in [('dev',200),('val',100),('test',100)]:self.assertEqual(sum(r['split']==split for r in a),n)
        for x,y in UNCERTAIN:self.assertEqual(mapping(a)[x],mapping(a)[y])
    def test_rejects_missing_or_duplicate_task(self):
        with self.assertRaises(ValueError):allocate([{'id':'duplicate'}]*400)
