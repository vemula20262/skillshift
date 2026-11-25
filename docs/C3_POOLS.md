# C3 feedback handoff

C3 concentrates repeated execution-error feedback across development tasks. It keeps all 60 original attempts, adds 45 failure copies from tasks 49300, 57558 and 57590 (15 each), and adds one copy of each of the 15 successful attempts. The result is 120 records with 30 successes and 90 failures, matching C1_50's size, repeat fraction and outcome ratio.

The category is selected from development records only: execution errors occur in three distinct tasks, while wrong_values already accounts for 42 of 45 original failures. C3 increases execution-error occurrences from 3 to 48. These are copies of observed failures, not new independent attempts, fabricated feedback or proven semantically identical mistakes. The coarse exec_error label can contain different underlying causes. The three-task coverage limits generalization. C3 and C1_50 also differ in success-copy concentration, so their comparison does not isolate failure category as the sole causal factor.

## Reproduce

Use the exact input SHA-256 `d2de6a9e0241ba6b67935950d9cd15804413d4a729af11e51ea52e8e372bdf34`. Configuration `config/pools.grid.json` includes C0, C1_50 and C3. Per-pool dominant task IDs override the shared default. The optional failure_category guard requires matching failures from at least two distinct tasks.

```sh
python3 scripts/build_pools.py --input attempts/records.jsonl --config config/pools.grid.json --task-manifest datasets/120/task_manifest.json --output-dir pools/grid
python3 scripts/validate_attempts.py attempts/records.jsonl pools/grid/C0.jsonl pools/grid/C1_50.jsonl pools/grid/C3.jsonl
```

C0 and C1_50 retain their previous JSONL bytes. All three pools share one manifest and statistics file. Raw attempts, generated pools and the handoff archive remain outside Git. The handoff includes the exact input, task manifest, config, pool files, statistics, validation summary and file checksums. Raw trajectories are not included; retain the original collection for model execution.

For the grid-runner PR, set C3's repeat fraction to `"1/2"` rather than null so its full original-content and provenance checks run. The handoff includes `config/grid.c3.json` with that setting and the existing five selectors and three seeds. Semantic thresholds, the exact trajectory deduplication change and API credits remain execution dependencies. No model calls or full-grid results are produced by this handoff.
