# 400-task version

400 source tasks, 398 runnable: 198 development / 100 validation / 100 test. Do not mix these splits with the other version.

Use `task_manifest.json`, `splits.json` and the `*_executor.json` files for runs. `source_manifest.json` and `source_splits.json` keep every source task, including excluded ones. `rejected_tasks.csv` lists exclusions with reasons and `not_selected.csv` the eligible tasks that were not sampled. `families.csv` records source families, and `precautionary_group_log.csv` lists possibly related tasks kept in the same split. `pilot_10.json` lists the development pilot tasks and `data_summary.csv` the split counts.

To restore and check the workbooks, run `python3 scripts/prepare_data.py`, then `python3 scripts/prepare_variants.py --materialize` and `python3 scripts/prepare_variants.py --verify`. Input workbooks go to `inputs/` and reference workbooks to `evaluator_only/`; only inputs belong in the agent's workspace.

Source: https://huggingface.co/datasets/KAKA22/SpreadsheetBench (CC BY-SA 4.0). Workbooks are not modified.
