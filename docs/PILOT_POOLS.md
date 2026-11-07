# Pilot feedback pools

The pilot uses the frozen 120-task package and the 60 original development attempts in `attempts/records.jsonl`. The input SHA-256 is `d2de6a9e0241ba6b67935950d9cd15804413d4a729af11e51ea52e8e372bdf34`.

C0 contains all 60 originals, with 15 successes and 45 failures. C1_50 retains those originals and adds 60 exact copies, yielding 120 records with 30 successes and 90 failures. Copies account for half the final pool, preserving the 1:3 outcome ratio.

## Repeated-task selection

The pilot selects one successful task and three failed tasks by sorting SHA-256(`skillshift-c1-pilot-v1:` + task ID) ascending within each outcome. The selected IDs are `524-31` (success), `54274`, `49667`, and `49945` (failures). Each receives 15 copies and therefore appears 16 times in C1_50. This is a reproducible pilot design choice, not a claim of team-wide protocol agreement. Outcome stratification preserves the required ratio; no validation or test outcomes are used.

The explicit configuration is `config/pools.pilot.json`. Its approved status enables the builder for this pilot; it does not certify a team review.

## Build and verify

Use the supplied input file without reformatting it. From the repository root:

```sh
python3 scripts/build_pools.py --input attempts/records.jsonl --config config/pools.pilot.json --task-manifest datasets/120/task_manifest.json --output-dir pools/pilot
```

The output directory must be new. The builder writes both JSONL pools, `manifest.json` with input checksums, and `pool_stats.csv`. Verify the attempts checksum in the manifest against the value above before running experiments.

On the evaluation-runs-and-costs branch, which provides the pilot validator:

```sh
python3 scripts/validate_attempts.py attempts/records.jsonl pools/pilot/C0.jsonl pools/pilot/C1_50.jsonl
python3 scripts/run_pilot.py --pool-dir pools/pilot --check
```

The delivered pools passed schema validation, the pilot's content/checksum/statistics checks, and selection by unfiltered, exact_dedup and source_balanced at revision `e17ec10`. The pilot check reported no pool problems. No model calls or evaluation runs were performed during pool preparation.

## Handoff

Attempt records and generated pools remain outside Git under the existing ignore rules. The separate handoff archive contains the exact input file, both pools, configuration, task manifest, statistics, validation results and file checksums. It supersedes the earlier C0-only package. Raw trajectories referenced by the attempts are not included; retain the original collection for downstream steps that require those files.
