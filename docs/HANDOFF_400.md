# Full 400-task handoff

Version: full400_v1. This supersedes the earlier 120-task selection for the expanded study. The old version is retained for history only. No model results or team signoff are implied.

## Ready to use

All 400 tasks and their 800 original workbooks are retained. Development contains 200 tasks; validation and test contain 100 each. This preserves the proposal's 50/25/25 proportions while expanding the sample. `pilot_10.json` contains ten development-only task IDs.

Seven unresolved relationships involving 13 tasks are recorded in `precautionary_group_log.csv`. Connected tasks stay in the same split, so no uncertain pair crosses development, validation or test. These are precautionary split blocks, not proven shared-source families. `family_id` retains observed source identity; `split_group_id` identifies the block used to prevent leakage. For conservative uncertainty estimates, the statistics pipeline should resample these blocks rather than pretend the potentially related tasks are independent. Feedback selectors should use the team's documented source-family definition and must not silently reinterpret these blocks as confirmed lineage.

No tasks are rejected. Source checksums, task counts, split assignments and limitations appear in `provenance.json`. Heuristic screening cannot guarantee that all hidden variants were found. Structural checks do not certify reference-answer correctness or evaluator compatibility.

## Files and responsibilities

- Charith: use `task_manifest.json` for evaluator integration and the three `*_executor.json` files for task execution. Executor manifests omit golden paths and golden audits. Raw answer positions in the task manifest remain unchanged and must be handled by the benchmark evaluator.
- Varshini: start with `pilot_10.json`. Collect two attempts per development task only after the pilot/configuration is fixed: the expanded base collection is now **400 original attempts**, not 120. Log task IDs, family IDs, split blocks, evaluator outcomes and configuration versions. Any 24 additional reruns remain a separate protocol decision.
- Venkata: join feedback records to task/family metadata; tune on development only. The exact definitions of C1/C2/C3 remain unresolved.
- Thanishka: review the split protocol change and use the appropriate block unit for uncertainty analysis. Recalculate run/runtime projections because validation and test each grew to 100 tasks.
- Thushar: provide this fixed version and record any future change as a new version.

## Safe execution layout

`inputs/` contains original input workbooks. `evaluator_only/` contains reference answers. Only input workbooks and the relevant executor manifest should be placed in the model's workspace. Keep gold answers, the full source archive and evaluator access outside that workspace. Directory names alone do not enforce isolation.

## Verification and reproduction

From the project root:

```sh
python3 scripts/prepare_full_dataset.py --verify
python3 -m unittest discover -s tests -v
```

For a fresh clone, first run `python3 scripts/prepare_data.py` to download/audit the pinned source, then `python3 scripts/prepare_full_dataset.py`. The final builder refuses to overwrite an existing output version. Its source audit and seven explicit precautionary pairs are reproducible. To regenerate for comparison, use `--output` with a new directory. The archive SHA-256 must match the recorded value.

The prior `validate_split.py` defaults to the historical 120-task split. For this version use `prepare_full_dataset.py --verify`, which checks 400 unique IDs, 200/100/100 counts, group and hash isolation, all 800 workbook hashes, split-file consistency, pilot membership and metadata checksums.

When real feedback arrives, the pool builder accepts `--task-manifest data/full400_v1/task_manifest.json`. Keep `split_group_id` in attempt records for downstream analysis. No real pools have been produced; this handoff completes the source-task preparation, not the model experiments.

## Source and attribution

SpreadsheetBench Verified is obtained from https://huggingface.co/datasets/KAKA22/SpreadsheetBench, archive `spreadsheetbench_verified_400.tar.gz`. The dataset page identifies CC BY-SA 4.0 licensing: https://creativecommons.org/licenses/by-sa/4.0/. Retain attribution and applicable license terms when sharing. Workbooks are copied without edits; split metadata and precautionary block assignments are project additions. The code/model execution environment has not yet been validated on Sol.
