# Exact-copy pool contract — implementation ready, experiment unresolved

This builder implements only explicitly named **exact-copy** interventions. The tracker labels C1/C2/C3 have not been defined; this document does not assign meanings to them. No actual attempts have been provided and no final experimental pools have been generated. Unit-test fixtures are synthetic and must never appear in experiment results.

## Inputs and decisions needed

Provide original attempt records as JSONL. Each record needs nonempty string `record_id`, `task_id`, `source_family`, `split: "dev"`, and `outcome: "success"` or `"failure"`. Additional attempt fields are preserved exactly. One task must have one consistent source family across all its attempts. IDs must already be globally unique across the supplied original attempts. An input record is an original attempt, not necessarily a unique task. Never supply previously copied pool records.

Provide the frozen task-level split (60/30/30 for the 120 version; 198/100/100 eligible tasks for the 400-source version) through `split_tasks.dev`, `.val`, and `.test`, each a disjoint list of task IDs. The builder rejects every non-dev record, including records mislabeled dev whose task is not assigned to dev. Upstream acquisition and evaluator correctness remain separate responsibilities; this tool cannot verify whether outcome labels or provenance claims are true.

The team must define pool names, specify the exact-copy mechanism, identify dominant task IDs from dev, and approve the design. Whether source-family concentration must meet a threshold, how dominant tasks are chosen, and the meanings of C1/C2/C3 remain open design decisions. Statistics report concentration without claiming an unspecified threshold has been satisfied.

Example **unresolved configuration**, intentionally rejected until those decisions are made:

```json
{
  "status": "unresolved",
  "split_tasks": {"dev": [], "val": [], "test": []},
  "dominant_task_ids": [],
  "pools": []
}
```

An approved definition has `status: "approved"` and explicit pool entries such as `{"name":"team_chosen_name","mechanism":"exact_copy","repeat_fraction":0.25}`. This is a schema example, not an approved experimental choice. Supported fractions are 0, 0.25, 0.5, and 0.75. Names use letters, numbers, hyphens, or underscores.

## Exact invariants

Every pool retains all N original attempts. For repeat fraction r, the number of added copies is `K = N*r/(1-r)`, so `r = copies / total records`. Total pool sizes therefore grow across conditions; they are not budget matched. If N contains S successful attempts, added successful copies must equal `K*S/N`. Both counts must be integers; otherwise the build fails rather than rounding, dropping originals, or changing the outcome ratio. A balanced baseline of six originals therefore yields totals 6, 8, 12, and 24 at the four fractions, with copies 0, 2, 6, and 18.

Copies come only from explicitly selected dominant task IDs. Required successes and failures must both be available among those tasks whenever their required copy count is nonzero. Within each outcome, records are sorted by original record ID and selected round-robin. This deterministic selection is an implementation choice to be accepted or changed before experimental use.

The original `record_id`, task ID, source family, outcome, and all attempt content remain unchanged on copies. `original_record_id` points to that unchanged identity. New `pool_record_id` values distinguish every occurrence; `is_copy` distinguishes originals from additions. Downstream loaders must retain copies as separate occurrences rather than deduplicating by `record_id`.

The manifest reports total records, unique original attempts, copies, exact repeat and success fractions, success:failure counts, source-family counts, maximum source-family share, and source-family HHI (sum of squared shares). HHI and maximum share count all occurrences, including copies. An all-success or all-failure baseline remains supported; its count ratio includes a zero denominator or numerator and is not divided numerically.

## Run

From the `skillshift` directory:

```sh
python3 scripts/build_pools.py --input path/to/dev_attempts.jsonl --config path/to/approved_pools.json --task-manifest datasets/400/task_manifest.json --output-dir path/to/new_pool_directory
python3 -m unittest discover -s tests -p 'test_pools.py' -v
```

All pools are validated and constructed in memory before any output is created. The output directory must be new, preventing accidental replacement of previous pools. It contains one JSONL file per named pool, `pool_stats.csv`, and a manifest recording the effective configuration, statistics, and SHA-256 provenance of the input attempts, configuration file, and supplied task manifest. Approval status is a deliberate configuration gate, not an authentication or review system.

The `--task-manifest` adapter accepts the data preparation output: an array with `id`, `split` (dev/val/test), and `family_id`. It derives split membership and expected source families, rejects inconsistent explicit configuration, and checks each attempt against those assignments. With this adapter, omit `split_tasks` and `task_families` from the configuration or provide exactly matching maps. `train` split labels are rejected to avoid confusing a validation set with the development set. The current separate-version manifest is fixed locally; loading it does not imply team signoff. Without the adapter, explicit split configuration remains supported for isolated fixtures; production use should bind the manifest.
