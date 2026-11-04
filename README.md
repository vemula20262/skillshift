# SkillShift — source-balanced feedback for agent skill updates

## Current dataset: all 400 tasks

The completed source-task handoff is **data/full400_v1/**: 200 development, 100 validation, and 100 test tasks, with all 800 original input/reference workbooks. Start with [the handoff instructions](docs/HANDOFF_400.md).

All tasks are retained. Seven uncertain relationships involving 13 tasks are kept within single splits using explicitly precautionary blocks. They are not claimed to be proven shared-source families. No model runs or real feedback pools have been produced.

The earlier 120-task datasets and drafts are historical, not the active study split. The full400_v1 protocol supersedes their task counts and exclusions. The expanded split has not been represented as team-approved.

## Reproduce

Python 3 standard libraries are sufficient for preparation:

```sh
python3 scripts/prepare_data.py
python3 scripts/prepare_full_dataset.py
python3 scripts/prepare_full_dataset.py --verify
python3 -m unittest discover -s tests -v
```

The full builder refuses to overwrite an existing version. Downloaded and extracted workbooks are excluded from Git; use the scripts to retrieve the pinned archive and materialize them locally. Only inputs and executor manifests belong in the model workspace. Reference workbooks belong exclusively to the evaluator.

## Feedback preparation

The tested builder in `scripts/build_pools.py` supports exact-copy interventions and validates development membership against the full task manifest. See [the pool contract](docs/pool_contract.md). Real evaluator-labelled attempts, C1/C2/C3 definitions, and the fixed model/execution configuration are still needed.

The expanded plan has 200 development tasks, so two attempts each means 400 original attempts. Validation and test each contain 100 tasks. Recalculate experiment costs/runtime and agree on the changed study protocol before full runs on Sol.

## Collaboration

See [CONTRIBUTING.md](CONTRIBUTING.md). Work on a branch and obtain one teammate review before merging. Thanishka reviews Thushar's work. Commit and push authorization remain separate from local preparation.

## Sources

[SpreadsheetBench Verified](https://huggingface.co/datasets/KAKA22/SpreadsheetBench), [official benchmark repository](https://github.com/RUCKBReasoning/SpreadsheetBench), and [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Original workbooks remain unchanged; this project adds reproducible inventories, grouping precautions and splits.
