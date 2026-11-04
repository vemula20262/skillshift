#!/usr/bin/env python3
"""Rebuild an explicitly provisional 120-task manifest from verified SpreadsheetBench.
No model calls. Gold workbooks are audited, never used for family/selection features.
"""
import argparse, csv, collections, hashlib, io, json, tarfile, urllib.request, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://huggingface.co/datasets/KAKA22/SpreadsheetBench/resolve/main/spreadsheetbench_verified_400.tar.gz'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SEED = 'skillshift-candidate-v1'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def workbook_audit(data):
    """Read literal values/formulas, resolving shared strings; ignore packaging metadata."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        book = ET.fromstring(z.read('xl/workbook.xml'))
        sheet_names = [s.attrib['name'] for s in book.findall('m:sheets/m:sheet', NS)]
        sheets, formulas, missing_cache, cells = [], 0, 0, 0
        for name in sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')):
            rows = []
            for c in ET.fromstring(z.read(name)).findall('.//m:sheetData/m:row/m:c', NS):
                f, v = c.find('m:f', NS), c.find('m:v', NS)
                value = v.text if v is not None else None
                typ = c.attrib.get('t', 'n')
                if typ == 's' and value is not None:
                    value, typ = strings[int(value)], 'string'
                elif typ == 'inlineStr':
                    inline = c.find('m:is', NS)
                    value, typ = (''.join(inline.itertext()) if inline is not None else None), 'string'
                if f is not None:
                    formulas += 1
                    missing_cache += value is None
                if value is not None or f is not None:
                    rows.append([c.attrib['r'], typ, value, f.text if f is not None else None,
                                 sorted(f.attrib.items()) if f is not None else []])
                    cells += 1
            sheets.append(rows)
        # Sheet names intentionally omitted: renaming a workbook is not a new family.
        return {'sha256': digest(data), 'cell_content_sha256': digest(json.dumps(sheets, ensure_ascii=False, separators=(',', ':')).encode()),
                'sheet_names': sheet_names, 'nonempty_cells': cells, 'formula_cells': formulas,
                'formula_cells_without_cached_value': missing_cache}

def make_groups(tasks):
    parent = {t['id']: t['id'] for t in tasks}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    seen = {}
    for t in tasks:
        # Never group on task operation, category, instruction similarity, or numeric ID prefix.
        for kind in ('sha256', 'cell_content_sha256'):
            key = (kind, t['initial_audit'][kind])
            if key in seen:
                a, b = find(t['id']), find(seen[key]); parent[max(a,b)] = min(a,b)
            else:
                seen[key] = t['id']
    groups = collections.defaultdict(list)
    for t in tasks:
        groups[find(t['id'])].append(t)
    for gid, members in groups.items():
        for t in members:
            t['family_id'] = 'observed-' + gid
            t['family_evidence'] = 'shared initial workbook bytes or normalized initial cells' if len(members)>1 else 'singleton; unseen provenance/variants remain unverified'
    return groups

def choose_groups(groups, target, salt):
    ordered = sorted(groups, key=lambda g: digest((SEED+salt+g).encode()))
    reachable = {0: []}
    for gid in ordered:
        size = len(groups[gid])
        for n, selected in list(reachable.items())[::-1]:
            if n+size <= target and n+size not in reachable:
                reachable[n+size] = selected+[gid]
        if target in reachable:
            return reachable[target]
    raise ValueError(f'Cannot fill {target} tasks without breaking families')

def prepare(archive, output):
    tasks, rejected = [], []
    with tarfile.open(archive) as tar:
        members = {m.name:m for m in tar.getmembers() if m.isfile()}
        metadata_path = next(n for n in members if n.endswith('/dataset.json'))
        metadata = json.load(tar.extractfile(metadata_path))
        base = metadata_path.rsplit('/',1)[0]
        ids = collections.Counter(str(t['id']) for t in metadata)
        for record in metadata:
            t = dict(record); t['id'] = str(t['id']); reasons = []
            if ids[t['id']] != 1: reasons.append('duplicate task id')
            for field in ('instruction','answer_position'):
                if not t.get(field): reasons.append('missing '+field)
            prefix = base+'/'+t['spreadsheet_path']+'/'
            files = [n for n in members if n.startswith(prefix) and n.endswith('.xlsx')]
            initial = [n for n in files if n.endswith('_init.xlsx') or n.endswith('/initial.xlsx')]
            golden = [n for n in files if n.endswith('_golden.xlsx') or n.endswith('/golden.xlsx')]
            if len(initial)!=1 or len(golden)!=1: reasons.append('expected exactly one initial and one golden')
            else:
                try:
                    t['initial_audit'] = workbook_audit(tar.extractfile(initial[0]).read())
                    t['golden_audit'] = workbook_audit(tar.extractfile(golden[0]).read())
                    t['initial_archive_path'], t['golden_archive_path'] = initial[0], golden[0]
                except Exception as e: reasons.append('workbook parse error: '+str(e))
            if reasons: rejected.append({'id':t['id'],'reasons':reasons})
            else: tasks.append(t)
    groups = make_groups(tasks)
    remaining = dict(groups); selected = []
    for split, count in [('dev',60),('val',30),('test',30)]:
        for gid in choose_groups(remaining,count,split):
            for task in remaining.pop(gid):
                selected.append(dict(task, split=split, status='candidate_pending_team_approval'))
    output.mkdir(parents=True,exist_ok=True)
    import shutil
    for directory in ('inputs', 'evaluator_only'):
        if (output / directory).exists(): shutil.rmtree(output / directory)
    with tarfile.open(archive) as tar:
        for task in selected:
            for role in ('initial', 'golden'):
                destination = output / ('inputs' if role == 'initial' else 'evaluator_only') / task['id'] / (role+'.xlsx')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(tar.extractfile(task[role+'_archive_path']).read())
                task[role+'_local_path'] = str(destination.relative_to(output))
    def save(name,data): (output/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    save('audit.json', tasks); save('candidate_manifest.json', selected); save('rejected.json',rejected)
    save('splits.json', {'status':'candidate_pending_team_approval', 'splits':{name:[t['id'] for t in selected if t['split']==name] for name in ('dev','val','test')}})
    def csv_save(name, fields, rows):
        with (output/name).open('w', newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    csv_save('tasks_120.csv', ['id','split','family_id','instruction_type','instruction','answer_position','initial_local_path','golden_local_path','status'], selected)
    csv_save('families.csv', ['id','family_id','family_evidence','variant_review_status'], [dict(t,variant_review_status='pending_manual_provenance_review') for t in tasks])
    csv_save('merge_log.csv', ['family_id','member_ids','evidence'], [{'family_id':g[0]['family_id'],'member_ids':'|'.join(t['id'] for t in g),'evidence':'shared raw or normalized initial workbook hash'} for g in groups.values() if len(g)>1])
    csv_save('rejected_tasks.csv', ['id','reasons'], [{'id':t['id'],'reasons':'; '.join(t['reasons'])} for t in rejected])

    save('not_selected.json',[{'id':t['id'],'reason':'eligible, not selected by deterministic family-preserving candidate sampling'} for group in remaining.values() for t in group])
    summary = {'status':'PROVISIONAL; not a team-approved frozen split', 'source_url':URL,'archive_sha256':digest(archive.read_bytes()),
               'seed':SEED,'total_metadata_tasks':len(metadata),'eligible_tasks':len(tasks),'rejected_tasks':len(rejected),
               'observed_families':len(groups),'multi_task_observed_families':sum(len(g)>1 for g in groups.values()),
               'candidate_split_counts':dict(collections.Counter(t['split'] for t in selected)),
               'candidate_type_counts':dict(collections.Counter(t['instruction_type'] for t in selected)),
               'all_type_counts':dict(collections.Counter(t['instruction_type'] for t in tasks)),
               'limitations':['Content hashes identify exact/shared cell-content workbooks only; changed-value variants and common source provenance may remain undetected.',
                 'Style-only differences are conservatively grouped; cell hash ignores formatting and sheet names.',
                 'Candidate sampling is deterministic, not stratified by difficulty, feasibility, or task type.',
                 'Audit verifies XLSX readability and metadata presence, not answer correctness or executable feasibility.',
                 'Answer ranges require parser normalization/manual review before scoring; raw metadata is preserved.',
                 'Golden files must remain evaluator-only; training/retrieval and agent prompts must use initial workbooks only.',
                 'No human family review or team split approval has occurred.']}
    save('provenance.json',summary)
    print(json.dumps(summary,indent=2))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--archive',type=Path,default=ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz');parser.add_argument('--output',type=Path,default=ROOT/'data/prepared');args=parser.parse_args()
    if not args.archive.exists():
        args.archive.parent.mkdir(parents=True,exist_ok=True)
        urllib.request.urlretrieve(URL,args.archive)
    prepare(args.archive,args.output)
