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
    save('protocol.json',{'version':variant+'-v2','source_tasks':len(source),'eligible_tasks':len(active),'eligible_split_counts':counts,'archive_sha256':EXPECTED,'family_policy':'Observed family_id is not confirmed provenance. split_group_id enforces precautionary isolation; use blocks for conservative resampling.','team_status':'Prepared for review, not claimed team-approved','model_runs':0,'pool_status':'Await real evaluated attempts and C1/C2/C3 definitions','sampling':'Deterministic hash ordering; 120 excludes source flags, unresolved lineage and evaluator-unusable tasks; 400 preserves historical full400_v1 allocation and omits flagged tasks only from execution.'})
    save('pools.unresolved.json',{'status':'unresolved','dominant_task_ids':[],'pools':[]})
    note=f'''# {variant}-task version

This folder is self-contained dataset metadata for version {variant}-v2. It is an alternative to the other version, not another independent experiment to combine with it.

Source collection: **{len(source)} tasks**. Eligible for execution/scoring: **{len(active)} tasks**, with **{counts['dev']} development / {counts['val']} validation / {counts['test']} test**.

Use `task_manifest.json`, `splits.json`, and the three executor manifests for runs. `source_manifest.json` and `source_splits.json` retain source accounting. The 400 version retains two upstream-flagged tasks in source records but excludes them from every runnable manifest. The 120 version selects replacements before splitting so its eligible counts remain exactly 60/30/30.

`families.csv` records observed identities. No confirmed workbook merges were found, so `merge_log.csv` has headers only. Potential relationships, where retained, are explicitly precautionary blocks in `precautionary_group_log.csv`, not confirmed family merges. Heuristic review cannot prove independence.

`rejected_tasks.csv` separates upstream warnings from project precautions; `not_selected.csv` accounts for eligible unsampled tasks. `data_summary.csv` provides report counts. `pilot_10.json` contains development-only IDs.

## Reproduce and verify

From the repository root, run `python3 scripts/prepare_data.py` if the source archive is absent, then `python3 scripts/prepare_variants.py --materialize` to restore workbook files for the published manifests. Run `python3 scripts/prepare_variants.py --verify`. To regenerate metadata separately use `--output-root` with a new directory.

Input workbooks go in `inputs/`; references in `evaluator_only/`. Only inputs and executor manifests belong in the agent workspace. Do not expose reference answers to the agent. Raw workbook bytes are unchanged; checksums cover all files.

For pool creation, pass `--task-manifest datasets/{variant}/task_manifest.json` to `scripts/build_pools.py`. Use `pools.unresolved.json` only after definitions are agreed; it intentionally cannot produce experimental pools yet. Two attempts per eligible development task means {counts['dev']*2} original attempts. Additional reruns are a separate decision.

## Completion status

Task selection, file checks, source-warning handling, split checks, pilot IDs, and a dataset-section draft are prepared. Semantic reference correctness and the evaluator integration still require validation. Real pilot/final pools and their statistics cannot be completed without actual attempts. No test results or team approval are claimed.

Source: https://huggingface.co/datasets/KAKA22/SpreadsheetBench (CC BY-SA 4.0). Preserve source attribution. The older `data/` versions are historical and may include the source-flagged tasks in runnable lists; do not run them.
'''
    (out/'README.md').write_text(note)
    extra=' The 120 version also excludes 130-9 and 283-32, whose answer positions the evaluator cannot parse, and 73-45, whose initial file already passes verification.' if variant=='120' else ''
    (out/'dataset_section.md').write_text(f'''# Dataset section draft — {variant}-task version

We use SpreadsheetBench Verified, preserving its original instructions and input/reference workbook pairs. This version contains {len(source)} source tasks and {len(active)} eligible tasks allocated to development ({counts['dev']}), validation ({counts['val']}), and test ({counts['test']}). Source metadata warnings exclude tasks 56225 (initial file already passes verification) and 56274 (reference data-validation inconsistency) from execution.{extra} All raw source records remain available in the original archive.

Selection and split assignment are deterministic and do not use model outcomes. Observed workbook identity and precautionary split blocks are distinguished. The smaller version excludes unresolved-lineage candidates before selecting 120 tasks; the larger version retains them in whole precautionary blocks. Neither procedure proves all task sources independent. File readability and hashes are checked, but reference semantics and evaluator behavior are not certified by these checks.

The accompanying data_summary.csv supplies measured split/category counts. We plan two attempts per eligible development task ({counts['dev']*2} original attempts). No such attempts have been collected in this package; feedback pool definitions, success/failure ratios, and concentration statistics remain pending. This draft must be updated after actual collection.
''')
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
