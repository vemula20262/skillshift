#!/usr/bin/env python3
"""Create a versioned 400-task handoff, preserving uncertain pairs in split blocks."""
import argparse, collections, csv, hashlib, json, tarfile, zipfile
from pathlib import Path
from prepare_data import choose_groups
from finalize_dataset import UNCERTAIN
ROOT=Path(__file__).resolve().parents[1]
EXPECTED='10ef893dd29cb13ab97143ea787e68cdc9574a13873ab9a54e50b31dc03fc949'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def allocate(tasks):
    ids={t['id'] for t in tasks}
    if len(tasks)!=400 or len(ids)!=400: raise ValueError('Expected 400 unique tasks')
    parent={i:i for i in ids}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    def join(a,b):
        a,b=find(a),find(b);parent[max(a,b)]=min(a,b)
    for a,b in UNCERTAIN:
        if a not in ids or b not in ids: raise ValueError('Unknown reviewed task')
        join(a,b)
    for field in ('sha256','cell_content_sha256'):
        seen={}
        for t in tasks:
            value=t['initial_audit'][field]
            if value in seen: join(t['id'],seen[value])
            seen[value]=t['id']
    groups=collections.defaultdict(list)
    for t in tasks: groups[find(t['id'])].append(t)
    remaining=dict(groups);output=[]
    for split,n in [('dev',200),('val',100),('test',100)]:
        for group in choose_groups(remaining,n,'full400-v1-'+split):
            members=remaining.pop(group)
            for t in members:
                output.append(dict(t,split=split,split_group_id='block-'+group,split_group_basis='precautionary unresolved lineage' if len(members)>1 else 'singleton',status='full400_v1'))
    if remaining: raise ValueError('Unassigned tasks')
    return output

def verify(out):
    rows=json.loads((out/'task_manifest.json').read_text())
    if collections.Counter(r['split'] for r in rows)!={'dev':200,'val':100,'test':100}: raise ValueError('Wrong split sizes')
    if len({r['id'] for r in rows})!=400: raise ValueError('Duplicate/missing IDs')
    seen={}
    for r in rows:
        for key,value in [('family',r['family_id']),('block',r['split_group_id']),('raw',r['initial_audit']['sha256']),('cells',r['initial_audit']['cell_content_sha256'])]:
            if seen.setdefault((key,value),r['split'])!=r['split']: raise ValueError('Cross-split leakage')
        for role in ('initial','golden'):
            if sha(out/r[role+'_local_path'])!=r[role+'_audit']['sha256']: raise ValueError('Workbook hash mismatch')
    byid={r['id']:r for r in rows}
    for a,b in UNCERTAIN:
        if byid[a]['split']!=byid[b]['split']: raise ValueError('Uncertain pair crosses splits')
    splits=json.loads((out/'splits.json').read_text())['splits']
    if any(set(v)!={r['id'] for r in rows if r['split']==k} for k,v in splits.items()):raise ValueError('Split file mismatch')
    pilot=json.loads((out/'pilot_10.json').read_text())
    if len(pilot)!=10 or len(set(pilot))!=10 or not set(pilot)<=set(splits['dev']):raise ValueError('Invalid pilot')
    for rel,digest in json.loads((out/'SHA256SUMS.json').read_text()).items():
        if sha(out/rel)!=digest:raise ValueError('Manifest checksum mismatch: '+rel)
    return {'tasks':400,'workbooks_verified':800,'splits':{k:len(v) for k,v in splits.items()},'uncertain_pairs_kept_together':len(UNCERTAIN),'pilot_tasks':10}

def build(out):
    if out.exists():raise ValueError('Output exists; preserve version or use a fresh --output directory')
    archive=ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz'
    if sha(archive)!=EXPECTED:raise ValueError('Source archive checksum changed')
    rows=allocate(json.loads((ROOT/'data/prepared/audit.json').read_text()))
    out.mkdir(parents=True)
    def save(name,data): (out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    def table(name,fields,data):
        with (out/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(data)
    with tarfile.open(archive) as tar:
        for t in rows:
            for role in ('initial','golden'):
                rel=Path('inputs' if role=='initial' else 'evaluator_only')/t['id']/(role+'.xlsx')
                payload=tar.extractfile(t[role+'_archive_path']).read()
                if hashlib.sha256(payload).hexdigest()!=t[role+'_audit']['sha256']:raise ValueError('Audit/source mismatch')
                (out/rel).parent.mkdir(parents=True,exist_ok=True);(out/rel).write_bytes(payload);t[role+'_local_path']=str(rel)
    save('task_manifest.json',rows)
    splits={s:[t['id'] for t in rows if t['split']==s] for s in ('dev','val','test')}
    save('splits.json',{'version':'full400_v1','splits':splits})
    save('pilot_10.json',sorted(splits['dev'],key=lambda x:hashlib.sha256(('pilot-full400-v1-'+x).encode()).hexdigest())[:10])
    for s in splits:
        # Executor manifests deliberately omit golden paths and golden audit fields.
        save(s+'_executor.json',[{k:t[k] for k in ('id','instruction','instruction_type','initial_local_path','split','family_id','split_group_id')} for t in rows if t['split']==s])
    table('tasks_400.csv',['id','split','family_id','split_group_id','split_group_basis','instruction_type','initial_local_path','golden_local_path'],rows)
    table('families.csv',['id','family_id','split_group_id','split_group_basis','split'],rows)
    table('precautionary_group_log.csv',['task_a','task_b','reason'],[dict(task_a=a,task_b=b,reason=r) for (a,b),r in UNCERTAIN.items()])
    table('rejected_tasks.csv',['id','reason'],[])
    summary={'version':'full400_v1','source_url':'https://huggingface.co/datasets/KAKA22/SpreadsheetBench','archive_sha256':EXPECTED,'tasks':400,'excluded':0,'splits':{s:len(v) for s,v in splits.items()},'types_by_split':{s:dict(collections.Counter(t['instruction_type'] for t in rows if t['split']==s)) for s in splits},'observed_source_families':len({t['family_id'] for t in rows}),'precautionary_split_blocks':len({t['split_group_id'] for t in rows}),'uncertain_pairs':len(UNCERTAIN),'selection_seed':'skillshift-candidate-v1; salt full400-v1-{split}','method':'Retain all 400; transitive precautionary blocks for seven unresolved pairs plus exact raw/cell matches; deterministic whole-block allocation 200/100/100. No outcome-driven selection.','limits':['Precautionary blocks do not prove common source lineage. family_id remains observed identity; split_group_id prevents potential related tasks crossing splits.','Heuristic screening can miss transformed variants.','Reference answer correctness, evaluator execution and model performance have not been certified.','For conservative bootstrap inference resample split_group_id blocks, subject to team protocol agreement.','This replaces the original 120-task plan; no team signoff is implied.']}
    save('provenance.json',summary)
    save('SHA256SUMS.json',{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()})
    result=verify(out);print(json.dumps(result,indent=2))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'data/full400_v1');p.add_argument('--verify',action='store_true');a=p.parse_args()
    if a.verify:print(json.dumps(verify(a.output),indent=2))
    else:build(a.output)
