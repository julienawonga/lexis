<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Conversation protocol: measuring what `run` cannot reach

`python -m dev_tools.evals run` is stateless (rule 8 of
[evaluation.md](./evaluation.md)): it never sends a `conversation_id` or a user,
so a change on a path that needs a conversation, clarification first of all,
cannot move its scores. This page holds the protocol written for that case (E31
of [experiments.md](./experiments.md), PR #82) and the tool that runs it.

## What is original and what is new

- **Original, verbatim:** everything between the two horizontal rules below,
  including both amendments. It was written and frozen on 2026-11-16 **before any
  run**, outside the repository (`lexis-evals/clarification/PREREGISTERED.txt`),
  and is copied here byte for byte (line endings aside). Do not edit it. File
  names it mentions (`questions.json`, `probe.py`, `probe.sha256`) refer to the
  original scripts; their hashes were `probe.py` 3e9cb0d3...bace and
  `questions.json` 418bb48a...ce81 (the second is also recorded in the cases
  file's description).
- **New, in this pull request:** this introduction and the section after the
  rules. The scripts were ported to `dev_tools/evals/conversation.py` and the
  questions to `dev_tools/evals/cases/conversation_clarification.json`, frozen
  with the usual `frozen_sha256` (checked by `python -m dev_tools.integrity`).
  The new code is **not** the hashed `probe.py`: the definitions were copied, but
  the code was rewritten to be testable, and it has never run against the live
  stack. A measurement made with it is a new run of the protocol, not a
  continuation of the one E31 reports.

---

```text
Pre-registered 2026-11-16, BEFORE any run (PR #82: a clarification option pins the answer to its database).

What the change can and cannot affect
  The frozen cases (dev_tools/evals/cases) run stateless, without conversation_id, so they never reach the clarification path. They cannot measure this
  change. Three purpose-built measurements replace them. Same stack, same models, clarification_enabled = true, machine otherwise idle, runs one after the
  other (workers = 1) so each run can be matched to its backend log lines.

Arms
  main      = backend image built from origin/main (without #82).
  candidate = backend image built from branch clarification-database (#82).

M1  Does the database vote contradict the chosen option?  (the defect, on main)
  Questions: questions.json, group "undefined" (fixed below, 8 questions). Candidate turn 1, 5 repeats each, records the options and each option's database.
  Only runs whose clarification offers options from >= 2 different databases count. For every offered option, replay on main WITHOUT a conversation: the
  original question with evidence 'The user defined "<term>" as: <label> (<description>)' (exactly what main builds from a click) and read the database
  main selects from its log ("Selected candidate database"). Report: share of (option) cases where main's database differs from the option's database.
  No gate: this measures how often the defect occurs. Before the change only 2 live trials existed (1 wrong).

M2  Does the pin work through the real path?  (wiring)
  Candidate only, authenticated conversation (header x-auto-ontology-user-id, conversation_id, supports_clarification = true). For every option offered in M1
  turn 1 (up to 40 options), answer by option_id and read "Question intent: ... target_db=" from the log.
  GATE: target_db equals the option's database in 100% of the answered options that carry a database, and the log line "Selected candidate database"
  does not appear for those runs. One miss fails the gate. (An earlier deployment passed all unit tests and failed this live.)

M3  Does the change make the engine ask more or less often?
  (a) Answerable, fully specified questions: dev_tools/evals/cases/chinook.json (20 cases) x 3 repeats, each arm, authenticated conversation, turn 1 only,
      count turns that end in a clarification instead of an answer.
      GATE: candidate asks <= main asks + 5 of the 60 runs.
  (b) Undefined terms: questions.json group "undefined" x 3 repeats, each arm, turn 1 only, count turns that end in a clarification.
      GATE: candidate asks >= main asks - 4 of the 24 runs.
  Noise: generation is not deterministic; one run is 1.7 points of (a) and 4.2 points of (b). Margins were chosen before any run and are not changed after.

M4  Label stability (report only, no gate)
  The question "What is our overall satisfaction score?" x 20 per arm, turn 1 only. Report the number of distinct sets of option labels per arm.

Not measured here (stated so it is not claimed): quality of the offered readings for a real company, multi-database questions, free-text answers, and the
  separate defect "a certified metric within the distance threshold suppresses the question" (seen once, E31).

Decision
  Merge only if M2 and both M3 gates pass. M1 and M4 are reported either way. If a gate fails, the result is recorded as is in docs/experiments.md.
  Questions are fixed in questions.json (sha256 recorded in questions.sha256 before the first run).

AMENDMENT 2026-11-16T15:47Z, BEFORE any measured run (only a one-question smoke test per arm was done to check the script):
  - M3a/M3b/M4 send no target_db, as the web app does (no database selected); the frozen Chinook file supplies the 20 questions only.
  - M1/M2 answer ONE option per turn-1 run, chosen round-robin by repetition (option index = repetition mod number of options), so 8 questions x 5
    repetitions give up to 40 answered options, each from a fresh conversation (a clarification can be answered once).
  - The candidate backend is the stack's current image (branch clarification-database); the main backend is image auto-ontology:main-eval built from
    origin/main 0b326100 (checked: contains the tile fix, not the option database), on port 3011. Test user: eval-clarification (deleted afterwards).
  - Script: probe.py, sha256 recorded in probe.sha256.

AMENDMENT 2026-11-16T16:26Z, BEFORE any M1 or M2 run (M3 was still running; its probe process had already loaded the earlier script and is unchanged):
  - To cut the duration of M1 and M2 (measured: a full answer takes a median 45 s, so about 100 s per run, about 70 minutes for 40 runs), the probe closes the
    stream as soon as the backend log shows "Retrieved N ColumnAttributes", which comes right after the database is pinned or voted. M1 and M2 read only
    that database from the log, so what is measured is unchanged; the SQL, its execution and the charts are no longer waited for. Criteria are unchanged.
  - probe.sha256 re-recorded.
```

---

## Running it (new)

```bash
# M3a, M3b, M4: turn 1 only, one arm at a time, resumable (done keys are skipped).
# Arms are named `main` and `cand`: the report compares those two.
python -m dev_tools.evals conversation run m3 --arm cand --url http://localhost:3001 --out m3.jsonl
python -m dev_tools.evals conversation run m3 --arm main --url http://localhost:3011 --out m3.jsonl

# M1 and M2: strictly sequential, one answered option per run. Needs read access to
# `docker logs` of both backends and `docker exec` on the Postgres container
# (the stored options carry the databases; the client-facing event does not).
python -m dev_tools.evals conversation run m12 --cand-url http://localhost:3001     --cand-container auto-ontology --main-url http://localhost:3011     --main-container ao-main-eval --out m12.jsonl

python -m dev_tools.evals conversation report --m3 m3.jsonl --m12 m12.jsonl --out report.json
```

- **Authentication.** Requests carry `x-auto-ontology-user-id` (`--user`, default
  `eval-clarification`). When the backend sets `INTERNAL_API_TOKEN`, pass `--token`
  or set the variable; the token is sent as `x-internal-token` and is never
  written to a record or a report.
- **Questions.** `undefined` and `label_stability` come from
  `cases/conversation_clarification.json`; the answerable set of M3a is the
  question list of `cases/chinook.json`. The report records the hash of both.
- **Gates** are evaluated only on a complete set of runs (60 for M3a, 24 for M3b
  per arm, as preregistered); otherwise the report says `incomplete`.
- **Reading choices made in the port.** The text is silent on these, so they are
  stated rather than hidden:
  - The M2 gate counts the answered options of runs that offered options from at
    least two databases (as the original `report.py` did). The report also prints,
    as information only, the same check over every asked run that carries a
    database.
  - M1 counts only those answered options for which the main arm's log showed a
    selected database ("Selected candidate database"); a replay that logged none
    is not counted either way.
  - M4's "distinct sets of option labels" ignores option order (sorted labels) and
    counts only runs that asked.
  - `m3` runs three questions at a time (`--workers`, capped at 6, the harness
    limit); M1 and M2 are always sequential.
