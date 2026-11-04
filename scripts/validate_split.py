#!/usr/bin/env python3
"""Validate observed-family isolation; this does not establish unseen-family isolation."""
import argparse, collections, json
from pathlib import Path

def validate(rows):
    errors=[]
    counts=collections.Counter(r['split'] for r in rows)
    if counts != {'dev':60,'val':30,'test':30}: errors.append(f'wrong split counts: {dict(counts)}')
    if len({r['id'] for r in rows}) != len(rows): errors.append('duplicate task IDs')
    for key in ('family_id','sha256','cell_content_sha256'):
        seen={}
        for row in rows:
            value=row[key] if key=='family_id' else row['initial_audit'][key]
            if value in seen and seen[value]!=row['split']: errors.append(f'cross-split leakage: {key} {value}')
            seen[value]=row['split']
    return errors

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest',nargs='?',type=Path,default=Path(__file__).resolve().parents[1]/'data/prepared/candidate_manifest.json');a=p.parse_args()
    errors=validate(json.loads(a.manifest.read_text()))
    if errors: raise SystemExit('\n'.join(errors))
    print('PASS: 120 unique candidates, 60/30/30 counts, no observed family or initial workbook hash crosses splits. Unseen families remain unverified.')
