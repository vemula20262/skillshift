> Update: the initial candidate described below has been superseded by `data/final_v1/`. See `docs/FINAL_DATASET.md` and `docs/DATA_SECTION_V1.md` for the current reviewed working dataset. The earlier preparation details are retained as history.

# SkillShift: understand the project and your role

Reviewed November 3, 2026. This is a working guide, not an experiment-results report.

## The question in everyday language

Suppose an AI spreadsheet assistant fails on the same workbook repeatedly. Its instruction-writing assistant sees ten reports of that failure and one report from each of several other workbooks. It might conclude that the repeated failure is a widespread problem and add an overly broad rule. Your project asks whether choosing feedback more carefully leads to better instruction updates.

The underlying AI model stays fixed. A **skill** is a written instruction document used by the agent. **Skill evolution** means editing that document after examining past attempts. You are testing the quality of the evidence used to make an edit, not training a new language model.

The proposed solution considers both the origin of feedback and its meaning: remove duplicates within a source, preserve failures observed across different sources, and give different sources a chance to contribute. Similar wording from different workbooks may reveal a real recurring problem; repeated copies from one workbook do not provide the same evidence.

This is a data-mining project because the central work involves duplicate detection, semantic similarity, clustering, representative sampling, and evaluating whether those choices improve downstream performance.

## What happens in an experiment

1. Prepare spreadsheet tasks, their input workbooks, and reference answers.
2. Separate related tasks into development, validation, and test groups, with no source family crossing those groups.
3. Run the starting agent on development tasks. Store its attempts, errors, and evaluator outcomes.
4. Construct feedback pools, including deliberately repeated records from selected sources.
5. Compare five feedback selectors: unfiltered, exact deduplication, global semantic deduplication, source balancing alone, and the proposed combined selector.
6. Give each selected feedback set to the instruction optimizer, starting from the same parent skill.
7. Accept a proposed edit only when it passes the agreed validation improvement rule.
8. Evaluate the resulting skill on held-out test tasks. Compare successes with the parent, calculate uncertainty, and count accepted edits that actually hurt test performance.

Development data is where methods and thresholds are built. Validation data decides whether to accept an edit. Test data measures the final result; it must not guide tuning. Structural checks of test input/reference files are data quality checks, not model test evaluations.

## Thushar's responsibility

You own the data foundation. Your teammates depend on reliable task identifiers, family assignments, splits, and feedback pools.

- **November 3:** download Verified 400, check input/reference files, and produce `tasks_120.csv` plus rejected-task reasons.
- **November 4:** produce `families.csv`, a reasoned `merge_log.csv`, and a reproducible 60/30/30 split with leakage checks. Candidate assignments must be reviewed before calling the split frozen.
- **November 8:** build pilot pools from real evaluated attempts and provide pool statistics. Draft the Data section with counts, families, merge examples, and limitations.
- **November 10:** finalize the ten agreed feedback pools and their statistics.
- Review Venkata's selector work; Thanishka reviews your work. All five members contribute to writing and presenting.

These dates come from the November 2 team tracker. Its displayed Days Left values appear based on November 2; use the actual dates. On November 3, your first task is due today.

## Who supplies what

- **Charith:** shared attempt schema, SkillOpt integration, fixed execution configuration, and validation gate.
- **Venkata:** the five feedback-selection methods and development-only threshold tuning.
- **Varshini:** real attempts and success/failure labels, trajectory parsing, experiment runs, and cost records.
- **Thanishka:** statistical comparisons, qualitative analysis, and report assembly.
- **Thushar:** task inventory, source families, split integrity, feedback pools, and dataset writing.

You can prepare and test the data pipeline now. Real feedback pools depend on Varshini's attempt records and Charith's schema. Results and conclusions depend on running the integrated experiment.

## Decisions that must be resolved

