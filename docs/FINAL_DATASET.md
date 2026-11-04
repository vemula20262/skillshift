# Working workbook dataset v1 — completed November 3, 2026

Use `data/final_v1/`, which supersedes the initial `data/prepared/` candidate. The working selection is fixed and checksummed. No team signoff or experiment completion is implied.

## What is ready

- 120 tasks: 60 development, 30 validation, 30 test.
- 82 cell-level and 38 sheet-level tasks.
- 120 input workbooks and 120 reference workbooks, separated by role.
- `tasks_120.csv`, `families.csv`, `splits.json`, detailed `task_manifest.json`, exclusion and nonselection logs, review evidence, and checksums.
- Reproducible preparation, family screening, final selection, and split validation.

## Family review and selection

All 400 original tasks passed structural checks. The input-only screen compared all 79,800 task pairs using rare shared text, cell-content containment, and text containment. These are broad candidate-screening signals, not proof of source identity. Sixty-three pairs were flagged and reviewed using the stored overlap evidence and task context.

Fifty-six pairs showed generic shared labels, names, calendar terms, categories, or other insufficient evidence of a shared workbook. Seven pairs involving 13 distinct tasks remained uncertain: dictionary/anagram data, distinctive business descriptions, ledgers, reconciliation headers, and attendance templates. Both endpoints of each uncertain pair were excluded, rather than inventing source-family merges. Exact reasons and pair evidence are preserved in `family_review_decisions.json` and `excluded_tasks.csv`.

From the remaining 387 tasks, deterministic selection produced 120; 267 eligible tasks were not selected. Structural rejections remain zero. No confirmed family merges were made. The selected set has 120 observed singleton families under this procedure.

This is an operational family definition, not proof that the tasks are statistically independent. The screen may miss transformed variants. Conservative exclusions can change representativeness, and this limitation must be reported. Selection did not use agent success rates or golden answer values.

## Verification completed

All 16 unit tests pass. Final checks verified 60/30/30 counts, task uniqueness, observed-family and input-hash split isolation, absence of excluded tasks, all 240 extracted workbook hashes, manifest checksums, deterministic regeneration of selected IDs, and compatibility with the feedback-pool manifest adapter.

Structural readability does not certify reference answer correctness. Raw answer-position strings still need handling by the benchmark evaluator. This is an integration task, not a reason to withhold the prepared task dataset.

## Use and reproduce

From the `skillshift` directory:

```sh
python3 scripts/validate_split.py data/final_v1/task_manifest.json
python3 -m unittest discover -s tests -v
```

To recreate in a fresh checkout, run `prepare_data.py`, `review_families.py`, then `finalize_dataset.py`. The finalizer refuses to overwrite an existing `final_v1`. Preserve this version; make a new version with a change log if the team later changes the protocol.

The executor receives `data/final_v1/inputs/` only. Gold files in `evaluator_only/` and the source archive belong to the evaluator/admin environment and must not be exposed to the model. Directory naming is not an access-control mechanism.

Pass `--task-manifest data/final_v1/task_manifest.json` to the pool builder when real attempt records exist. The pool design configuration is still unresolved. Independent reruns must remain separate from injected copies.

## What is not yet produced

The user confirmed that the team has not agreed on a model or API budget. No paid model runs have been started. There are no real feedback attempts or final experimental pools. Those require the selected executor/model, budget, shared attempt schema, and explicit C1/C2/C3 intervention definitions. These dependencies are separate from the completed workbook dataset.
