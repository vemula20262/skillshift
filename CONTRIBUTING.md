# Contributing

Use a separate branch for each change and open a pull request to main. Every pull request needs one teammate's review before merging, as specified in the team task tracker.

## Review rotation

- Thushar's changes: Thanishka reviews.
- Thanishka's changes: Varshini reviews.
- Varshini's changes: Charith reviews.
- Charith's changes: Venkata reviews.
- Venkata's changes: Thushar reviews.

GitHub usernames and collaborator access must be supplied before assigning reviewers. This document describes the team process; it does not imply branch protection is enabled.

## Checks

Run `python3 -m unittest discover -s tests -v`. For data changes, also run `python3 scripts/prepare_full_dataset.py --verify`. Explain any changes to selected tasks, source families, or experiment settings. Do not use test results to tune the methods.

Keep secrets, downloaded workbooks, and private attempt records out of commits. Preserve dataset attribution and record source checksums. Distinguish actual experiment results from synthetic test fixtures.

## Local commit workflow

For Thushar's changes, prepare the proposed file list and commit message for review and obtain Thushar's explicit confirmation before any commit. Do not commit, push, or merge on Thushar's behalf without the applicable authorization.
