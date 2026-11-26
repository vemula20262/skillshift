# C3 feedback handoff

C3 concentrates repeated execution-error feedback across development tasks. It keeps all 60 original attempts, adds 45 failure copies from tasks 49300, 57558 and 57590 (15 each), and adds one copy of each of the 15 successful attempts. The result is 120 records with 30 successes and 90 failures, matching C1_50's size, repeat fraction and outcome ratio.

The category is selected from development records only: execution errors occur in three distinct tasks, while wrong_values already accounts for 42 of 45 original failures. C3 increases execution-error occurrences from 3 to 48. These are copies of observed failures, not new independent attempts, fabricated feedback or proven semantically identical mistakes. The coarse exec_error label can contain different underlying causes. The three-task coverage limits generalization. C3 and C1_50 also differ in success-copy concentration, so their comparison does not isolate failure category as the sole causal factor.

## Reproduce

Use the public input SHA-256 `8e5ef6e4c0a6e6a303c867a2264f3f31ef70778b603c4c7fa7a2037e47e09f00`. The public copy removes one personal checkout path from task 57558's error message. `attempts/provenance.json` records the original and public hashes; all other input bytes are preserved. Do not mix manifests from the earlier private archive with these public files. Configuration `config/pools.grid.json` includes C0, C1_50 and C3. Per-pool dominant task IDs override the shared default. The optional failure_category guard requires matching failures from at least two distinct tasks.

```sh
python3 scripts/build_pools.py --input attempts/records.jsonl --config config/pools.grid.json --task-manifest datasets/120/task_manifest.json --output-dir pools/grid_rebuilt
python3 scripts/validate_attempts.py attempts/records.jsonl pools/grid/C0.jsonl pools/grid/C1_50.jsonl pools/grid/C3.jsonl
```

The repository includes `attempts/records.jsonl` and all three pools under `pools/grid/`, together with their manifest, statistics, validation summary and checksums. Rebuilt public pools differ from the earlier private handoff only in occurrences of the sanitized error message; counts and selection rules are unchanged. Other runtime attempts and outputs remain ignored.

## Selector handoff

Pull this PR branch to obtain all supplied selector inputs; no ZIP is required. The records contain nonempty summaries and trajectory hashes. All embeddings are null: semantic selection still requires embeddings and calibrated thresholds. Full raw trajectories are unavailable in this checkout and remain with the original collector; do not interpret trajectory hashes as the trajectory contents. Raw trajectories are needed by later update runs, but not to compare hashes for exact deduplication.

Validate without model calls using the commands above. `pools/grid/SHA256SUMS.json` uses repository-relative paths. The regenerated output directory must be new. Public files contain existing attempt feedback and do not represent new model runs.

For the grid-runner PR, set C3's repeat fraction to `"1/2"` rather than null so its full original-content and provenance checks run. The handoff includes `config/grid.c3.json` with that setting and the existing five selectors and three seeds. Semantic thresholds, the exact trajectory deduplication change and API credits remain execution dependencies. No model calls or full-grid results are produced by this handoff.
