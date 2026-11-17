<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Preregistered gate for the answerability check

These are the acceptance criteria for the answerability check (audit finding
E1, draft PR #112), copied verbatim from the files written **before** any run of
the candidate. They are kept here so that "the criteria were fixed first" can be
checked: each file's SHA-256 was taken when it was written, on 2026-11-17, and
is given below. The measurement they governed, and its verdict, are entry E36 of
[experiments.md](./../experiments.md).

## The gate as first written

SHA-256 of the original file: `2c34828d60b4924d6c2c9ebb849de2b9a0d6008200a550fdfbb9af4b12bd3102`

```text
PREREGISTERED GATE FOR THE ANSWERABILITY CHECK (audit E1, draft PR #112)
Written 2026-11-17 BEFORE any run of the candidate. The candidate (branch
p2-answerability, flag `answerability_check_enabled`) has never been run
against a model. Nothing below may be changed after the first candidate run
except by an amendment dated and written before the run it concerns.

WHAT IS COMPARED
  Baseline ("off"): the current engine, image built from main b371dc11
                    (flag absent). Run on 2026-11-17 on the local stack.
  Candidate ("on"): the image built from p2-answerability with the
                    configuration row `answerability_check_enabled` = true.
  Same stack, same machine, same gateway, same frozen cases files, same
  harness, 4 workers, 3 repeats. Sets: unanswerable.json with its 12 controls
  (36 + 12 questions), chinook.json (20), pagila.json (13), rentals.json (24).
  Runs are alternated by set where practical; the order actually used is
  recorded. Each side uses a populated semantic index (the harness refuses an
  empty one).

KNOWN LIMITS, STATED NOW
  All four sets come from public or invented databases, with no real company
  data. They show whether the mechanism works on them; they do not show it
  holds on a customer's data. No threshold below was tuned on these sets: the
  mechanism has no numeric threshold, and the decision thresholds below were
  chosen from the earlier E27 gate (which used 80% catch, 0 false alarms on 14
  controls, a 10% ceiling on answerable tasks) before seeing any candidate run.
  Run-to-run noise on 3 repeats is about one run in three per question; one
  question is 2.8 to 8 points on these sets.

CRITERIA (all must hold for ACCEPT; a failure is recorded as it is)
  C1  Catch. On the unanswerable set the TOLERANT refusal rate of the
      candidate is at least 50%, and at least 25 points above the baseline.
      (Tolerant = no executed query result, as defined in docs/evaluation.md
      "Unanswerable questions".) Runs scored no_answer are excluded from the
      denominator and counted.
  C2  Paired evidence for C1. Among the unanswerable questions whose majority
      outcome flipped between arms, the exact two-sided sign test favours the
      candidate with p < 0.05.
  C3  No false refusals on the controls. Of the 12 control runs x 3, the
      candidate refuses (returns no executed rows) on at most 1 run more than
      the baseline does.
  C4  No regression on the answerable sets. For each of chinook, pagila and
      rentals, `python -m dev_tools.evals compare baseline candidate --margin 0`
      does not REJECT (no question regresses by more than the harness
      tolerance, and the score does not fall), AND the share of candidate runs
      on those three sets that carry an `answer.refusal` or the `unanswerable`
      caveat is at most 10%.
  C5  The four `needs-definition` rentals questions (certified definitions
      given as evidence) are never refused by the candidate in 3 of 3 runs.
  C6  Cost is reported, not gated: extra model calls and added seconds per
      question, from the harness durations.

DECISION RULES
  ACCEPT only if C1 to C5 all hold. Otherwise REJECT: the draft PR stays a
  draft and the flag stays off; the numbers go into docs/experiments.md anyway.
  A candidate that passes C1 and fails C3, C4 or C5 is a failed candidate, not
  a candidate to be re-tuned on these sets: any change to the prompt or the
  decision rule after seeing results makes these sets no longer held out for it
  and must say so.
  The LiveSQLBench 180-task check of E27 (criterion 4 and 5 there) is NOT part
  of this gate: it takes hours and its data stays outside the repository. If
  ACCEPT is reached here, enabling the flag by default additionally needs that
  run; this document does not claim it.

REPORTING
  Strict and tolerant scores for the unanswerable set; per-question table; the
  replay rule of docs/evaluation.md applied identically to both arms; reports
  kept outside the repository, summaries in docs/experiments.md and the history
  file (docs/eval-history/history.jsonl).
```

## Amendment 1 (the combined candidate image, the replay rule, and the gate for the soft-delete hint)

SHA-256 of the original file: `b59c3b8c0f2985b56dda8e99cb9af90b69d0ef5fbee6f2928da9875a8dbf9c43`

```text
AMENDMENT 1 to PREREGISTERED_E1.txt, and preregistration of the soft-delete gate
Written 2026-11-17, BEFORE any run of any candidate. No candidate has run.
(PREREGISTERED_E1.txt sha256 2c34828d60b4924d6c2c9ebb849de2b9a0d6008200a550fdfbb9af4b12bd3102 is unchanged.)

A. WHAT CHANGES IN THE ANSWERABILITY GATE (E1)
  A1  The candidate image is built from the LOCAL branch `gate-candidate`
      (the branch of draft PR #112, plus the commit of draft PR #115, a flagged
      soft-delete hint), not from p2-answerability alone, to avoid building twice.
      The soft-delete flag (`soft_delete_hint_enabled`) is OFF in the answerability
      arm. Its code with the flag off renders the schema context byte for byte as
      before (a test in PR #115 compares it with the pre-change output), so the
      answerability arm is the same engine as the branch of #112 with the flag on.
      The base of both is main b371dc11 (no database migration), the same commit
      the baseline image was built from.
  A2  The baseline for chinook and pagila is measured on the current image
      (main b371dc11) after the unanswerable and rentals baselines, on
      2026-11-17, with the machine kept awake. The unanswerable baseline run on
      2026-11-17 00:02 to 03:58 was disturbed by a machine sleep: 8 of its 21
      no_answer runs lasted 2848 to 8324 s. The replay rule applied to BOTH arms:
      a question having a run that lasted more than 600 s is run again
      (`run --only`, all its repeats) and the new report replaces the old
      entry (`merge`). 13 runs ended at the 300 s run limit: those are the
      engine's own, stay as no_answer, and are excluded from the denominator by
      the frozen scoring rule. Both arms are reported with their no_answer counts.
  A3  The baseline measured so far, for the record, before any candidate ran:
      unanswerable set, tolerant: 12 of 87 scored runs refused (13.8%), 21
      no_answer; controls: 35 of 36 correct; rentals: 32 of 72 runs (44.4%).

B. PREREGISTERED GATE FOR THE SOFT-DELETE HINT (draft PR #115)
  What it changes: with the flag on, a table that has a detected soft-delete
  marker column carries one sentence in the schema context asking to exclude
  deleted rows by default. It changes what the model sees; it must pass this gate
  before the flag is enabled by anyone.
  Arms: baseline = current image, both flags off (the arms already measured on
  main b371dc11); candidate = the gate-candidate image with
  `soft_delete_hint_enabled` = true and `answerability_check_enabled` = false.
  Sets: rentals.json (24), chinook.json (20), pagila.json (13), 3 repeats, 4
  workers. Same harness, cases files and rules as the gate above.
  LIMIT STATED NOW: the rentals set is the MOTIVATING set for this change (its
  baseline failures are what led to it), so it is a development set for it and
  proves nothing about held-out data. Chinook and Pagila have no soft-delete
  marker columns (declared in their fixtures): they are the regression guard and
  should be unchanged; a difference there would be noise or a side effect.
  Criteria (all must hold; a failure is recorded):
  S1  Effect: on rentals the candidate's score is at least 15 points above the
      baseline's (44.4%), and no question that passed 3 of 3 on the baseline
      fails more than 1 of 3 on the candidate.
  S2  Guard: for chinook and for pagila, `compare baseline candidate --margin 0`
      does not REJECT.
  S3  Targeted: of the 13 rentals questions that failed every run on the baseline,
      at least 6 pass in at least 2 of 3 runs on the candidate.
  S4  Cost reported, not gated: added tokens or seconds per question.
  ACCEPT only if S1 to S3 all hold. Otherwise REJECT; the draft stays a draft and
  the flag stays off. Any change to the detector or the annotation after seeing
  these results makes rentals no longer usable even as a development set for the
  changed version, and must be said.
  NOT claimed even on ACCEPT: that the hint helps on a customer's own data, that
  booleans or status codes are handled, and that the LiveSQLBench tasks do not
  regress (not run).
```

## Amendment 2 (the gate for version 2 of the check, on fresh blind sets)

SHA-256 of the original file: `a35a4dbdf56b978cf8919fd6a8372716eaade970da41c0b44c0ab4f89a128328`

```text
AMENDMENT 2: gate for VERSION 2 of the answerability check
Written 2026-11-17 BEFORE any run of version 2 and before the two fresh sets exist
in the repository (they are being written blind by another agent). Version 2 has never
run against a model.

WHAT HAPPENED TO VERSION 1
  Version 1 was measured under PREREGISTERED_E1.txt (sha256 2c34828d...). C1 and C2
  passed (100% of 105 scored unanswerable runs refused; baseline 13.2%; sign test
  p about 2e-9); C3 FAILED (6 of 36 answerable control runs refused, baseline 0).
  Verdict: REJECTED, recorded as it is. Its answerable-set runs (chinook, pagila,
  rentals) were still running when this amendment was written and will be reported
  as information; they do not change the verdict.
  The cause, read from the backend log: a computed measure (a revenue that exists
  only as payments joined to films) was called absent, and a table that the
  relevance filter had dropped made an item (a customer's country) look absent.

WHAT VERSION 2 CHANGES (draft PR #112, branch p2-answerability, written without
looking at any evaluation set, report or log): computed measures are told to be
derivable, not absent; and before refusing, every item the first pass calls
absent is checked once more against the whole catalog of the database (names and
types only), with fail-open on a truncated outline.

WHY THE OLD SETS CANNOT JUDGE IT
  unanswerable.json, chinook.json, pagila.json and rentals.json have been seen by
  version 1 and the failures that shaped version 2 came from them. They are
  development sets for version 2. Version 2 is judged on two NEW frozen files
  written blind (without access to the check, its code, its reports or the
  engine's behaviour): `unanswerable_rentals.json` (24 questions that cannot be
  answered, on the Rentals database) and `answerable_heldout.json` (36 answerable
  questions, 12 per database on chinook, pagila and rentals; 6 per database of the
  shape "a measure computed through joins", 4 of "a table reached through 2 to 3
  joins", 2 plain).

ARMS
  Baseline: the same candidate image with `answerability_check_enabled` = false
  (equal to the engine without the check: a flag-off test proves identical
  rendering and zero extra calls). Candidate: the image built from
  origin/p2-answerability (version 2) with the flag true. Same stack, machine,
  gateway, harness, 4 workers, 3 repeats, populated semantic index. Runs
  alternate by set; the order used is recorded. The replay rule is as in
  Amendment 1 (a question with a run longer than 600 s is run again for the
  arm concerned; runs ending at the 300 s limit stay no_answer, excluded from the
  denominator and counted).

CRITERIA (all must hold for ACCEPT; a failure is recorded)
  V1  Catch. On unanswerable_rentals the TOLERANT refusal rate of the candidate is
      at least 50% and at least 25 points above the baseline's.
  V2  Paired evidence for V1: among questions whose majority outcome flipped, the
      exact two-sided sign test favours the candidate with p < 0.05.
  V3  False refusals. On answerable_heldout, the share of candidate runs that return
      no executed rows or carry the refusal marker is at most 10%, AND at most 5
      points above the baseline's share, AND at most 10% within each tag
      (`computed`, `far-table`, `plain`) taken separately.
  V4  No regression. `compare baseline candidate --margin 0` on answerable_heldout
      does not REJECT.
  Reported, not gated: the same measures on the old development sets; extra model
  calls and seconds per question; how many refusals were reached through the
  escalation (log lines) and how many items it rescued.

DECISION
  ACCEPT only if V1 to V4 hold. Then the flag may be switched on by the owner after
  the owner's own decision; this amendment does not enable it and does not claim it
  holds on customer data or on the LiveSQLBench tasks (not run). REJECT otherwise:
  the draft stays a draft, the flag stays off, the numbers go into the experiments
  log. A third version would need a third set of fresh blind sets: the sets used
  here become development sets for it.
```
