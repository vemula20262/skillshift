# Feedback selector interface

`Selector.select(records)` returns a `Selection` containing method, input_count, items and metadata. Each `Selected` item carries the record, weight, group ID, member occurrence IDs and source families. Callers receive copies; original inputs are preserved.

Required fields are nonempty task_id, source_family, summary, feedback_source and env_version; outcome is success/failure, token_count is a nonnegative integer and failures require error_category. Additional schema fields are preserved. This is the selector-facing contract, not the full attempt schema.

Original record_id identifies an attempt; copied pool records require pool_record_id, matching original_record_id and boolean is_copy. occurrence_id identifies each pool occurrence. Mixed original/pooled batches and conflicting copies are rejected.

The selector contract is independent of dataset size. Before selecting experiment feedback, call `validate_dev(records, manifest)` from skillshift.io. Full runnable manifests check development membership, family identity, nonempty dev/val/test partitions and family/block isolation. Explicit split dictionaries support dev/val/test or validation as an alias, but cannot prove family/block isolation alone. The direct selector API does not choose or filter splits.

Run checks with `python3 -m unittest discover -s tests -v`.
