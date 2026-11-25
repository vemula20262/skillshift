#!/usr/bin/env python3
"""Build explicit, development-only exact-copy pools. No attempt generation."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path


class PoolError(ValueError):
    pass


def validate(records, config):
    if config.get('status') != 'approved':
        raise PoolError('Pool definitions are unresolved; set approved only after team specification.')
    splits = config.get('split_tasks', {})
    if set(splits) != {'dev', 'val', 'test'}:
        raise PoolError('Provide explicit dev, val, and test task ID lists.')
    seen = set()
    for name, ids in splits.items():
        if not isinstance(ids, list) or any(not isinstance(x, str) or not x for x in ids):
            raise PoolError('Split task IDs must be nonempty strings in lists.')
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise PoolError('Task splits must be disjoint, without duplicates.')
        seen.update(ids)
    dominant = config.get('dominant_task_ids')
    if not isinstance(dominant, list) or not dominant or not set(dominant) <= set(splits['dev']):
        raise PoolError('Explicit dominant_task_ids must be a nonempty subset of dev tasks.')
    if not records:
        raise PoolError('No input attempts; real pools cannot be built.')
    record_ids = set()
    task_families = {}
    for row in records:
        if any(not isinstance(row.get(k), str) or not row[k] for k in ('task_id', 'source_family', 'record_id')):
            raise PoolError('Each attempt requires nonempty task_id, source_family, record_id strings.')
        if row.get('split') != 'dev' or row['task_id'] not in splits['dev']:
            raise PoolError('Only explicitly assigned dev attempts are permitted; no val/test records.')
        prior_family = task_families.setdefault(row['task_id'], row['source_family'])
        if prior_family != row['source_family']:
            raise PoolError('A task cannot have inconsistent source_family values.')
        expected_family = config.get('task_families', {}).get(row['task_id'])
        if 'task_families' in config and expected_family != row['source_family']:
            raise PoolError('Attempt source_family does not match the task family manifest.')
        if row.get('outcome') not in ('success', 'failure'):
            raise PoolError('Outcome must be success or failure.')
        if row['record_id'] in record_ids:
            raise PoolError('Duplicate input record_id; originals must be unique.')
        record_ids.add(row['record_id'])
        if any(k in row for k in ('pool_record_id', 'original_record_id', 'is_copy')):
            raise PoolError('Input contains reserved pool metadata; pass original attempts only.')
    pools = config.get('pools')
    if not isinstance(pools, list) or not pools:
        raise PoolError('Provide explicit named pool definitions.')
    names = set()
    for pool in pools:
        if not isinstance(pool, dict):
            raise PoolError('Each pool must be an object.')
        name = pool.get('name')
        if not isinstance(name, str) or not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
            raise PoolError('Pool names must use letters, numbers, underscores or hyphens.')
        if name in names:
            raise PoolError('Pool names must be unique.')
        names.add(name)
        if pool.get('mechanism') != 'exact_copy':
            raise PoolError('Only explicitly specified exact_copy mechanisms are supported.')
        try:
            rate = Fraction(str(pool['repeat_fraction']))
        except (KeyError, ValueError, ZeroDivisionError):
            raise PoolError('Invalid repeat_fraction.') from None
        if rate not in (Fraction(0), Fraction(1, 4), Fraction(1, 2), Fraction(3, 4)):
            raise PoolError('repeat_fraction must be 0, .25, .5 or .75.')


def pool_stats(rows):
    total = len(rows)
    outcomes = Counter(r['outcome'] for r in rows)
    sources = Counter(r['source_family'] for r in rows)
    copies = sum(r['is_copy'] for r in rows)
    return {
        'total': total, 'unique_originals': len({r['original_record_id'] for r in rows}),
        'copies': copies, 'repeat_fraction': str(Fraction(copies, total)),
        'outcomes': dict(outcomes), 'success_fraction': str(Fraction(outcomes['success'], total)),
        'success_to_failure_ratio': f"{outcomes['success']}:{outcomes['failure']}",
        'source_counts': dict(sources), 'source_max_share': max(sources.values()) / total,
        'source_hhi': sum((n / total) ** 2 for n in sources.values()),
    }


def build_pools(records, config):
    validate(records, config)
    originals = sorted(records, key=lambda r: r['record_id'])
    n = len(originals)
    successes = sum(r['outcome'] == 'success' for r in originals)
    result = {}
    for definition in config['pools']:
        name = definition['name']
        rate = Fraction(str(definition['repeat_fraction']))
        copy_count = n * rate / (1 - rate)
        if copy_count.denominator != 1:
            raise PoolError(f'{name}: exact copy fraction infeasible for {n} originals; no rounding allowed.')
        success_copies = copy_count * Fraction(successes, n)
        if success_copies.denominator != 1:
            raise PoolError(f'{name}: exact success/failure ratio infeasible; no rounding allowed.')
        rows = [dict(r, original_record_id=r['record_id'], pool_record_id=f'{name}:original:{i}', is_copy=False)
                for i, r in enumerate(originals)]
        for outcome, count in [('success', int(success_copies)), ('failure', int(copy_count-success_copies))]:
            candidates = [r for r in originals if r['task_id'] in config['dominant_task_ids'] and r['outcome'] == outcome]
            if count and not candidates:
                raise PoolError(f'{name}: dominant tasks lack {outcome} attempts needed to preserve outcome ratio.')
            for i in range(count):
                row = candidates[i % len(candidates)]
                rows.append(dict(row, original_record_id=row['record_id'], pool_record_id=f'{name}:copy:{outcome}:{i}', is_copy=True))
        result[name] = {'records': rows, 'stats': pool_stats(rows)}
    return result


def apply_task_manifest(config, rows):
    """Bind the explicit design to prepare_data's task assignments and families."""
    splits = {'dev': [], 'val': [], 'test': []}
    families = {}
    family_splits = {}
    for row in rows:
        task_id, split, family = row.get('id'), row.get('split'), row.get('family_id')
        if not isinstance(task_id, str) or not task_id or split not in splits or not isinstance(family, str) or not family:
            raise PoolError('Task manifest requires id, dev/val/test split and family_id.')
        if task_id in families:
            raise PoolError('Task manifest contains duplicate task IDs.')
        if family_splits.setdefault(family, split) != split:
            raise PoolError('A source family crosses task splits.')
        families[task_id] = family
        splits[split].append(task_id)
    if config.get('split_tasks') and {k: set(v) for k, v in config['split_tasks'].items()} != {k: set(v) for k, v in splits.items()}:
        raise PoolError('Configured splits disagree with the task manifest.')
    if config.get('task_families') and config['task_families'] != families:
        raise PoolError('Configured families disagree with the task manifest.')
    return dict(config, split_tasks=splits, task_families=families)


