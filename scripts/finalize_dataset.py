#!/usr/bin/env python3
"""Build immutable working dataset v1 after input-only family screening.
Uncertain lineage is excluded, never represented as a confirmed family merge.
"""
import csv, hashlib, json, tarfile
from collections import Counter
from pathlib import Path
from prepare_data import choose_groups
from validate_split import validate
ROOT=Path(__file__).resolve().parents[1]
UNCERTAIN={
 ('23-24','118-50'):'Large shared dictionary vocabulary; workbook lineage cannot be established.',
 ('80-42','192-22'):'106 uncommon shared business descriptions; possible reused business source.',
 ('146-49','147-48'):'Small word-list content is contained in larger dictionary; possible derived example.',
 ('290-1','146-49'):'Shared unusual anagram strings; possible derived word-list source.',
 ('379-36','496-15'):'Related ledger headers and high layout overlap; changed-value variant cannot be excluded.',
 ('141-20','388-47'):'Matching date/period reconciliation headers; source lineage unresolved.',
 ('11276','11842'):'Related attendance labels and workbook purpose; template lineage unresolved.'}
def main():
    prepared=ROOT/'data/prepared'; review=ROOT/'data/family_review'
    audit=json.loads((prepared/'audit.json').read_text())
    pairs=json.loads((review/'candidates.json').read_text())
    excluded={x for pair in UNCERTAIN for x in pair}
    decisions=[]
    for p in pairs:
        key=(p['a'],p['b']); reason=UNCERTAIN.get(key)
        decisions.append(dict(p,decision='exclude_both_uncertain_lineage' if reason else 'no_merge_evidence',reason=reason or 'Shared examples are generic names, calendar terms, categories, or labels; the recorded cell/layout evidence does not establish a shared workbook. Similar vocabulary alone is not a family rule.'))
    out=ROOT/'data/final_v1'
    if out.exists(): raise SystemExit('Refusing to overwrite final_v1; use a new version for changes.')
    remaining={t['id']:[t] for t in audit if t['id'] not in excluded}; selected=[]
    for split,n in [('dev',60),('val',30),('test',30)]:
        for gid in choose_groups(remaining,n,'reviewed-v1-'+split):
            for t in remaining.pop(gid): selected.append(dict(t,split=split,status='frozen_working_dataset_v1',family_evidence='No shared workbook evidence after exact-hash and heuristic input-content screening; unobserved lineage remains possible.'))
    errors=validate(selected)
    if errors: raise ValueError(errors)
    out.mkdir()
    with tarfile.open(ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz') as tar:
        for t in selected:
            for role in ('initial','golden'):
                rel=Path('inputs' if role=='initial' else 'evaluator_only')/t['id']/(role+'.xlsx')
                content=tar.extractfile(t[role+'_archive_path']).read()
                assert hashlib.sha256(content).hexdigest()==t[role+'_audit']['sha256']
                (out/rel).parent.mkdir(parents=True,exist_ok=True);(out/rel).write_bytes(content)
                t[role+'_local_path']=str(rel)
    def save(name,obj): (out/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')
    def table(name,fields,rows):
        with (out/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    save('task_manifest.json',selected)
    save('splits.json',{'status':'frozen_working_dataset_v1','splits':{s:[t['id'] for t in selected if t['split']==s] for s in ('dev','val','test')}})
    save('family_review_decisions.json',decisions)
    table('tasks_120.csv',['id','split','family_id','instruction_type','instruction','answer_position','initial_local_path','golden_local_path','status'],selected)
    table('families.csv',['id','family_id','family_evidence'],selected)
    table('merge_log.csv',['family_id','member_ids','evidence'],[])
    table('excluded_tasks.csv',['id','reason'],[{'id':i,'reason':' | '.join(reason for pair,reason in UNCERTAIN.items() if i in pair)} for i in sorted(excluded)])
    selected_ids={t['id'] for t in selected}
    table('not_selected.csv',['id','reason'],[{'id':t['id'],'reason':'Eligible but not selected by deterministic sampling'} for t in audit if t['id'] not in excluded|selected_ids])
    table('rejected_tasks.csv',['id','reason'],[])
    summary={'status':'frozen working dataset v1; not a claim of team signoff','date':'2026-11-03','source_tasks':len(audit),'structural_rejections':0,'lineage_uncertainty_exclusions':len(excluded),'eligible_after_exclusions':len(audit)-len(excluded),'selected':len(selected),'eligible_not_selected':len(audit)-len(excluded)-len(selected),'split_counts':dict(Counter(t['split'] for t in selected)),'task_types':dict(Counter(t['instruction_type'] for t in selected)),'pairs_screened':79800,'flagged_pairs_reviewed':len(decisions),'uncertain_pairs':len(UNCERTAIN),'confirmed_merges':0,'human_review_status':'No human signoff recorded','selection':'skillshift-candidate-v1 hash ordering with reviewed-v1-{split} salt; no outcome-based selection','limitations':['Heuristic screening does not prove source independence and may miss transformed variants.','Excluding uncertain sources can alter representativeness; retain exclusion log and report this limitation.','No model executions, evaluator correctness certification, or outcome labels.','Unusual answer ranges remain raw and require evaluator integration.'],'archive_sha256':hashlib.sha256((ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz').read_bytes()).hexdigest()}
    save('provenance.json',summary)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()}
    save('SHA256SUMS.json',hashes)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
