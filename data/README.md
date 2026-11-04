# SpreadsheetBench candidate data

Run `python3 scripts/prepare_data.py` from the project root to download and audit the actual verified-400 archive and recreate the candidate selection. This uses Python standard libraries only. Then run `python3 scripts/validate_split.py`.

`prepared/candidate_manifest.json` contains 120 provisional tasks (60 development, 30 validation, 30 test), with archive paths, raw instructions and answer metadata, workbook hashes, and local workbook paths relative to `prepared/`. Initial workbooks are under `prepared/inputs/`. Gold workbooks are under `prepared/evaluator_only/`; do not expose these to the model or retrieval corpus. The original archive also contains golds and is evaluator/admin material.

All 400 tasks parsed successfully; 280 eligible tasks were not sampled. `rejected.json` therefore contains no entries, while `not_selected.json` accounts for unsampled tasks. Full audit and source checksum are in `audit.json` and `provenance.json`.

The candidate includes 78 cell-level and 42 sheet-level tasks; the source has 275 cell-level and 125 sheet-level tasks. Sampling is deterministic with seed `skillshift-candidate-v1`, and selection never reads golden answer values. Byte-identical or normalized-cell-identical initial workbooks are grouped transitively, without grouping by operation category. No such duplicates were found in this archive. Each observed family is therefore a singleton. **This does not prove all tasks are independent:** variants with changed values or shared source provenance require human review before freezing the split. The normalized hash omits styles and sheet names; equal cell content is conservatively grouped. Task complexity and benchmark answer correctness are not validated by the audit.

No split has been approved by teammates. No model benchmark has run, and these artifacts contain no experimental performance results.