def write_outputs(pools, config, input_path, output_dir, provenance_paths=None):
    provenance_paths = dict(provenance_paths or {}, attempts=input_path)
    provenance = {name: {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                  for name, path in provenance_paths.items()}
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, pool in pools.items():
        (output_dir / f'{name}.jsonl').write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in pool['records']))
    stats = {name: pool['stats'] for name, pool in pools.items()}
    (output_dir / 'manifest.json').write_text(json.dumps({'config': config, 'provenance': provenance, 'pools': stats}, indent=2) + '\n')
    with (output_dir / 'pool_stats.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['pool_name'] + list(next(iter(stats.values()))))
        writer.writeheader()
        for name, row in stats.items():
            writer.writerow(dict(pool_name=name, **{key: json.dumps(value, sort_keys=True) if isinstance(value, dict) else value
                                                   for key, value in row.items()}))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Original attempt JSONL, dev only')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--task-manifest', type=Path, help='datasets/<version>/task_manifest.json; checks task splits and families')
    parser.add_argument('--output-dir', required=True, type=Path, help='New directory (must not already exist)')
    args = parser.parse_args()
    try:
        records = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
        config = json.loads(args.config.read_text())
        provenance_paths = {'config': args.config}
        if args.task_manifest:
            config = apply_task_manifest(config, json.loads(args.task_manifest.read_text()))
            provenance_paths['task_manifest'] = args.task_manifest
        pools = build_pools(records, config)
        write_outputs(pools, config, args.input, args.output_dir, provenance_paths)
    except (PoolError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f'Pool build failed: {exc}\n')


if __name__ == '__main__':
    main()
