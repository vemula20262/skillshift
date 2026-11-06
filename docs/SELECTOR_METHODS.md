# Feedback selector interface

`Selector.select(records)` returns a `Selection` containing method, input_count, items and metadata. Each `Selected` item carries the record, weight, group ID, member occurrence IDs and source families. Callers receive copies; original inputs are preserved.

Required fields are nonempty task_id, source_family, summary, feedback_source and env_version; outcome is success/failure, token_count is a nonnegative integer and failures require error_category. Additional schema fields are preserved. This is the selector-facing contract, not the full attempt schema.

Original record_id identifies an attempt; copied pool records require pool_record_id, matching original_record_id and boolean is_copy. occurrence_id identifies each pool occurrence. Mixed original/pooled batches and conflicting copies are rejected.

The selector contract is independent of dataset size. Before selecting experiment feedback, call `validate_dev(records, manifest)` from skillshift.io. Full runnable manifests check development membership, family identity, nonempty dev/val/test partitions and family/block isolation. Explicit split dictionaries support dev/val/test or validation as an alias, but cannot prove family/block isolation alone. The direct selector API does not choose or filter splits.

Run checks with `python3 -m unittest discover -s tests -v`.

## Baselines

- Unfiltered keeps every occurrence with weight 1.
- Exact dedup hashes literal summary, outcome/category/source/environment and tool events; keeps one representative, preferring originals, and records all contributing families and occurrence IDs.
- Semantic dedup uses cosine similarity and deterministic greedy complete-link grouping within outcome/category/source/environment partitions. Every pair must meet the threshold. The medoid maximizes total within-group similarity; ties prefer originals, then occurrence ID. Identical vectors have cosine 1, including at threshold 1.

Use `get_selector(method, threshold)` from skillshift.selectors. Semantic methods require an explicit finite threshold in [-1, 1], finite nonzero equal-dimensional embeddings and consistent model metadata when provided. No experimental threshold has been calibrated.

Clustering sorts by partition, summary and occurrence ID, joining the first compatible group. Changing wording can change grouping; this is not an exact reproduction of SemDeDup. Pairwise comparisons suit small pools; larger workloads require performance assessment. Exact-hash fields must match the actual reflection payload.

`skillshift.embeddings.encode(records, model_name, revision, cache_folder)` optionally loads Sentence Transformers with trust_remote_code=False and embeds summaries. Pin the model revision and package version before a real run. Embed originals before pooling; pooled rows are rejected. Core tests use handcrafted vectors/fake encoders and require no extra dependencies. Real model inference remains unverified.

## Weighted methods

Source balancing retains all occurrences and assigns 1 / family count. Each family has total weight one, counting successes and failures together. Source-behavior weighting retains all occurrences and assigns 1 / count of that family within the semantic behavior group. Each family-behavior pair has total weight one; group provenance records all families sharing the behavior. Successful and failed outcomes stay in separate semantic partitions.

Weights are outputs, not a guarantee that reflection consumes them. The pipeline must define the weighting policy and actual serialized token budget. These methods do not reduce retained record count. Integration and downstream benefit remain unverified.

## Dataset compatibility

The selectors do not hardcode dataset sizes or split ratios. Use the matching runnable task manifest: datasets/120 has 60/30/30 development/validation/test tasks; datasets/400 has 198/100/100 runnable tasks (two of 400 source tasks are excluded). Custom nonempty partition sizes work with the same manifest schema; arbitrary split labels or cross-validation fold formats are not automatically supported. Partial executor lists cannot establish family/block isolation and are rejected by validate_dev.

The 120-task dataset currently has singleton families, making source balancing per-task balancing. Weights are computed from input records, not dataset inventory counts. Pool feasibility still depends on exact integer copy/outcome ratios in the shared pool builder. Tests cover both complete development partitions, injected repeats and custom sizes with multiple tasks per family using synthetic feedback. Calibration and real C1/C3 comparisons are separate work.
