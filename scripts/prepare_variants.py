#!/usr/bin/env python3
"""Build separate reviewed dataset packages; source warnings never enter runnable sets."""
import argparse,collections,csv,hashlib,json,tarfile
from pathlib import Path
from prepare_data import choose_groups, audit_archive, EXPECTED
from source_families import UNCERTAIN, allocate
ROOT=Path(__file__).resolve().parents[1]
# Tasks the benchmark evaluator cannot score meaningfully; excluded from the 120 version before sampling.
EVALUATOR_UNUSABLE={
 '130-9':'Answer position cannot be parsed by the evaluator (sheet name contains commas).',
 '283-32':'Answer position cannot be parsed by the evaluator (unbalanced quote, whole-column ranges).',
 '73-45':'Initial file already passes verification.'}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def select(audit,variant):
    flagged={r['id'] for r in audit if r.get('exclude')}
    if variant=='400': source=allocate(audit)
    else:
        uncertain={i for pair in UNCERTAIN for i in pair}
        remaining={t['id']:[t] for t in audit if t['id'] not in flagged|uncertain|set(EVALUATOR_UNUSABLE)};source=[]
        for split,n in [('dev',60),('val',30),('test',30)]:
            for gid in choose_groups(remaining,n,'separate120-v2-'+split):
                for t in remaining.pop(gid):source.append(dict(t,split=split,split_group_id='block-'+t['id'],split_group_basis='singleton after conservative lineage exclusions'))
    for t in source:
        t['eligible_for_execution']=t['id'] not in flagged
        t['exclusion_reason']=t.get('exclude','')
        t['status']='separate_versions_v2'
    return source,[t for t in source if t['eligible_for_execution']]
def validate(source,active,variant):
    expected={'dev':60,'val':30,'test':30} if variant=='120' else {'dev':200,'val':100,'test':100}
    if collections.Counter(t['split'] for t in source)!=expected:raise ValueError('Wrong source split')
    if len({t['id'] for t in source})!=int(variant):raise ValueError('Wrong unique source size')
    wanted={t['id'] for t in source if not t.get('exclude')}
    if {t['id'] for t in active}!=wanted or len(active)!=len(wanted):raise ValueError('Runnable set does not enforce source exclusions')
    seen={}
    for t in source:
        for k,v in [('family',t['family_id']),('block',t['split_group_id']),('hash',t['initial_audit']['sha256']),('cells',t['initial_audit']['cell_content_sha256'])]:
            if seen.setdefault((k,v),t['split'])!=t['split']:raise ValueError('Cross-split leakage')
    byid={t['id']:t for t in source}
    for a,b in UNCERTAIN:
        if a in byid and b in byid and byid[a]['split']!=byid[b]['split']:raise ValueError('Uncertain pair leakage')
    return dict(collections.Counter(t['split'] for t in active))
