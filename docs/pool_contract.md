# Pool builder

`scripts/build_pools.py` builds feedback pools from original development attempts. It currently supports exact-copy pools; real reruns (C2) and one failure type across tasks (C3) are not built yet.

## Input

Attempt records as JSONL, following `skillshift/schema.py`. Each needs `record_id`, `task_id`, `source_family`, `split: "dev"` and `outcome` (`success` or `failure`); other fields are kept as they are. Pass only original attempts, never rows from an earlier pool.

Bind the build to the task manifest with `--task-manifest datasets/120/task_manifest.json`. Records from non-development tasks, or whose family disagrees with the manifest, are rejected.

## Config

```json
{
  "status": "approved",
  "dominant_task_ids": ["<dev task id>"],
  "pools": [{"name": "C1_50", "mechanism": "exact_copy", "repeat_fraction": 0.5}]
}
```

`repeat_fraction` can be 0, 0.25, 0.5 or 0.75. Copies come only from the dominant tasks. Pool names use letters, numbers, underscores or hyphens.

## What a pool contains

Each pool keeps all N original attempts and adds K = N·r / (1 − r) copies, so r is copies over total records. Copies keep the success/failure ratio of the originals; if the required counts are not whole numbers the build fails instead of rounding. Within each outcome, copies are taken round-robin in record ID order.

Every occurrence keeps the original fields and adds `pool_record_id` (unique per occurrence), `original_record_id` and `is_copy`. Loaders must keep copies as separate rows.

The output directory must not exist yet. It gets one JSONL file per pool, `pool_stats.csv` (totals, copies, outcome counts, family counts, largest family share and HHI) and `manifest.json` with the config and SHA-256 hashes of the inputs.

## Run

```sh
python3 scripts/build_pools.py --input attempts/records.jsonl --config pools.json \
  --task-manifest datasets/120/task_manifest.json --output-dir pools/pilot
```
