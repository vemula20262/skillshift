# SkillShift

Two separate dataset options are prepared for review. Choose one with the team; do not mix their splits or treat the alternatives as independent replications.

- **[120-task version](datasets/120/README.md):** 120 eligible tasks, split 60 development / 30 validation / 30 test. Excludes the two upstream-flagged tasks and unresolved-lineage candidates before sampling.
- **[400-source-task version](datasets/400/README.md):** preserves all 400 original tasks, but only 398 are eligible for execution: 198 development / 100 validation / 100 test. Tasks 56225 and 56274 retain source records but are absent from runnable manifests. Potentially related tasks stay together in precautionary blocks.

Each folder includes its task inventory, observed families, merge/precaution logs, exclusions, source and runnable manifests, runnable splits, executor manifests, pilot IDs, checksums, data summary, dataset-section draft, and unresolved pool configuration. Reference workbooks remain evaluator-only.

## Setup and verification

```sh
python3 scripts/prepare_data.py
python3 scripts/prepare_variants.py --materialize
python3 scripts/prepare_variants.py --verify
python3 -m unittest discover -s tests -v
```

The source command downloads and audits the pinned archive without creating intermediate dataset versions.

Shared implementation is in `scripts/` and tests in `tests/`. Original workbook bytes are downloaded from the source and excluded from Git. To independently regenerate both sets of metadata, run `python3 scripts/prepare_variants.py --output-root /path/to/new/directory`.

## Still pending

These are prepared protocol alternatives, not claims of team signoff. Reference-answer semantics and evaluator integration still require pilot validation. Real feedback pools require evaluator-labelled attempts and definitions of C1/C2/C3. The pool tool is implemented; no real pilot/final pools or results have been invented.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and the review process.

Source: [SpreadsheetBench Verified](https://huggingface.co/datasets/KAKA22/SpreadsheetBench), [official repository](https://github.com/RUCKBReasoning/SpreadsheetBench), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Preserve attribution. Workbooks are not modified; task selection, audit metadata and split policies are project additions.