1. **Pool definitions:** the tracker requests ten pools and refers to C0 and C1/C2/C3 at 25%, 50%, and 75% repeats, but never defines what distinguishes C1, C2, and C3. One baseline plus three conditions at three levels would yield ten, but that is an inference, not a documented design. The 24 reruns on four dominant tasks may represent a different intervention from copying records. Keep independent reruns distinct from exact copies.
2. **Repeat denominator:** state whether 50% means half the final pool consists of copies or copies equal half the original pool. The provided copy-pool utility uses copies divided by final record count and documents that choice.
3. **Trial grid:** the proposal specifies 5 methods × 2 conditions × 3 source-order seeds = 30 updates; the tracker specifies 10 pools × 5 methods = 50. Decide whether seeds remain, and revise cost projections before runs.
4. **Selector:** the proposal describes complete-linkage clustering within source families, shortest representatives, and round-robin selection. The tracker adds family × failure-behavior grouping and inverse-group-size weights. These are not automatically the same algorithm.
5. **Acceptance gate:** the proposal says strict validation improvement; the tracker says a fixed margin. Specify the margin before observing candidate results. On 30 validation tasks, one additional success changes accuracy by 1/30 (about 3.33 percentage points).
6. **Family evidence:** shared workbook content or documented variants justify grouping. Similar instructions, error types, or layouts alone are insufficient. Automated hashes cannot discover every edited workbook variant; review candidates and preserve uncertainty.
7. **Budget and configuration:** agree on API cap, model, starting skill, executor/evaluator versions, summary template, embedding model, token budget, seeds, and randomness settings before paid runs.

## A practical sequence from today

First review the generated inventory and ambiguous family candidates, settle any existing split, and freeze a reviewed split by November 4. Give its task IDs and hashes to Charith and Varshini. In parallel, Charith can finish the schema and executor while Venkata implements selectors.

Next, use a development-only ten-task pilot to verify the complete path from input workbook through evaluator-labelled attempts to feedback selection and a proposed edit. The pilot should establish runtime and cost before committing to the full grid. No success/failure labels should be inferred from whether an output file merely exists.

Once real records arrive, validate them against the agreed schema, construct the explicitly defined pools, and verify unique-record preservation, repeat fractions, outcome proportions, and source concentration. By November 8, hand Thanishka the measured dataset description and preliminary pilot data. The tracker sets the progress-report deadline to November 9.

Finally, finalize pools by November 10, support runs through November 13, and assist analysis through November 16. Preserve the tracker rule that test results are not inspected until the full grid is done; this includes avoiding interim test-driven changes to the methods. Record exceptions or reduced scope before final testing.

## Course deliverables and attribution

The course guidelines require an ACM/KDD-style final report, at most eight pages excluding references and appendices, with Abstract, Introduction, Related Work, Data, Methods, Results, Discussion, and Conclusion. The progress report is an intermediate version with mostly complete introductory and data sections. The guideline table lists 4–5 pages for the progress report.

The approved-ideas deck lists December 4 for final reports; the proposal targets November 28 for preparation. Course documents conflict on presentation duration (four versus five minutes), and some dates remain TBD. Treat the November 9 progress date as the team's stated hard deadline and confirm official submission details in the current course assignment.


## Sources reviewed

- [Group proposal](https://docs.google.com/document/d/1VJhdOLq5yc7422pCwFn9ID3P6vW0Abzfa-YkxCQ8CeU/edit), last modified October 10.
- [Team task plan](https://docs.google.com/spreadsheets/d/1nd9c6bN-aQl7OLCSauuca2ssmNa4dpCUjfJHSSnTsaA/edit), last modified November 2; tracker, milestones, progress-report contents, and ground rules reviewed.
- [Course project guidelines](https://drive.google.com/file/d/17Vnh32MxmSCWXJqU1gvMRmrp6WORuhT0/view).
- [Approved project ideas](https://docs.google.com/presentation/d/1bqSyWHcKdkIAQKAijt4YKtOthuWyusvRH-v9Dvvz7pM/edit), including the Self-evolution Agent topic.
- [SpreadsheetBench data](https://huggingface.co/datasets/KAKA22/SpreadsheetBench/tree/main) and [official repository](https://github.com/RUCKBReasoning/SpreadsheetBench).
- [SkillOpt](https://arxiv.org/abs/2605.23904) and [feedback-dynamics paper](https://arxiv.org/abs/2608.02636): abstracts checked to verify the cited work and project framing.

The local `sources/` folder and discovered course Drive folder were empty. Targeted ASU-email searches located course notifications but no SkillShift implementation or attempt files. This review does not imply access to every course submission or a completed team repository.
