import importlib.util
from pathlib import Path
import unittest
import io
import zipfile
ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
prep=module('prepare_data');validator=module('validate_split')
class DataTests(unittest.TestCase):
    def test_empty_inline_string_and_shared_string_equivalence(self):
        def workbook(cell, shared=None):
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Data"/></sheets></workbook>')
                z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row>'+cell+'<c r="B1" t="inlineStr"/></row></sheetData></worksheet>')
                if shared: z.writestr('xl/sharedStrings.xml',shared)
            return out.getvalue()
        inline=workbook('<c r="A1" t="inlineStr"><is><t>hello</t></is></c>')
        shared=workbook('<c r="A1" t="s"><v>0</v></c>','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>hello</t></si></sst>')
        self.assertEqual(prep.workbook_audit(inline)['cell_content_sha256'],prep.workbook_audit(shared)['cell_content_sha256'])
        self.assertEqual(prep.workbook_audit(inline)['nonempty_cells'],1)
    def test_shared_workbooks_are_grouped_transitively(self):
        rows=[{'id':i,'initial_audit':{'sha256':raw,'cell_content_sha256':cell}} for i,raw,cell in [('a','raw1','cell1'),('b','raw1','cell2'),('c','raw3','cell2'),('d','raw4','cell4')]]
        groups=prep.make_groups(rows)
        self.assertEqual(sorted(map(len,groups.values())),[1,3])
        self.assertEqual(rows[0]['family_id'],rows[2]['family_id'])
    def test_group_selection_exact_size_and_indivisible(self):
        groups={'a':[1]*4,'b':[1]*3,'c':[1]*2}
        picked=prep.choose_groups(groups,5,'test')
        self.assertEqual(set(picked),{'b','c'})
        with self.assertRaises(ValueError):prep.choose_groups(groups,1,'test')
    def test_validator_rejects_cross_split_content_leak(self):
        rows=[]
        for split,count in [('dev',60),('val',30),('test',30)]:
            for i in range(count):
                ident=f'{split}-{i}';rows.append({'id':ident,'split':split,'family_id':ident,'initial_audit':{'sha256':ident,'cell_content_sha256':ident}})
        self.assertEqual(validator.validate(rows),[])
        rows[-1]['initial_audit']['cell_content_sha256']=rows[0]['initial_audit']['cell_content_sha256']
        self.assertTrue(any('cross-split' in e for e in validator.validate(rows)))
if __name__=='__main__':unittest.main()
