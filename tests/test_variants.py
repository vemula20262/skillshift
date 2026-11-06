import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_variants import select,validate
from build_pools import apply_task_manifest,build_pools,PoolError
class VariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.audit=json.loads((ROOT/'datasets/400/source_manifest.json').read_text())
    def test_counts_flags_and_order_independence(self):
        for variant,n in [('120',120),('400',398)]:
            source,active=select(copy.deepcopy(self.audit),variant)
            validate(source,active,variant)
            self.assertEqual(len(active),n)
            self.assertFalse({'56225','56274'} & {t['id'] for t in active})
            if variant=='120':self.assertFalse({'130-9','283-32','73-45'} & {t['id'] for t in active})
            other,otheractive=select(copy.deepcopy(list(reversed(self.audit))),variant)
            self.assertEqual({t['id']:t['split'] for t in active},{t['id']:t['split'] for t in otheractive})
    def test_flagged_task_cannot_be_reintroduced(self):
        source,active=select(copy.deepcopy(self.audit),'400')
        with self.assertRaisesRegex(ValueError,'exclusions'):validate(source,source,'400')
    def test_pool_adapter_rejects_excluded_attempt(self):
        _,active=select(copy.deepcopy(self.audit),'400')
        config=apply_task_manifest({'status':'approved','dominant_task_ids':[active[0]['id']],'pools':[{'name':'baseline','mechanism':'exact_copy','repeat_fraction':0}]},active)
        r={'record_id':'synthetic','task_id':'56225','source_family':'observed-56225','split':'dev','outcome':'success'}
        with self.assertRaises(PoolError):build_pools([r],config)
