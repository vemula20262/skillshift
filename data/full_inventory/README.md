# Full source inventory

All 400 tasks passed the existing structural audit. all_400.csv retains every original task and its workbook hashes. eligible_387.csv applies the conservative lineage exclusions used for working dataset v1. The 13 flagged tasks are not demonstrated corrupt or incorrect; they require stronger source-family evidence or explicit grouping before cross-split use.

These files are inventories, not a new frozen experimental split. The existing 120-task version remains unchanged. Expanding the experiment requires a revised development/validation/test allocation and run budget before evaluation. Sol access can enable local open-model inference without commercial API charges, but actual account access, GPU availability, and runtime must be verified by a pilot.

Original source: https://huggingface.co/datasets/KAKA22/SpreadsheetBench
Archive: spreadsheetbench_verified_400.tar.gz. Raw files remain outside Git tracking. Preserve dataset attribution and license when redistributing; the inventories and download scripts are sufficient to reproduce retrieval without storing all workbooks in Git.