def build(variant,base):
    out=base/variant
    if out.exists():raise ValueError('Output already exists; choose a fresh --output-root')
    audit=audit_archive(ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz')
    source,active=select(audit,variant);counts=validate(source,active,variant)
    archive=ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz'
    if digest(archive)!=EXPECTED:raise ValueError('Wrong archive checksum')
    out.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        for t in source:
            for role in ('initial','golden'):
                rel=Path('inputs' if role=='initial' else 'evaluator_only')/t['id']/(role+'.xlsx')
                content=tar.extractfile(t[role+'_archive_path']).read()
                if hashlib.sha256(content).hexdigest()!=t[role+'_audit']['sha256']:raise ValueError('Source hash mismatch')
                (out/rel).parent.mkdir(parents=True,exist_ok=True);(out/rel).write_bytes(content);t[role+'_local_path']=str(rel)
    def save(n,d):(out/n).write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
    def table(n,fields,rs):
        with (out/n).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(rs)
    save('source_manifest.json',source);save('task_manifest.json',active)
    save('splits.json',{'version':variant+'-v2','scope':'eligible execution only','splits':{s:[t['id'] for t in active if t['split']==s] for s in counts}})
    save('source_splits.json',{'splits':{s:[t['id'] for t in source if t['split']==s] for s in counts}})
    pilot=sorted([t['id'] for t in active if t['split']=='dev'],key=lambda i:hashlib.sha256(('pilot-'+variant+'-v2-'+i).encode()).hexdigest())[:10]
    save('pilot_10.json',pilot)
    for s in counts:save(s+'_executor.json',[{k:t[k] for k in ('id','instruction','instruction_type','split','family_id','split_group_id','initial_local_path')} for t in active if t['split']==s])
    table('tasks_'+variant+'.csv',['id','split','instruction_type','family_id','split_group_id','eligible_for_execution','exclusion_reason','initial_local_path','golden_local_path'],source)
    table('families.csv',['id','family_id','split_group_id','split_group_basis','eligible_for_execution'],source)
    table('merge_log.csv',['task_a','task_b','reason'],[])
    table('precautionary_group_log.csv',['task_a','task_b','reason'],[dict(task_a=a,task_b=b,reason=r) for (a,b),r in UNCERTAIN.items() if a in {t['id'] for t in source} and b in {t['id'] for t in source}])
    rejected=[]
    uncertain={i for pair in UNCERTAIN for i in pair}
    for t in audit:
        if t.get('exclude'):rejected.append(dict(id=t['id'],reason=t['exclude'],basis='upstream exclude note'))
        elif variant=='120' and t['id'] in uncertain:rejected.append(dict(id=t['id'],reason='Unresolved source lineage; conservative subset exclusion',basis='project precaution'))
        elif variant=='120' and t['id'] in EVALUATOR_UNUSABLE:rejected.append(dict(id=t['id'],reason=EVALUATOR_UNUSABLE[t['id']],basis='evaluator check'))
    table('rejected_tasks.csv',['id','reason','basis'],rejected)
    selected={t['id'] for t in source};rejectids={t['id'] for t in rejected}
    table('not_selected.csv',['id','reason'],[dict(id=t['id'],reason='Eligible but not sampled') for t in audit if t['id'] not in selected|rejectids])
    stats=[dict(split=s,source_tasks=sum(t['split']==s for t in source),eligible_tasks=counts[s],cell_level=sum(t['split']==s and t['instruction_type']=='Cell-Level Manipulation' for t in active),sheet_level=sum(t['split']==s and t['instruction_type']=='Sheet-Level Manipulation' for t in active)) for s in counts]
    table('data_summary.csv',['split','source_tasks','eligible_tasks','cell_level','sheet_level'],stats)
    save('protocol.json',{'version':variant+'-v2','source_tasks':len(source),'eligible_tasks':len(active),'eligible_split_counts':counts,'archive_sha256':EXPECTED,'family_policy':'Observed family_id is not confirmed provenance. split_group_id enforces precautionary isolation; use blocks for conservative resampling.','sampling':'Deterministic hash ordering; 120 excludes source flags, unresolved lineage and evaluator-unusable tasks; 400 keeps the full allocation and omits flagged tasks only from execution.'})
    note=f'''# {variant}-task version

{len(source)} source tasks, {len(active)} runnable: {counts['dev']} development / {counts['val']} validation / {counts['test']} test. Do not mix these splits with the other version.

Use `task_manifest.json`, `splits.json` and the `*_executor.json` files for runs. `source_manifest.json` and `source_splits.json` keep every source task, including excluded ones. `rejected_tasks.csv` lists exclusions with reasons and `not_selected.csv` the eligible tasks that were not sampled. `families.csv` records source families, and `precautionary_group_log.csv` lists possibly related tasks kept in the same split. `pilot_10.json` lists the development pilot tasks and `data_summary.csv` the split counts.

To restore and check the workbooks, run `python3 scripts/prepare_data.py`, then `python3 scripts/prepare_variants.py --materialize` and `python3 scripts/prepare_variants.py --verify`. Input workbooks go to `inputs/` and reference workbooks to `evaluator_only/`; only inputs belong in the agent's workspace.

Source: https://huggingface.co/datasets/KAKA22/SpreadsheetBench (CC BY-SA 4.0). Workbooks are not modified.
'''
    (out/'README.md').write_text(note)
    save('SHA256SUMS.json',{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file() and p.suffix!='.xlsx'})

def verify(base,materialize=False):
    archive=ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz'
    if materialize and digest(archive)!=EXPECTED:raise ValueError('Archive mismatch')
    for variant in ('120','400'):
        out=base/variant;source=json.loads((out/'source_manifest.json').read_text());active=json.loads((out/'task_manifest.json').read_text());counts=validate(source,active,variant)
        for rel,h in json.loads((out/'SHA256SUMS.json').read_text()).items():
            if digest(out/rel)!=h:raise ValueError('Metadata changed: '+rel)
        if materialize:
            with tarfile.open(archive) as tar:
                for t in source:
                    for role in ('initial','golden'):
                        p=out/t[role+'_local_path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(tar.extractfile(t[role+'_archive_path']).read())
        for t in source:
            for role in ('initial','golden'):
                if digest(out/t[role+'_local_path'])!=t[role+'_audit']['sha256']:raise ValueError('Workbook mismatch')
        actual=json.loads((out/'splits.json').read_text())['splits']
        if actual!={s:[t['id'] for t in active if t['split']==s] for s in counts}:raise ValueError('Split mismatch')
        pilot=json.loads((out/'pilot_10.json').read_text())
        if len(set(pilot))!=10 or not set(pilot)<=set(actual['dev']):raise ValueError('Pilot leakage')
        for s in counts:
            exe=json.loads((out/(s+'_executor.json')).read_text())
            if [t['id'] for t in exe]!=actual[s]:raise ValueError('Executor mismatch')
        print(variant,': verified',len(active),'eligible;',counts)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,default=ROOT/'datasets');p.add_argument('--verify',action='store_true');p.add_argument('--materialize',action='store_true');a=p.parse_args()
    if not(a.verify or a.materialize):
        for v in ('120','400'):build(v,a.output_root)
    verify(a.output_root,a.materialize)
