#!/usr/bin/env python3
"""Download and audit the pinned SpreadsheetBench source archive.
No model calls. Gold workbooks are audited, never used for family/selection features.
"""
import argparse, collections, hashlib, io, json, tarfile, urllib.request, zipfile
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

EXPECTED = '10ef893dd29cb13ab97143ea787e68cdc9574a13873ab9a54e50b31dc03fc949'

def audit_archive(archive):
    if digest(archive.read_bytes()) != EXPECTED:
        raise ValueError("Source archive checksum mismatch")
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
    if rejected:
        raise ValueError(f"Source validation failed: {rejected}")
    if len(tasks) != 400:
        raise ValueError("Expected 400 source tasks")
    make_groups(tasks)
    return tasks

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT/'data/raw/spreadsheetbench_verified_400.tar.gz')
    args = parser.parse_args()
    if not args.archive.exists():
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, args.archive)
    tasks = audit_archive(args.archive)
    print(json.dumps({'source_tasks': len(tasks), 'archive_sha256': digest(args.archive.read_bytes())}))
