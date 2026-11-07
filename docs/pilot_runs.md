# Attempt collection, pilot runs and cost tracking

This covers the progress-report pilot: one original attempt per development task, the selector-ready records, six validation-only updates and the cost ledger. The second development pass, the dominant-task reruns, C3, the semantic selectors and the full grid come later.

All outputs are gitignored (`attempts/`, `results/`, `pools/`) and must be shared outside the repository.

## 1. Collect development attempts

```sh
python3 scripts/collect_dev_attempts.py --check
python3 scripts/collect_dev_attempts.py --call-limit 75
```

`--check` reports prerequisites (extracted workbooks, the API key named in `config/config.yaml`, skillopt) and progress without calling the model. A live run needs `--call-limit`. The team-approved allowance is 75 calls for this collection and 350 calls in total. The collection limit counts only collection rows in `results/cost.csv`, and each chunk is sized to the calls left, so successful calls never pass it.

Task IDs come from `datasets/120/task_manifest.json`. The starting skill is the one in `config/config.yaml`. Tasks run in chunks of `executor.workers` through `skillshift.attempts.collect_attempts` into `attempts/raw/dev_original/`:

- `results.jsonl` holds evaluated attempts only. Re-running skips them, so no completed model call is repeated.
- If a model call fails after SkillOpt's retries (rate limit, overload), `collect_attempts` leaves that task out of `results.jsonl` and raises, so collection stops instead of recording a fake failure. The chunk is logged in `cost.csv` as `failed`; re-running retries the task.
- Other infrastructure failures (harness timeout or crash, setup error) go to `infra_failures.jsonl`, with trajectories under `infra/<task>/<n>/`. They are retried up to `--max-infra-attempts`.
- Trajectories left by an interrupted chunk are moved to `interrupted/<task>/<time>/` before the task is rerun.

Collection is complete only when the evaluated task IDs equal the manifest's 60 development IDs, each once.

## 2. Prepare records

```sh
python3 scripts/prepare_records.py
python3 scripts/validate_attempts.py attempts/records.jsonl
```

This writes `attempts/records.jsonl` and `attempts/records_manifest.json` (path, SHA-256, counts). Each record gets a fixed-template `summary` built from its outcome, error category, task type, turns, tool events, imported modules and a normalized evaluator reason. Identifiers, paths, cell references, quoted values and numbers are kept out of the summary. The file is written only if it is schema-valid, covers exactly the 60 development tasks, has no empty summary, and `unfiltered`, `exact_dedup` and `source_balanced` can consume it. `embedding` stays null; these three selectors do not use it.

Pools are built from this exact file (see `docs/pool_contract.md`). The pool builder records its SHA-256 in `manifest.json`.

## 3. Pilot updates

```sh
python3 scripts/run_pilot.py --pool-dir pools/pilot --check
python3 scripts/run_pilot.py --pool-dir pools/pilot --call-limit 350
```

The pool directory needs `C0.jsonl` and `C1_50.jsonl`, plus `manifest.json` and `pool_stats.csv` when they exist. Before any model call, each pool is checked against `attempts/records.jsonl`: every occurrence must match its source record, every record must appear once as an original, the measured repeat fraction must be 0 for C0 and 1/2 for C1_50, and the manifest's attempts SHA-256 and the stats file must agree.

Runs go through `skillshift.update.run_update` with `evaluation.test_policy` set to `none` in memory. Pool and selector are the only settings that change: config, seed, validation task IDs (the full validation split), models, starting skill, feedback budget and gate margin are the same in all six runs. Each run log must show `test_evaluated: false`.

Here `--call-limit` is the total allowance and counts every row in `cost.csv`, including collection. A run starts only if the calls used so far plus its estimate fit. The estimate covers child validation, parent validation tasks not yet cached (the cache is shared across runs, so the parent is scored once), and SkillOpt's reflect, merge and rank calls for the most records the feedback budget can hold.

Output goes to `results/pilot/runs/<pool>__<selector>__seed<seed>/`. On restart, completed runs are skipped. A run directory without `run.json` is reported as partial and left in place. `--retry-partial` moves it to `results/pilot/partial/` and reruns it.

## 4. Results and cost

```sh
python3 scripts/pilot_report.py [--price-input USD_PER_M --price-output USD_PER_M --cap-usd USD]
```

This writes `results/pilot/report/`:

- `pilot_results.csv` and `pilot_results.md`: one row per completed `run.json`. Each row lists the edit outcome, parent and child validation scores, gate decision ("accepted", "rejected by gate", or "no edit (skill unchanged)") and feedback tokens, plus any missing combinations.
- `cost_summary.json`: measured calls and tokens by phase. Dollar figures appear only when pricing is given.
- `budget_burn.svg`: cumulative cost, or cumulative tokens when pricing is not set, with the cap line when known.

`results/cost.csv` gets one row per collection chunk and per update run, including failed and interrupted ones, keyed by `event_id` so nothing is counted twice. Provider usage comes from SkillOpt's token tracker, which records only calls that returned a response. Requests that failed after all retries are not visible there and are counted as `infra_failures` on collection rows. `feedback_tokens_estimate` is the pipeline's own feedback-size estimate and is kept separate from provider usage.
