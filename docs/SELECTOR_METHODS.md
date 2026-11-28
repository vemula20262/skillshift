# Feedback selector interface

`Selector.select(records)` returns a `Selection` containing method, input_count, items and metadata. Each `Selected` item carries the record, weight, group ID, member occurrence IDs and source families. Callers receive copies; original inputs are preserved.

Required fields are nonempty task_id, source_family, summary, feedback_source and env_version; outcome is success/failure, token_count is a nonnegative integer and failures require error_category. Additional schema fields are preserved.

Original record_id identifies an attempt; copied pool records require pool_record_id, matching original_record_id and boolean is_copy. occurrence_id identifies each pool occurrence. Mixed original/pooled batches and conflicting copies are rejected.

The selector contract is independent of dataset size. Before selecting experiment feedback, call `validate_dev(records, manifest)` from skillshift.io. Full runnable manifests check development membership, family identity, nonempty dev/val/test partitions and family/block isolation. Explicit split dictionaries support dev/val/test or validation as an alias, but cannot prove family/block isolation alone. The direct selector API does not choose or filter splits.

Run checks with `python3 -m unittest discover -s tests -v`.

## Baselines

- Unfiltered keeps every occurrence with weight 1.
- Exact dedup hashes trajectory_sha256 together with outcome/category/source/environment; rejects missing or malformed trajectory hashes; keeps one representative, preferring originals, and records all contributing families and occurrence IDs.
- Semantic dedup uses cosine similarity and deterministic greedy complete-link grouping within outcome/category/source/environment partitions. Every pair must meet the threshold. The medoid maximizes total within-group similarity; ties prefer originals, then occurrence ID. Identical vectors have cosine 1, including at threshold 1.

Use `get_selector(method, threshold)` from skillshift.selectors. Semantic methods require an explicit finite threshold in [-1, 1], finite nonzero equal-dimensional embeddings and consistent model metadata when provided.

Clustering sorts by partition, summary and occurrence ID, joining the first compatible group. Changing wording can change grouping; this is not an exact reproduction of SemDeDup.

`skillshift.embeddings.encode(records, model_name, revision, cache_folder)` optionally loads Sentence Transformers with trust_remote_code=False and embeds summaries. Pin the model revision and package version before a real run. Embed originals before pooling; pooled rows are rejected.

## Weighted methods

Source balancing retains all occurrences and assigns 1 / family count. Each family has total weight one, counting successes and failures together. Source-behavior weighting retains all occurrences and assigns 1 / count of that family within the semantic behavior group. Each family-behavior pair has total weight one; group provenance records all families sharing the behavior. Successful and failed outcomes stay in separate semantic partitions.

These methods keep every occurrence; the update pipeline samples records by weight into its fixed feedback token budget.

## Dataset compatibility

The selectors do not hardcode dataset sizes or split ratios. Use the matching runnable task manifest: datasets/120 has 60/30/30 development/validation/test tasks; datasets/400 has 198/100/100 runnable tasks (two of 400 source tasks are excluded). Custom nonempty partition sizes work with the same manifest schema; arbitrary split labels or cross-validation fold formats are not automatically supported. Partial executor lists cannot establish family/block isolation and are rejected by validate_dev.

The 120-task dataset currently has singleton families, making source balancing per-task balancing. Weights are computed from input records, not dataset inventory counts. Pool feasibility still depends on exact integer copy/outcome ratios in the shared pool builder. Tests cover both complete development partitions, injected repeats and custom sizes with multiple tasks per family using synthetic feedback. Calibration and real C1/C3 comparisons are separate work.


## Development calibration commands

The selector tools are available through `python -m skillshift --help`.
Embed original development records before constructing pools, using `embed`
with `--model`, `--revision` (an immutable model commit), and `--cache`.
Sentence Transformers must be installed separately for real inference.
The local model choice is pinned below; no experimental threshold is selected.

Tune using reviewed JSONL pairs with `left_id`, `right_id` and boolean
`equivalent` fields. IDs refer to original record IDs; include both positive
and negative examples. Use the full canonical manifest for family/block checks:

```sh
python -m skillshift tune --input attempts/embedded.jsonl \
  --pairs attempts/reviewed_pairs.jsonl \
  --task-manifest datasets/120/task_manifest.json \
  --candidates 0.8 0.85 0.9 0.95 1.0 --output calibration.json
```

Candidate values above are an example grid, not calibrated results. Calibration
rejects pooled records, non-development tasks, and mixed synthetic/real inputs.
Absent synthetic markers mean real records; explicit markers must be boolean. It records input, pair and
manifest checksums, embedding model identity, and in-sample pair metrics.
A zero-F1 grid produces no usable threshold. `select` and `compare` accept
`--calibration calibration.json` and check model and manifest identity.
`compare` exports all five methods' kept records, weights and provenance.
All commands refuse to overwrite existing output files. Synthetic fixtures
validate the tooling only; tasks 17 and 18 require real reviewed inputs/results.

The local embedding choice is pinned in `config/selectors/embedding.json`:
`sentence-transformers/all-MiniLM-L6-v2` at revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. It encodes short summaries locally;
inputs exceeding 256 word pieces are truncated by the model. Inspect summary
lengths before calibration. This model choice is not evidence that its thresholds
are calibrated or that the team has reviewed the choice.
