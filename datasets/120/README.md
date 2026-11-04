# 120-task version

This folder is self-contained dataset metadata for version 120-v2. It is an alternative to the other version, not another independent experiment to combine with it.

Source collection: **120 tasks**. Eligible for execution/scoring: **120 tasks**, with **60 development / 30 validation / 30 test**.

Use `task_manifest.json`, `splits.json`, and the three executor manifests for runs. `source_manifest.json` and `source_splits.json` retain source accounting. The 400 version retains two upstream-flagged tasks in source records but excludes them from every runnable manifest. The 120 version selects replacements before splitting so its eligible counts remain exactly 60/30/30.

`families.csv` records observed identities. No confirmed workbook merges were found, so `merge_log.csv` has headers only. Potential relationships, where retained, are explicitly precautionary blocks in `precautionary_group_log.csv`, not confirmed family merges. Heuristic review cannot prove independence.

`rejected_tasks.csv` separates upstream warnings from project precautions; `not_selected.csv` accounts for eligible unsampled tasks. `data_summary.csv` provides report counts. `pilot_10.json` contains development-only IDs.

## Reproduce and verify

From the repository root, run `python3 scripts/prepare_data.py` if the source archive is absent, then `python3 scripts/prepare_variants.py --materialize` to restore workbook files for the published manifests. Run `python3 scripts/prepare_variants.py --verify`. To regenerate metadata separately use `--output-root` with a new directory.

Input workbooks go in `inputs/`; references in `evaluator_only/`. Only inputs and executor manifests belong in the agent workspace. Do not expose reference answers to the agent. Raw workbook bytes are unchanged; checksums cover all files.

For pool creation, pass `--task-manifest datasets/120/task_manifest.json` to `scripts/build_pools.py`. Use `pools.unresolved.json` only after definitions are agreed; it intentionally cannot produce experimental pools yet. Two attempts per eligible development task means 120 original attempts. Additional reruns are a separate decision.

## Completion status

Task selection, file checks, source-warning handling, split checks, pilot IDs, and a dataset-section draft are prepared. Semantic reference correctness and the evaluator integration still require validation. Real pilot/final pools and their statistics cannot be completed without actual attempts. No test results or team approval are claimed.

Source: https://huggingface.co/datasets/KAKA22/SpreadsheetBench (CC BY-SA 4.0). Preserve source attribution. The older `data/` versions are historical and may include the source-flagged tasks in runnable lists; do not run them.
