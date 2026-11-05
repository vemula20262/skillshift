#!/usr/bin/env python3
"""Screen input workbooks for possible variants; never auto-merge on similarity."""
import collections, csv, io, json, tarfile, zipfile
from prepare_data import audit_archive
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def features(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        texts=set(); cells=set(); layout=set()
        for i,name in enumerate(sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))):
            for c in ET.fromstring(z.read(name)).findall('.//m:sheetData/m:row/m:c',NS):
                t=c.attrib.get('t','n'); v=c.find('m:v',NS); value=v.text if v is not None else None
                if t=='s' and value is not None: value=strings[int(value)]; t='text'
                elif t=='inlineStr':
                    e=c.find('m:is',NS); value=''.join(e.itertext()) if e is not None else None; t='text'
                if value is None or not str(value).strip(): continue
                value=str(value).strip().casefold(); loc=(i,c.attrib['r'])
                layout.add(loc); cells.add((*loc,t,value))
                if t=='text' and len(value)>=4: texts.add(value)
        return texts,cells,layout

def main():
    tasks=audit_archive(ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz'); fs={}
    with tarfile.open(ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz') as tar:
        for t in tasks: fs[t['id']]=features(tar.extractfile(t['initial_archive_path']).read())
    freq=collections.Counter(x for f in fs.values() for x in f[0]); pairs=[]
    for i,a in enumerate(tasks):
        at,ac,al=fs[a['id']]
        for b in tasks[i+1:]:
            bt,bc,bl=fs[b['id']]; shared=at&bt; rare={x for x in shared if freq[x]<=5}
            cell_overlap=len(ac&bc)/max(1,min(len(ac),len(bc)))
            layout_j=len(al&bl)/max(1,len(al|bl))
            text_overlap=len(shared)/max(1,min(len(at),len(bt)))
            if len(rare)>=3 or (len(ac&bc)>=15 and cell_overlap>=.7) or (len(shared)>=5 and text_overlap>=.75):
                pairs.append({'a':a['id'],'b':b['id'],'shared_rare_texts':len(rare),'cell_overlap':round(cell_overlap,4),'layout_jaccard':round(layout_j,4),'text_overlap':round(text_overlap,4),'shared_examples':sorted(rare or shared)[:12],'instruction_a':a['instruction'],'instruction_b':b['instruction'],'decision':'needs_evidence_review'})
    pairs.sort(key=lambda p:(-p['shared_rare_texts'],-p['cell_overlap']))
    dest=ROOT/'data/family_review';dest.mkdir(exist_ok=True)
    (dest/'candidates.json').write_text(json.dumps(pairs,indent=2,ensure_ascii=False)+'\n')
    (dest/'screening.json').write_text(json.dumps({'tasks':len(tasks),'pairs_screened':len(tasks)*(len(tasks)-1)//2,'flagged_pairs':len(pairs),'method':'Rare shared text OR high matching cell containment OR high text containment. Input workbooks only. Similarity is candidate evidence, not a merge rule.','limitations':'Heuristic screen may miss transformed variants. No upstream source lineage available in metadata.'},indent=2)+'\n')
    print(json.dumps({'pairs_screened':len(tasks)*(len(tasks)-1)//2,'flagged_pairs':len(pairs)}))
    for p in pairs: print(json.dumps(p,ensure_ascii=False))
if __name__=='__main__':main()
