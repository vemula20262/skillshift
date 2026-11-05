"""Reviewed lineage precautions and deterministic full-source allocation."""
import collections
from prepare_data import choose_groups

UNCERTAIN={
 ('23-24','118-50'):'Large shared dictionary vocabulary; workbook lineage cannot be established.',
 ('80-42','192-22'):'106 uncommon shared business descriptions; possible reused business source.',
 ('146-49','147-48'):'Small word-list content is contained in larger dictionary; possible derived example.',
 ('290-1','146-49'):'Shared unusual anagram strings; possible derived word-list source.',
 ('379-36','496-15'):'Related ledger headers and high layout overlap; changed-value variant cannot be excluded.',
 ('141-20','388-47'):'Matching date/period reconciliation headers; source lineage unresolved.',
 ('11276','11842'):'Related attendance labels and workbook purpose; template lineage unresolved.'}

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
