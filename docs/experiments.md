<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Experiments log

A chronological lab notebook of every measurement and key engineering finding on
Lexis since the fork was cloned (2026-11-09) up to 2026-11-15. It is written so a
maintainer or reviewer can decide how far to trust each claim and, where
possible, repeat it.

## 1. Purpose and how to read

- Each entry says what question was asked, how it was set up, what came out, what
  statistics were applied, what the entry does **not** show, and where the raw
  data lives.
- **Tags** use the levels of [verification-status.md](./verification-status.md):
  `REAL-E2E` (real stack: real database, real model endpoint, through the path a
  user takes), `REAL-ENGINE` (real database engine, not the full stack), `FAKES`
  (unit tests with stubs), `UNVERIFIED`.
- **Manual run, not repeatable from the repository** means the run needed data
  or a stack that the repository does not contain (LiveSQLBench, the
  maintainer's local stack and model gateway). The procedure is in section 6; the
  reports are kept outside the repository.
- **Development vs held-out.** A question set used while looking at failures is a
  development set and is not evidence of generalisation. Held-out sets (Chinook,
  LiveSQLBench-Base-Lite) were frozen before the engine was measured on them.
  Each entry says which kind it is.
- Numbers come from the sources named in the entry: a pull request body (`#N`,
  repository `julienawonga/lexis`), a document in this repository, the score files
  of the maintainer's machine, or the maintainer's working notes. Where a number
  could not be checked against a primary source it is marked **unverified**.
- Times are UTC and approximate where the notes give only an hour.
- LiveSQLBench gold SQL, knowledge-base text, question text and expected rows are
  never reproduced here (the benchmark's authors asked for no redistribution).
  Only aggregate scores, counts, p-values and case ids appear.

## 2. Method summary

The full method is in [evaluation.md](./evaluation.md); only what a reader needs
to interpret the entries is repeated.

- **Scoring.** The harness compares the rows the generated SQL returned with
  expected rows, never SQL text. Each question runs several times (three by
  default for Pagila and Chinook; one for LiveSQLBench); a report's score is the
  share of runs passed, and a question counts as passed when most runs did.
- **Frozen sets.** `chinook.json` is frozen (hash checked by CI,
  `python -m dev_tools.integrity`). The LiveSQLBench case files were frozen
  (`sha256sum -c`) before any measurement. `pagila.json` is not frozen and is a
  development set.
- **Official vs clean metric** (LiveSQLBench). `lsb-score --mode official`
  transcribes the benchmark's SELECT metric as written; `--mode clean` is a more
  careful reading. On the frozen reports of entry E09 both modes gave the same
  answer on all 180 questions (`clean.txt` and `official.txt`: identical counts).
  All LiveSQLBench numbers below are `official` unless stated.
- **Paired test.** Two engines are compared question by question with the exact
  two-sided McNemar test on the discordant pairs, at alpha 0.05.
- **Noise band.** Two runs of the same generation code on the same 180 questions
  gave 49 and 56 correct (entry E13), so differences of about 4 points
  (7 questions of 180) are inside run-to-run noise.
- **Rules** (evaluation.md, "Rules for an honest measurement"): cases and scoring
  are fixed before measuring; no case is edited and no convention loosened after
  seeing a result; strict and tolerant scores are reported together; both sides
  use the same cases file; a change is not judged only on the questions that
  motivated it; the semantic index must be populated.

## 3. Chronological log

### E00 - Pagila reference answers (2026-11-09)

- **Question.** What are the true answers to the Pagila questions, so the chat
  can be graded?
- **Setup.** SQL run directly in Postgres on the committed fixture
  (`dev_tools/fixtures/sql/pagila.sql`: 599 customers, 1000 films, 599 rentals,
  599 payments). Source: maintainer note "pagila-ground-truth".
- **Result.** 13 reference answers, for example top spender Ruth Martinez 23.95,
  total revenue 2502.01, category with most films Sports (74), and the hard
  question "top category by revenue in store 2" = Drama 104.79 (by inventory
  store). Traps found: rentals only span 2022-05-24..28 while payments span
  2022-01..07; "store 2" is ambiguous (inventory store vs customer store).
- **Limits.** The gold SQL and the questions were written by the same author, so
  the answers are not independent. The user was asked to review ambiguous ones;
  there is no record in the sources that the Pagila answers were reviewed.
  Pagila is a development set.
- **Where.** `dev_tools/evals/cases/pagila.json`.

### E01 - First Pagila baseline, 79.5% (2026-11-10): invalid, corrected

- **Question.** What does the engine score on Pagila before any change?
- **Setup.** Harness of PR #10, 13 questions x 3 runs.
- **Result.** 79.5% (PR #10 body, "Baseline recorded 2026-11-10 before the SQL
  guard and row limit").
- **What was wrong.** (1) The semantic index was **empty** (entry E02), so the run
  measured the raw schema, not the ontology (register row "Evaluation
  baselines"). (2) The maintainer notes record that the grader had been loosened
  after seeing failures (`allow_missing_columns`; "64.1% -> 79.5% with no engine
  change") and one question reworded to avoid ties. The figures 64.1% and the
  loosening come from the notes only (**unverified** against a report; the
  report was not kept).
- **Correction.** The user objected that the test was being fitted to the
  result. Rules 1, 2 and 5 of evaluation.md came from this. The cases were made
  strict again in PR #15 (four cases that tolerated a missing column were
  restored, declared before measuring) and the run now refuses an empty index.
  **Never compare against the 79.5% baseline.**
- **Where.** Register row "Evaluation baselines"; reports not committed.

### E02 - The semantic index was empty (2026-11-10)

- **Question.** Why did chat answer from the raw schema?
- **Finding.** `vdb.semantic_layer` held no rows: the semantic embedder built its
  parameters by hand and ignored `EMBED_EXTRA_FIELDS` / `EMBED_DIMENSIONS`, so the
  gateway rejected every row (`embed_all_semantic_nodes: 0/80 rows had
  embeddings`), while compilation was still recorded as `succeeded` (21 times).
  Every chat question retrieved 0 candidates.
- **Fix.** PR #11 (both call sites use `get_embed_params()`), PR #18 (a compile
  that leaves rows out is recorded as failed; `POST
  /api/semantic-compilation/reindex`; per-database `expected/indexed/missing`;
  WARNING on empty retrieval), PR #29 (eval pre-flight refuses an empty index).
- **Verification.** Reproduced against the live gateway with a dry run (PR #11).
  After the fix the status read 80 expected, 80 indexed, 0 missing on the running
  stack (register, `REAL-E2E`). The reindex route itself was only tested with
  fakes (`FAKES`).

### E03 - Pagila: junction far-side table and ranking projection, 61.5% to 94.9% (2026-11-10)

- **Question.** Do PR #13 (include the label table on the far side of a kept
  junction) and PR #15 (return the ranked value with the item) improve answers?
- **Setup.** Pagila, 13 questions x 3 runs, strict scoring, semantic index
  populated, same cases file on both sides, `main` against the candidate with
  both changes (PR #15 body).
- **Result.** 61.5% to 94.9%; harness verdict ACCEPT; 5 questions improved, 0
  regressed. One question still fails: top category by revenue in store 2 (1 run
  in 3).
- **Limits.** Both changes were written from these very questions: this is a
  **development** result and measures how well the changes fit Pagila. The notes
  also quote a different pre-change figure ("56.4% strict / 74.4% tolerant");
  the two figures were measured at different times and are not reconciled here
  (**unverified**). A reviewer should treat 61.5% as the figure of record
  (PR #15, docs/evaluation.md). E08 and E09 later showed the gain did not carry
  over.
- **Where.** `dev_tools/evals/cases/pagila.json`; report label
  `candidate-junction+projection` (not committed). Tag `REAL-E2E`.

### E04 - Postgres foreign-key extraction lost keys (2026-11-10)

- **Question.** Does the catalog hold the real FKs of Pagila?
- **Finding.** On Pagila `payment` has its three FKs only on its seven
  partitions, so the catalog held 0 keys touching `payment` and the Payment Term
  was isolated. Three more defects: a 2-column FK produced 4 rows; constraint
  names are unique per table, not per schema; and (found by CI) cross-schema FKs
  such as `analytics.film_performance -> public.film` were dropped.
- **Result.** After PR #16: 21 foreign keys instead of 36 rows, including
  `payment -> customer`, `rental`, `staff`; `payment` reports its primary key
  `(payment_date, payment_id)`.
- **Limits.** Postgres 17 only. A catalog ingested before the fix keeps the old
  keys until re-ingested; the running catalog was not re-ingested at the time.
  The notes judge the effect on answers small (the model infers joins from
  column names); the effect was not measured.
- **Where.** `auto_ontology/connectors/tests/test_postgres_keys.py` (live Postgres
  tests; `REAL-ENGINE`).

### E05 - Value matching probes and the value index (2026-11-10 to 2026-11-11)

- **Question.** Does the chat find stored values when the user types them
  differently?
- **Finding (2026-11-10).** "customers from the USA" returned 0 (stored value
  "United States", truth 36); "customers in Indai" returned 0 (truth 60). Case
  differences already worked (pg-13, mary smith, drama). Setting the opt-in
  `DB_PROBE_PROACTIVE` changed nothing, because the literal check only proposes
  values for columns under 20 distinct values (countries 109, cities 599).
  Measured on a throwaway backend (PR #25 body).
- **Change.** PR #25: opt-in value index, lookup, generic ISO alias table
  (all 249 countries and US state codes).
- **Live probe (2026-11-11, stack with the value index built for Pagila).**
  "USA" 36, "US" 36 (before 0), "pg-13" 223, "Norway" 0 (not corrected), "Indai"
  **failed** (anchor "India" found, generated SQL nonsense, no rows after 227 s)
  (register row; PR #25 and notes).
- **Privacy incident.** The first real index build for Pagila (5,954 values, 19
  columns) wrongly included customer e-mails, phones, names, addresses and
  `staff.password` because PII detection was off. 3,847 rows were deleted by hand;
  name and value-shape rules were added (PR #30). 2,107 non-personal values
  remained. A personal value under an ordinary column name with ordinary-looking
  values would still not be detected.
- **Limits.** The five questions are the ones the feature was designed from, so
  this is **not** evidence of generalisation. A held-out set,
  `dev_tools/evals/cases/chinook_values.json`, exists and has never been run.
  Tag `REAL-E2E` for the probe, manual, not repeatable from the repository.

### E06 - Business term "VIP customer" (2026-11-11)

- **Question.** Is a defined business term (a manual SQL attribute) used by the
  chat?
- **Setup.** Pagila, attribute created through the API, questions sent with
  `target_db=pagila`, attribute deleted afterwards (gone from the table and the
  vector index).
- **Result.** First probe: used for "Which customers are VIP?" (correct), ignored
  for "How many VIP customers do we have?" (599, all customers). Without the
  definition the engine invented a different threshold each time (143, then 382;
  truth with a threshold of 15 is 22). Re-run at 09:44-09:46: 22, 22, 22 (3 of 3
  correct, attribute used); the 599 was **not reproduced**.
- **Isolated check.** A hand-built two-table context with the attribute: the
  generation agent used it 12 of 12 times (count 22) whatever the subtype, so
  generation is not the cause. No code fix was justified; the cause of the first
  599 is unknown.
- **Limits.** Small sample (3 and 12 runs), development question. Register row
  "Business definition used by the chat" (`REAL-E2E`, manual). The separate row
  "Business metrics through SQL attributes" stays `UNVERIFIED`.

### E07 - The engine learned a test question (2026-11-11)

- **Finding.** Semantic compilation ran `suggest_sql_attributes`, which mines past
  query SQL and writes the SQL attributes an LLM picks into the shared ontology
  without review. Two appeared overnight ("Total Payment Amount", "Payment Amount
  At Least 15"); the second was the threshold typed into the VIP test question.
  That contaminates evaluations and writes shared knowledge without a human.
- **Action.** Both deleted (with the user's consent); PR #31 puts the stage behind
  `sql_attribute_suggestion_enabled`, off by default. A compilation on the running
  stack logged the stage as off and wrote no attribute (`REAL-E2E`).
- **Why it matters.** It is the concrete case behind the design rule that
  learned knowledge is a draft until a human certifies it
  ([design/self-improving-ontology.md](./design/self-improving-ontology.md)).

### E08 - Chinook, held-out, old code against current (2026-11-11 ~10:15-10:45)

- **Question.** After the Pagila work, does the engine still hold on a database it
  was not tuned on, and did the hardening regress anything?
- **Setup.** `dev_tools/evals/cases/chinook.json`, 20 questions, frozen before
  measuring, 3 runs each. Chinook loaded into the stack's Postgres (11 tables, 64
  columns; compiled, index 63/63). Arms: `main` at d92eb4e7 and the pre-hardening
  image at 81f02eb2, run as a temporary side container (`--allow-empty-index`
  because the old image has no status route; its index was healthy).
- **Result.** `main` 100% (20/20); pre-hardening 70%. Harness verdict ACCEPT, 6
  improved, 0 regressed.
- **Reading.** All 6 baseline failures returned the right items and lacked only the
  value column, which is the ranking-projection rule (PR #15) that the Chinook
  cases require. Substantive accuracy is about 100% on both: the set separates
  presentation, not reasoning. It is too easy and too well known to models to
  judge accuracy.
- **Limits.** The 20 expected answers were re-checked against SQLite (20 of 20
  match) but a human has **not reviewed** them; watch `playlist_most_tracks` (two
  playlists share a name) and `best_customer`. The cases were written by the same
  author as the gold. Reports kept in the maintainer's session scratch directory,
  not committed. `REAL-E2E`, manual.

### E09 - LiveSQLBench-Base-Lite, held-out, old code against `main` (2026-11-11)

- **Question.** Did the hardening work (PRs #8-#19) make the engine more accurate
  on a real, held-out benchmark?
- **Setup.** 180 SELECT tasks, 18 PostgreSQL databases, 1 run each, knowledge-base
  entries sent as `evidence` (the benchmark's "oracle knowledge" setting), official
  metric, 90 management (CRUD) tasks skipped because the engine is read-only. Case
  files built by the maintainer's script from the benchmark's public questions
  and the ground truth supplied by the benchmark authors on request; frozen
  before any measurement (`cases.FROZEN.sha256`, `cases-oracle.FROZEN.sha256`,
  both verified 18/18 after the run). One official gold query (`archeology_7`)
  has a stray comma before `FROM`; it was removed and tagged. Five gold queries
  return nothing (`insider_1`, `vaccine_2`, `vaccine_7`, `vaccine_10`,
  `virtual_2`) and score 0 for every engine. Arms: `main` at d92eb4e7 and the
  image at 81f02eb2.
- **Result.** Baseline 54/180 (30.0%; simple 17/42, moderate 25/89, challenging
  12/49). `main` 49/180 (27.2%; 13/42, 26/89, 10/49). Discordant: 14 only the
  baseline, 9 only `main`; exact McNemar p = 0.4049 (`official.txt`).
- **Statistics.** Not significant. `clean` mode gave the same counts.
- **Detours and mistakes (kept on purpose).**
  1. A first pass **without** the knowledge base scored 0% for both engines on
     2 databases (alien, archeology): terms such as SNQI exist only in the KB, so
     it was uninformative and was stopped. It was redone in oracle setting.
  2. The harness comparison (4 significant figures, rounding boundary) marked
     correct answers wrong on this benchmark, so harness scores were discarded in
     favour of the official metric.
  3. A throwaway scorer reported `main` 47/180 (PR #32 body: p about 0.21,
     15 vs 8 discordant). It wrongly failed `crypto_9` and `museum_6`. The
     reviewed `lsb-score` (PR #33) and a literal transcription of the benchmark's
     code both give 49. PR #32 recorded 47; docs/evaluation.md now says 49 and
     explains the correction.
  4. Running 14 worker processes in parallel caused infrastructure failures (the
     backend could not get a database connection: main 23 questions, baseline 19,
     in under 5 seconds with no SQL). Exactly those were replayed under one rule
     for both engines (no SQL, under 5 s) and merged; the originals are kept in
     `reports-oracle/pre-replay/`.
  5. Interim reading at 110 paired questions was 37 vs 37; at 150, 44 vs 42. The
     final figures above are for all 180.
- **Conclusion.** The hardening made the engine safer and more reliable, not more
  accurate; the Pagila gain measured fit to Pagila (E03).
- **Limits.** Single run per question; the scorer is our transcription of the
  benchmark rule and was not compared with the benchmark's own harness on more
  than a few tasks (docs/evaluation.md says so). The comparison is between code
  versions with different engine behaviour, not an isolated single change.
- **Where.** Reports and scores in the maintainer's `livesqlbench/` directory,
  outside the repository: `reports-oracle/`, `pr33-check/fixed/official.txt`,
  `clean.txt`. Recorded in the repository by PR #32 and PR #33.

### E10 - Source-database connections: exhaustion and fix (2026-11-11)

- **Finding 1.** Each registered source database held about 4 idle Postgres
  connections (backend and ingestion pools). Twenty databases exhausted
  `max_connections=100` and blocked the whole stack. The local Postgres was raised
  to 400 as a workaround.
- **Finding 2.** Under load the backend failed instantly instead of queueing
  ("missing required 'connectors'", "couldn't get a connection after 30 sec"); an
  unreadable connection store was returned as an empty connector list.
- **Fix.** PR #34: lazy pool with minimum 0 and idle close, per-source and
  per-process cap with waiting, `ConnectorLoadError` instead of `[]`.
- **Verification.** CI tests use a real PostgreSQL: 20 sources show 0 server-side
  connections before use, at most 2 per database under load, 0 after the idle
  timeout; 24 concurrent statements through a cap of 3 all succeed (`REAL-ENGINE`).
  On the stack with the image built from the PR branch (maintainer notes, 2026-11-11
  evening): idle source connections 60 to 0; 16 concurrent chats gave 0 connection
  errors, max 2 connections per database, but 15 of 16 produced no SQL because the
  test question needed system tables the catalog validator rejects (an engine
  limit, not the pool); 6 concurrent real LiveSQLBench questions gave 6/6 executed
  SQL, 0 errors, max 1 connection per database.
- **Limits.** The original 14-way failure mode was not replayed at full scale.

### E11 - The host crashed under 18 concurrent chats (2026-11-11 20:45)

- **Finding.** 18 concurrent chats plus another tool running produced a Windows
  blue screen (0x133, DPC_WATCHDOG_VIOLATION). Cause identified from the code: the
  backend started one full Python subprocess per concurrent conversation with no
  cap (`server/chat/worker.py`). The host has 13.6 GB and the Docker VM about 7 GB.
- **Rule adopted.** Load tests use at most 8 concurrent chats and never run
  alongside builds.
- **Fix.** PR #35 (`CHAT_MAX_CONCURRENT`, default 4; wait up to `CHAT_WAIT_S`, then
  503 with `Retry-After`). Live test before merge (notes): 10 questions at cap 4,
  merged only after "max in_use <= 4, worker processes <= 6, no crash, no 503
  storm"; the measured values are not given in the notes (**unverified**).
  Register row is `FAKES` for the unit tests.

### E12 - Gateway 429 storm from a 54-question burst (2026-11-11 ~23:15)

- **Finding.** On a temporary cloud VM (since deleted) 12 concurrent chats were
  fine; 54 concurrent made the model gateway's edge return HTML 429 and then block
  the VM's IP. The engine amplified the burst: embeddings 32-wide per call, SDK
  retries times application retries times a fallback model. A second finding:
  cancelled conversations kept calling the model after the client disconnected
  (about 100 gateway calls per 20 s after the eval client was killed; the backend
  had to be restarted).
- **Fix.** PR #38 (backoff with jitter and `Retry-After`, no nested retries,
  process-wide in-flight cap 8, embedding concurrency 4); PR #40 (disconnect
  cancels stateless runs, conversation runs after 60 s without a reader, any run
  after `CHAT_MAX_RUN_S` = 300 s; eval runner waits out 503).
- **Limits.** Both are `FAKES` in the register: the 429 burst and the 100-calls
  incident were not reproduced; the root cause of the latter is from code reading
  plus fake-based tests (PR #40 body). Rule: at most about 12 concurrent chats per
  IP on this gateway. The 300 s limit appears later as the error in the language
  runs (E20).

### E13 - Noise: the same engine twice (2026-11-12 ~00:30-03:40)

- **Question.** How much does one 180-question run vary on its own?
- **Setup.** `main` again, label `main-02d166c0-noise`, same frozen oracle cases,
  1 run, 2 workers, official metric. Script `noise_run.sh`.
- **Result.** 56/180 (31.1%; simple 17/42, moderate 28/89, challenging 11/49)
  against the first run's 49/180. Discordant 13 only the new run, 6 only the old;
  exact McNemar p = 0.1671. Against the baseline 81f02eb2 (54/180): 10 vs 8,
  p = 0.8145 (`noise.txt`).
- **Conclusion.** Run-to-run noise is about 4 points (7 questions). The 54-vs-49
  gap of E09 is noise: no regression is shown, no improvement either.
- **Limits.** The two `main` runs are different commits (d92eb4e7 and 02d166c0,
  which adds PRs #32-#34: tooling and connection handling). The notes state that
  generation logic did not change between them; this was not independently
  diffed for this document (**unverified**). One run per question.
- **Where.** `reports-noise/`, `pr33-check/fixed/noise.txt` (outside the repo).

### E14 - Arm A: no knowledge anywhere (2026-11-12, finished 02:47)

- **Question.** What does the engine score on LiveSQLBench with no business
  knowledge at all?
- **Setup.** Frozen `cases/` (no evidence), 180 tasks, 1 run, 2 workers, label
  `main-dfbea133-nokb`. Script `nokb_run.sh`. First pass finished 13/18 databases;
  5 failed because `uv` could not fetch `httpx` from PyPI (DNS error, not an
  engine failure) and were run again.
- **Result.** 3/180 (1.7%; simple 3/42, moderate 0/89, challenging 0/49). Against
  arm B (first run, 49/180): both 2, only A 1, only B 47, neither 130; exact
  McNemar p < 1e-4 (`armA-vs-B.txt`).
- **Limits.** Arm B was measured on `cases-oracle/` and arm A on `cases/`; the
  scorer prints a hash-mismatch warning for that (the files differ only by the
  `evidence` field) and the comparison was run with
  `--allow-cases-mismatch`. The two arms are different commits (d92eb4e7,
  dfbea133).

### E15 - Arm C: knowledge loaded as Terms, definitions not given to generation (2026-11-12, finished 06:25)

- **Question.** Does knowledge stored in the ontology help as much as knowledge
  pasted into the question?
- **Setup.** `lsb-kb` (PR #41) loaded each database's KB entries as uncertified
  Terms for the 18 LiveSQLBench databases only (dry run: 1,062 Terms would be
  created, 0 conflicts; about 1,054 applied, the rest skipped because Term names
  are unique across databases; counts from the notes, **unverified** against the
  tool's log). Backups of each database's model were exported first; Pagila and
  Chinook were untouched (index counts 80 and 63 checked). Frozen `cases/` (no
  evidence), 1 run, 4 workers, label `main-2467fe3b-kbterms`. Script
  `kbterms_run.sh`. Run only after arm A finished, to avoid contamination.
- **Result.** 4/180 (2.2%; simple 3/42, moderate 1/89, challenging 0/49), the
  same as arm A (both 2, only C 2, only A 1; p = 1.0), and far below arm B
  (only C 3, only B 48; p < 1e-4) (`armC.txt`).
- **Root cause (from code).** Retrieval kept one "subject Term" and used it only to
  add its linked tables to the prompt; Term descriptions and definitions never
  reached the SQL generator, which consumed only column attributes and SQL
  attributes. The ontology's business definitions were invisible to generation.
- **Side finding.** One Solar question looped through reconstruct/validate for
  about 50 minutes because the deployed engine had no run-time limit yet (PR #40
  adds `CHAT_MAX_RUN_S`).
- **Limits.** The KB entries were loaded through the whole-model import route
  (no Term create/delete API existed then, which led to PR #45). Arm C also
  changes which tables are offered, which arm B does not.

### E16 - Arm C': Term definitions given to generation (2026-11-12 ~07:00-10:10)

- **Question.** If the relevant Terms' definitions reach SQL generation, does the
  ontology carry the knowledge as well as pasted evidence?
- **Setup.** PR #42 (flag `TERM_DEFINITIONS_IN_GENERATION`, built from commit
  686adb04, deployed as a separate image with the flag on; 7-9 Terms per question
  injected). Same Terms and frozen `cases/` as arm C, 1 run, 4 workers, label
  `pr42-686adb04-cprime`. Script `cprime_run.sh`, override file
  `cprime-override.yml`.
- **Interim (07 of 18 databases, 70 questions).** C' 25/70 (35.7%) against C 2/70,
  B 26/70, B-noise 25/70; C' vs C 24 to 1, p < 1e-4; C' vs B 5 vs 6, p = 1.0
  (notes; **unverified** against a file, the interim output was not kept).
- **Final (180).** C' 55/180 (30.6%; simple 20/42, moderate 26/89, challenging
  9/49). C' vs C: both 3, only C' 52, only C 1, p < 1e-4. C' vs B (first run, 49):
  both 34, only C' 21, only B 15, p = 0.4050. C' vs B-noise (56): only C' 15, only
  B-noise 16, p = 1.0 (`armCprime.txt`).
- **Conclusion.** Knowledge is the lever (1.7% to about 30%). Once the definitions
  reach generation, the ontology performs like hand-supplied evidence (no
  significant difference either way). `TERM_DEFINITIONS_IN_GENERATION` is on by
  default since this measurement (PR #42 as merged).
- **Limits.** The change was designed after looking at why arm C failed on this
  same benchmark, so LiveSQLBench is **not held-out for this change** (PR #42
  says so). One run per question. The benchmark's KB is curated and complete; a
  customer's glossary will be neither. This tests loading and use of knowledge,
  not extracting it from documents (see section 5).
- **Where.** `reports-cprime/`, `pr33-check/fixed/armCprime.txt`; recorded in
  docs/evaluation.md ("Knowledge as Terms") and the register.

### E17 - Startup cost of re-ingestion (2026-11-12)

- **Finding.** Every container restart re-ran full ingestion for every registered
  database; one restart meant 20 databases and about 3,000 embedding rows, all paid
  gateway calls, to reproduce a stored result (PR #36 body; the figure is the PR
  author's, not re-counted).
- **Fix.** PR #36 skips databases whose catalog and embeddings are both present.
  Merged `FAKES`: the decision is unit-tested with stubs; the skip was observed
  once on the running stack after the next restart (notes: "startup pass: 0
  ingested, 20 skipped, 0 embeds"), but the register row still reads `FAKES`
  (the notes and the register differ; the register is the conservative record).

### E18 - Knowledge-use trace on real answers (2026-11-12 ~12:00)

- **Question.** Can an answer report which knowledge it was offered and used?
- **Setup.** PR #46; live check on the `alien_2` question of the frozen set.
- **Result.** Two live runs of the same question (`alien_2`), each read from the
  backend's `Knowledge trace:` log line and the streamed answer. First heuristic
  (commit c11f1bc6): offered 14, used 1, undecided 12; the SQL visibly applied
  the TOLS and BFR formulas, but KB definitions name columns in prose
  (CamelCase) and column attributes were matched by label. Final heuristic
  (commit 840af9e2, merged): offered 11, used 6, undecided 3, with TOLS matched
  on `techsigprob`, `natsrcprob`, `sigunique`, `anomscore`, both BFR Terms on
  `bwhz`, `centerfreqmhz`, and the Anomaly Score and Bandwidth column attributes
  true; the 3 undecided are general Terms whose definitions name no column. The
  offered count differs between runs because retrieval differs run to run.
- **Limits.** `used` is a text heuristic on the final SQL, not a causal measure;
  it has not been compared with human judgement.

### E19 - A flaky connection-cap test (2026-11-12)

- **Finding.** `test_connections_are_bounded_while_used_and_released_after` failed
  once in CI (`assert 3 <= 2`). PR #47 body: 85 local loops (40 at test settings,
  20 forcing constant pool shrink, 25 with 24 CPU-burner processes on 12 cores)
  never reproduced it: 0 server-side peaks above 2, 0 client-side peaks above 2.
  The root cause (a closing backend still listed in `pg_stat_activity`) is
  **inferred from reading psycopg_pool, not observed**. The test now counts only
  `active` backends. No production code changed.

### E20 - Questions in French: does translating them help? (2026-11-12 ~13:30 onward)

- **Question.** Does a French question work as well as an English one on an
  English ontology, and does translating it first help? (Design decision 10 in
  [design/self-improving-ontology.md](./design/self-improving-ontology.md).)
- **Setup.** Chinook, target database `chinook`, 3 runs per question (1 for `en-v2`), 4 workers. English cases: the frozen `chinook.json` (cases hash
  4fbe2a00...). French cases: 20 French renderings `chinook_fr.json` (cases hash
  e628cfda...), reviewed by the user before any result; the file ships with
  PR #49 (open when this was written; not on `main`). Backend images built from
  the PR #49 branch; the first version had an on/off flag, the reworked version
  chooses the ontology language per database (`en` by default) and translates
  only when the question language differs. Scripts `lang_eval.sh`, `lang2_eval.sh`.
- **Results (raw runs verified from the JSON reports).**

| Arm | Questions passed (majority) | Runs passed |
|---|---|---|
| EN, translation off (`en-off`) | 20/20 | 60/60 |
| FR, translation off (`fr-off`) | 17/20 | 53/60 |
| FR, translation on (`fr-on`) | 20/20 | 59/60 |
| EN, translation on (`en-on`) | 20/20 | 59/60 |
| FR, reworked version (`fr-v2`) | 20/20 | 59/60 |
| EN, reworked version, 1 run (`en-v2`) | 18/20 | 18/20 |
| EN, reworked version, 3 runs (`en-v2b`) | 20/20 | 58/60 |

  Failures. `fr-off`: `acdc_tracks` wrong values 3 of 3; `best_customer` two runs
  and `rock_tracks` two runs cancelled at the 300 s run limit. `fr-on`: one
  `top5_countries_sales` run hit the 300 s limit. `fr-v2`: one `best_customer` run
  hit the limit. `en-on`: one `best_customer` run hit the limit. `en-v2`:
  `best_customer` hit the limit and `rock_tracks` returned wrong values (single
  run, 18/20). The 3-run rerun `en-v2b` (same cases hash) passed 20/20 questions,
  58/60 runs: one `best_customer` run hit the 300 s limit and one `acdc_tracks`
  run returned wrong values.
- **Statistics.** FR off vs FR on by majority: 3 questions only with translation,
  0 only without; exact two-sided McNemar p = 0.25 (computed for this document
  from those counts; not significant at 20 questions). The en-off to en-on
  difference (60 vs 59 runs) is one run and is noise.
- **Conclusion (cautious).** Without translation, a French question lost 3 of 20
  questions on an English ontology; with translation it matched English. English
  did not regress under the reworked version: the single-run 18/20 (`en-v2`) was
  run-to-run noise, as the 3-run rerun shows. `best_customer` hits the 300 s limit
  intermittently in every arm, English included, so that timeout is not caused by
  language; it is an open engine issue. The sample is 20 questions on one well-known
  database; the effect is suggestive, not established.
- **Limits.** The failure causes of `acdc_tracks` and `rock_tracks` were not
  investigated. Every error is a cancellation at the 300 s run limit of PR #40;
  whether load or reasoning caused the slow runs was not examined. `git_sha` is not recorded in these
  reports. The reworked arm used an image built from a worktree, not a released
  commit. Chinook is a set the engine does well on (E08).
- **Where.** `lexis-evals/lang/*.json` (maintainer machine); PR #49.

### E21 - Terms API on the running stack (2026-11-12)

- **Question.** Do the new create/rename/delete routes for Terms work against the
  real stack?
- **Result.** PR #45 then PR #48: `POST /api/terms` on Pagila (linked by name to
  2 tables, `embedded: true`, row present in `vdb.semantic_layer`), `PATCH` of the
  name re-embedded the row, `DELETE` removed the row and the Term, a second
  `DELETE` returned 404, one audit log line per action.
- **Limits.** A functional probe, not a measurement. Done without the web app's
  user header, so the 403 permission path was not exercised, and nothing went
  through the web app. `REAL-E2E`, manual.

### E22 - "Who is our best customer?" ran in a loop for up to 300 s (2026-11-12 ~19:00-19:42)

- **Question.** Why did one Chinook question sometimes take 45 to 303 s, and does
  the fix remove it?
- **Finding.** Evidence grounding saw only the `Customer` table, so its wording
  ("allowed mapping targets") read as forbidding `Invoice` columns. The SQL
  validator and the reconstruction step then alternated between two answers
  (A, B, A) until the 300 s cut.
- **Fix.** PR #52: the evidence wording says it does not forbid other schema
  columns, discovered tables are declared legitimate, and an oscillation guard
  stops at the third rejection and returns the best SQL with a caveat note.
- **Result (maintainer's working notes, reports in `HomeLab/lexis-evals/deadlock/`).**
  The question asked 10 times: `main` took 45 to 303 s (6 slow, 1 cut at 300 s,
  9 of 10 correct); with the fix 49 to 62 s (0 slow, 10 of 10 correct, the same
  customer and total). The oscillation guard never fired, so the wording change
  alone removed the loop. Chinook 20x3 with the fix: 60/60. Pagila 13x3: 39/39.
- **Limits.** Ten runs of one question. Pagila is a development set. Whether the
  new wording changes the 180 LiveSQLBench questions (where the evidence wording
  was the stated risk) was planned and is **not recorded here**.
  `REAL-E2E`, manual.

### E23 - Grouping Terms into business domains with a real model (2026-11-14)

- **Question.** Does an LLM grouping of a database's Terms give domains a person
  would accept, on databases of different sizes?
- **Setup.** The domain map feature (PR #63): Terms grouped into named domains by
  the gateway's chat model, with a Louvain-community fallback. Run by hand on four
  databases of the local stack.
- **Result.** Chinook 2 domains, Pagila 4, a cross-database view 6, a 95-Term
  database 6. The groups read as sensible to the person running it. **A first
  attempt on the 95-Term database failed:** the model's reply was empty, because
  `max_tokens` of 4000 was consumed by the model's reasoning before any output;
  raising it to 16000 fixed it.
- **Limits.** **Not scored.** There is no reference grouping and nobody has
  graded the business names, which is a human judgement. Four databases, one run
  each. It is a presentation feature: it does not change SQL generation, so no
  accuracy claim follows. `REAL-E2E`, manual.

### E24 - Semantic contract: independent review, and a measurement that was stopped (2026-11-15)

- **Question.** Is the semantic contract (PR #62, written by two coding agents)
  correct, and does letting certified objects reach the planner change accuracy?
- **Review.** A line-by-line review of the branch found 10 findings. Two were
  confirmed by reading the code: a guard meant to prevent a duplicated prompt
  block compared against a header string the renderer never emits, and its unit
  test built its input by hand with the same wrong string, so it passed while the
  behaviour was broken; and a malformed environment value crashed every chat
  question. The others: real errors swallowed as "unknown database", one long
  definition emptying the whole block, an approval check made outside its
  transaction, repeated full catalog projections, a misleading conflict message,
  a stale skill text, an unrelated auth change. All were fixed with tests that
  fail on the old code (10 of the new tests fail on it).
- **CI.** The pull request was red for three reasons, all from files generated on
  Windows: a DAL signature snapshot holding memory addresses, a public OpenAPI
  spec holding Windows paths and carriage returns, and an unformatted migration.
  Generated artefacts are now produced on Linux only.
- **Measurement: no result, twice.** The planned gate (Chinook 20x3, flag off
  then flag on, same frozen cases) was started and stopped two times.
  **First attempt:** stopped at 22 of 60 questions of the flag-off run. Docker
  builds were running on the same machine and several questions hit the 300 s
  limit. **Second attempt, on an idle machine:** stopped at 35 of 60. 7 questions
  failed, all by the 300 s limit, none by a wrong answer, with a median of 112 s
  for the questions that passed. The backend log gave the cause: the isolated
  database's catalog had been ingested from the SQLite build of Chinook, so its
  tables carry the schema `main`, while the data lives in the Postgres schema
  `public`; the generated SQL failed with `relation "main.Invoice" does not
  exist` (42 times) and the repair loop ran to the limit. The web app's own
  tables were also missing in that database (hundreds of logged exceptions).
  The environment, not the code under test, produced those failures, so
  **no number from either attempt is reported.** The partial logs are kept
  outside the repository with a note on how to repeat the run: re-ingest
  Chinook from its Postgres copy so the schema is `public`, rebuild the index,
  recreate the certified concept (catalog ids change), then run flag off and
  flag on on an idle machine. Until an `ACCEPT`, the flag stays off and the
  branch stays a draft.
- **Limits.** The fixes to the transactional check and the error mapping are
  tested with fakes (`FAKES`); a real-Postgres run of the governance lifecycle was
  not repeated after them. Nothing is claimed about accuracy.

### E25 - Independent review of the business-domain map (2026-11-15)

- **Question.** Does the merged domain map (PR #63) hold up under a line-by-line
  review?
- **Finding.** Nine defects. Confirmed by reading the code: renaming a domain
  left its Terms marked as generated, so the next regeneration emptied it; the
  deterministic fallback was called with no links, so it could not cluster and a
  database of 30 or more Terms became one "Other" domain; table counts included
  tables of other databases; a whitespace-only name was stored; the error from
  creating the model client was swallowed. A separate review of the screen code
  found three more, each confirmed in the code: a generation result for a
  database the user had already left overwrote the current one, a failed load
  left a blank screen, and the rename form survived a change of domain.
- **Fixes.** PR #65, each with a test that fails on the old code. Two things went
  wrong on the way and are kept here on purpose: a performance regression
  introduced by a delegated fix (an isolated group re-scanned every edge for
  every candidate; rewritten to aggregate weights once per round, 2000 Terms in
  under a second), and a stricter rule on moving Terms between domains that
  passed its fake-database tests but failed the real-Postgres integration test
  in CI, so it was removed rather than shipped unverified.
- **Limits.** The data fixes are tested with fakes locally and by the Postgres
  suite in CI; nobody has looked at the screen. Not fixed: no index on
  `term_domain`, no uniqueness on a domain name per database (two simultaneous
  renames can collide), queries repeated by the map builder, and a Term can
  still be moved into a domain of another database through the API.
  `FAKES` plus CI.

### E26 - Repairing a filter that ignores a linked value, PR #58 (2026-11-13 and 2026-11-15)

- **Question.** Does the value-anchor repair of PR #58 (a string literal equal to a
  linked anchor's phrase whose stored value differs routes once to reconstruction;
  a single row of 0 or NULL runs the literal check) raise accuracy on value
  questions without regressing others?
- **First measurement (2026-11-13, combined build of #57, #58 and #59, reports in
  `HomeLab/lexis-evals/combo/`).** `chinook_values.json` 14x3: 83.3% to 95.2%
  (+11.9%), 6 questions improved, 1 regressed ("Jazz tracks that are mpeg audio",
  100% to 67%). `chinook.json` 20x3: 96.7% to 98.3%, 1 improved, 1 regressed.
  Harness verdict `REJECT` because of the regressions. It was a combined build, so
  the effect of #58 alone was not isolated, and the notebook did not record it.
- **Second measurement (2026-11-15, `main` against `main` plus #58 alone, same
  database, same frozen cases, same harness, 4 workers, runs alternated,
  reports in `HomeLab/lexis-evals/cand58/`).** `chinook_values.json` 14x3: `main`
  100.0%, candidate 97.6% (-2.4%; one question, the same "Jazz mpeg" one, went
  from 3/3 to 2/3). `chinook.json` 20x3: both 98.3%; "playlist with the most
  tracks" improved (2/3 to 3/3) and "five best-selling artists by revenue"
  regressed (3/3 to 2/3). Verdict `REJECT` on both.
- **Reading.** The problem #58 targets (three misspelling questions failing one
  run in three) was **not reproduced**: `main` was already at 100% on this set
  two days later. The cause of the difference from the 83.3% baseline of
  2026-11-13 was **not investigated** (the value index state and the merged
  changes in between are candidates). One question flipping in a set of 14 or 20,
  in both directions on both sides, is the noise level of this bench; #58 shows no
  effect above it.
- **Decision.** Not merged, PR closed with the branch kept. It adds an engine
  path with no measured benefit on current `main`.
- **Limits.** Chinook is small and well known to the model, so a null result here
  does not prove the repair is useless on messier data; there is no held-out
  messy-value set. Three repeats per question; no confidence interval. One
  machine. `REAL-E2E`, manual.

### E27 - What the engine does when the database cannot answer (2026-11-16)

- **Question.** When a question cannot be answered from the schema, does the engine
  say so, or does it return a result for something else?
- **Setup.** Chinook, through the chat API as the web app calls it, no
  conversation. Two small sets written by hand before any answer was read: a
  development set (8 unanswerable questions, for example salary of each employee,
  revenue per store, returns last month, units in stock, profit margin, and the
  French "Combien a rapporté chaque boutique ? CA") with 4 controls that do have
  an answer, then a held-out set (6 unanswerable, 3 controls) written after
  the first and frozen before its run. Two runs per question. Reports and the
  frozen scripts are kept outside the repository.
- **Result, 28 runs of unanswerable questions on `main` (no signal yet).** Clean
  refusal ("SQL can't be constructed from the data"): 4 (14%), all on two
  questions of the first set. A result for a different question: 21 (75%), of
  which 11 carried the engine's "not fully validated" note and 10 did not (only
  the model's own prose said the data lacked something). Timeout at 300 s: 3.
  Controls: all 14 completed with a sensible query and no warning.
- **What the substitutions looked like.** A `Salary` column filled with NULL or
  with the text "Unavailable"; a column named `units_in_stock` that counts
  tracks; total revenue returned for revenue per store; an estimated "shipping
  cost" computed as a remainder; and "CA" read as the US state California
  rather than chiffre d'affaires, in both runs of the French question.
- **Consequence.** The visible warning added in #73 only covers the runs that carry
  the validation note (11 of 21). A structured signal is needed. A branch adds two
  optional fields to the SQL generation output (`answers_question`: fully, partly
  or no; `limitation`: one sentence), passes them through as `answer_limitation`,
  and shows a notice. It is **not merged**.
- **Gate for the branch, frozen before it ran (file dated 2026-11-16).** At
  least 80% of the completed unanswerable runs flagged or refused; no flag on any
  of the 14 control runs; no Chinook regression; and, added before any candidate
  run because the change touches every generation, no significant regression on
  the 180 LiveSQLBench tasks (official metric, McNemar) and a flag rate under 10%
  on those answerable tasks.
- **Status (candidate measured on criteria 1, 2 and 3 only).** On the 28 unanswerable
  runs the candidate flagged 22 and refused 2 (24 of 24 completed runs, 4 timeouts;
  `main`: 4 refusals, 21 substitutions, 3 timeouts). No flag on the 14 control runs.
  Chinook 20x3, `main` against the candidate, same cases: 98.3% for both, 0 improved,
  0 regressed, verdict ACCEPT (Chinook is at its ceiling, so this cannot show a small
  loss). The first report script summed the refusals of both engines in criterion 1
  (ratio 1.167); fixed to count the candidate's own (24/24). Criterion 5 (flag rate
  under 10% on answerable tasks, the real false-alarm check) was run on 4 of the 18
  LiveSQLBench databases (solar, alien, credit, museum: 40 tasks, frozen oracle
  cases, one run each, candidate against `main` alternating by database):
  **21 of 40 runs carried a limitation (52%, 20 "partly", 1 "no")**. That fails the
  10% ceiling by a wide margin, so criterion 5 FAILS and the signal is **not merged**.
  The 18-database run and criterion 4 (McNemar) were not run, as the result cannot
  change the verdict. On those 40 tasks the harness pass count was 7 for `main` and 6
  for the candidate (a tolerant count, not the official metric, and not significant).
  Reading: on real answerable questions the model's own "partly" is a near coin flip,
  so the field cannot be used as an alarm. A different design is needed (for example
  a check against the schema made by code, not the model's self-assessment). The candidate image
  was built on a `main` a little older (only the "Understood" sentence differs).
- **Limits.** Two small hand-made sets on a database the model knows well; the
  development set shaped the design, so only the held-out set counts as unseen;
  two runs per question; the classification is read by the maintainer's
  assistant, not by an independent reviewer. `REAL-E2E`, manual.

### E28 - Does the chat apply a certified business metric? (2026-11-16, change not merged)

- **Question.** README step 4 (business metrics): when a person defines and
  certifies a metric, does the chat build its SQL from that definition?
- **Setup.** Chinook on the running stack. A Term "Gross revenue" and a certified
  SqlAttribute whose SQL sums `UnitPrice * Quantity` over invoice lines of tracks
  whose `MediaTypeId <> 3` (music only), both created through the API. The
  definition was chosen to give a number that differs from the naive query:
  2107.71 with the definition, 2328.60 without. Question: "What is our gross
  revenue?". Nothing else was changed; the test Term and metric were deleted
  afterwards so they do not enter later measurements.
- **Result 1, `main` as it was.** The metric was retrieved and shown to the model
  in 2 of 2 runs, but the answer was 2328.60 (naive) both times. Cause found in the
  logs: the table-relevance filter (an LLM call) removed `Track` and `InvoiceLine`,
  and only `InvoiceLine` was put back by the deterministic reconciliation. The
  model then wrote that it could not apply the music-only filter because `Track`
  was not in the schema (in one run it said so in its prose, in the other it did
  not).
- **A flaw in my own setup.** My first Term description said "all invoice lines",
  which contradicts the metric; a definition that conflicts with the Term text is
  followed by the model. Corrected description: music tracks only.
- **Change tried (PR #78, closed without merge).** The tables read by a
  **certified** SqlAttribute were put back by code after the relevance filter
  (same mechanism as the bridge tables). With it and the corrected description,
  3 of 3 runs gave 2107.71 and the logs show `Track` force-included.
- **Control, without the change but with the corrected description.** Also 3 of 3
  gave 2107.71, so the filter kept `Track` by itself. The two failing runs came
  before the description was corrected, so they may have been caused by my own
  setup and not by the filter. **Not shown to be needed, so not merged.** Reopen
  with a reproducible case that has a consistent description and several runs.
- **Effect on the existing evaluations.** The change only acts when a certified
  SqlAttribute is retrieved for the question. Not run: no Chinook or LiveSQLBench
  measurement was repeated for it.
- **Limits.** One database, one metric, one question, three runs per arm, no
  independent review. `REAL-E2E` for the retrieval and the answers, `FAKES` for
  the unit test.

### E29 - Could a rule on the SQL replace the model's self-assessment? (2026-11-16, exploration)

- **Question.** After E27 (the model's own "partly" fails the false-alarm ceiling),
  does a deterministic rule on the generated SQL catch substituted answers?
- **Setup.** No model call: the 42 recorded `main` runs of E27 (25 unanswerable
  runs that produced SQL, 14 controls). Rule: the SQL selects a typed `NULL` as a
  column, or a string literal such as "unavailable" as a value.
- **Result.** The rule fired on 9 of the 25 unanswerable runs (36%) and on none of
  the 14 controls. It misses the substitutions that are semantically wrong but
  syntactically ordinary (total revenue returned for revenue per store, a
  "remainder" computed as shipping cost, tracks counted as stock).
- **Limits.** The rule was written after reading these outputs, so 36% is an upper
  illustration, not a measurement; it has not been run on unseen questions or on the
  180 answerable LiveSQLBench tasks (its false-alarm rate there is unknown). A usable
  design would need a check of the question's entities against the schema, which is
  not built. `REAL` data, analysis only.

### E31 - Does a clarification choice decide the database? (2026-11-16, change not merged)

- **Question.** With no database selected, the clarification offers readings that
  live in different databases. Does choosing one of them decide which database
  answers, or does the later database vote override it?
- **Finding 1 (before the change).** The chosen option reached the engine only as
  text in the evidence. The vote (`_select_candidate_database`) then picked the
  database alone. Live, same question twice on the stack: choosing a reading from
  `mental` gave `mental`; choosing a reading from `disaster` gave `virtual`, a
  database that holds a different satisfaction measure (aggregate distance 0.99,
  one entity covered). Two trials, one wrong: a real defect, not a frequency.
- **Change.** Each option keeps the database of the candidate it relies on (the
  model copies it from the tagged candidates; a name not among the candidates is
  dropped). Picking the option pins the answer to that database. Candidates are
  listed in a fixed order. The database never reaches the client.
- **Finding 2 (a wrong first fix).** The first deployment still failed live: the
  databases were present after validation (logged) but missing from the stored
  message, because the worker handed the server the client-facing event, which has
  no databases, and the server rebuilt the clarification from it. Unit tests with
  fakes did not catch it. Fixed by carrying the databases on an internal key that
  the server stores and removes before streaming.
- **Result after the fix (live, 15:10).** The same question, choosing the
  `disaster` reading: the stored options carried their databases, the run went
  with `target_db=disaster`, no database vote ran, and the SQL was anchored on the
  `disaster` column. One live trial.
- **Finding 3 (a separate defect, not fixed, on purpose).** A certified metric "VIP
  Customer" at distance 0.61 (skip threshold `definition_max_distance` = 0.62) made
  the detector skip the question for a satisfaction question, because both mention
  "customer". Seen once live. Distances of the best SqlAttribute hit (this one
  metric, Pagila), measured afterwards with embedding calls only: 5 questions about
  VIP customers (one in French) 0.38 to 0.46; 7 questions unrelated to it 0.55 to
  0.64, so the threshold sits inside the unrelated range (3 of the 7 are under it).
  Consequence: a clarification is missed and the engine answers as it did before the
  feature existed. It is not a wrong answer produced by the metric, so the severity
  is low. The definition is still shown to the model up to 0.75 and the model has a
  `covered_by_definition` field, so lowering the automatic skip (for example to
  0.50) would move the decision in the grey zone to the model; that is the likely
  design.
  - **Why it was not changed.** The only evidence is 12 questions, one metric, and
    questions seen before the number was chosen: a threshold fitted to the sample at
    hand. The index holds 2 metrics and no saved analysis, public benchmark
    databases only, and no real questions to validate on. A constant chosen this way
    would look measured without being so. A change needs a frozen set of related and
    unrelated questions written beforehand, ideally on real data, measured against
    `main`.
  - **Generalisation limit of everything in this entry.** All measurements here use
    public benchmark databases (Chinook as a regression guard, Pagila, the
    LiveSQLBench databases for the undefined terms). Frozen questions protect
    against adjusting after seeing results; they do not show the behaviour holds on
    a customer's data.
- **Measurement (2026-11-16, 15:47 to 16:57 UTC).** The frozen cases run stateless
  and can never reach the clarification path, so a purpose-built protocol was
  written and frozen before any run (`lexis-evals/clarification/PREREGISTERED.txt`,
  two amendments dated before the runs they concern, questions and script hashed).
  Arms: `main` (0b326100) against this branch, same stack, flag on, authenticated
  conversations, no database selected, turn 1 only for M3.
  - **M2, the pin through the real path (gate 100%): 25 of 25 pass.** Every
    answered option that carries a database ran with `target_db` equal to it and no
    database vote. It is true by construction, so it is a wiring check, not a
    quality measure; it is the check that an earlier deployment failed.
  - **M3a, answerable Chinook questions, candidate asks <= main + 5: PASS.**
    Candidate 6 of 60, main 7 of 60 (one timeout each side counted as not asked).
  - **M3b, undefined terms, candidate asks >= main - 4: PASS.** 15 of 24 on both.
  - **M1, how often main's vote contradicts the chosen option: 5 of 22 (23%).**
    Concentrated: 3 of the 5 are the single question "overall engagement level",
    so the 22 are not independent and 23% is not a stable rate.
  - **M4, label stability (report only): not improved.** Distinct label sets over 20
    runs: 14 on main, 12 on the candidate. The fixed candidate order did not make
    the offered readings stable; temperature is still free.
  - **A finding unrelated to the change.** On fully specified Chinook questions with
    no database selected, "How much did we sell in 2023?" and "What are our top 5
    countries by sales?" triggered a clarification in 3 of 3 runs on both arms
    (14% of all 60 runs ask). "Sales" is arguably ambiguous, but it shows the
    engine asks about answerable questions when no database is chosen. Not
    investigated.
  - **Limits.** 22 to 25 options from 8 questions on unrelated benchmark databases;
    the option answered per run is chosen round-robin; two timeouts (300 s, one per
    arm, different questions) are counted as not asked; M1 and M2 stop the run once
    the database is in the log, so the SQL and its result were not checked; the
    labels still vary; nothing here says the readings suit a real company. The
    frozen eval cases were not rerun because they cannot reach this path.

### Built but never run

PR #44 (`bench split/run/score`) is tested with synthetic cases and fakes only;
it has not been run against the live stack or on LiveSQLBench. PR #25's
held-out value cases (`chinook_values.json`) and the clarification flow (PRs #26,
#27) have never been measured.

### Experiment E (tooling built, not run): wiki compiled into Terms vs plain RAG

- **Question.** Given a prose wiki for a database (Markdown, `#`/`##`/`###`
  headings, formulas and thresholds), does compiling it into ontology Terms
  answer more questions than retrieving the same wiki's chunks as evidence?
- **Arms** (same questions, same engine, same wiki; only how the knowledge
  reaches the model differs). Wiki, cases, extractions and reports all stay
  outside the repository.
  - **E-rag**: `wiki-rag` writes a NEW cases file whose `evidence` is the top-k
    wiki chunks (BM25 by default, `--similarity embedding` reuses the repo's
    `EMBED_*` client). Report `-k` and `--budget-chars` with the score; the
    comparison with arm B (full KB as evidence) and E-auto is only fair at a
    stated, equal evidence budget.
  - **E-auto**: `wiki-extract` has an LLM propose Terms per chunk (name,
    abbreviation, definition, formula, thresholds, dependencies, candidate
    columns, supporting quote). A term whose quote or formula is not a verbatim
    substring of its chunk is rejected and listed under `rejected`. Consolidation
    merges by normalised name and flags `contradiction` and
    `undefined_dependency`. Then `wiki-load --apply` stores the file as Terms.
  - **E-relu**: the same file after a human edited it (`include: false`, fixed
    formulas, resolved flags), loaded the same way.
- **Commands** (one per arm; `--url` defaults to `http://127.0.0.1:3001`):

  ```bash
  python -m dev_tools.evals wiki-chunk --wiki alien.md              # inspect the chunks
  # E-rag
  python -m dev_tools.evals wiki-rag --wiki alien.md --cases lsb/alien.json \
      --out e-rag/alien.json -k 4 [--budget-chars N]
  python -m dev_tools.evals run --cases e-rag/alien.json --target-db alien --label e-rag ...
  # E-auto (needs the gateway: REASONING_* or DEFAULT_MODELS_* settings)
  python -m dev_tools.evals wiki-extract --wiki alien.md --db alien --out alien.terms.yaml
  python -m dev_tools.evals wiki-score-extraction --extracted alien.terms.yaml --kb-dir kb --db alien
  python -m dev_tools.evals wiki-load --file alien.terms.yaml --db alien --dry-run
  python -m dev_tools.evals wiki-load --file alien.terms.yaml --db alien --apply
  python -m dev_tools.evals run --cases lsb/alien.json --target-db alien --label e-auto ...
  python -m dev_tools.evals wiki-load --db alien --remove           # undo
  ```

- **Loader safety.** Our Terms end with `[wiki-e:<db>:<id>]`; `--remove` deletes
  only those (via `DELETE /api/terms/{id}`). Terms are created with
  `POST /api/terms`, linked to tables by column-name match like `lsb-kb`, then
  the database is reindexed. A name already held by any other Term (including
  `[lsb-kb:...]` ones, which are never touched) is reported as a collision and
  not stored; Term names are unique across Terms, so run E-auto on a database
  without arm C's Terms loaded (or expect collisions on shared names).
- **Scoring the extraction.** `wiki-score-extraction` reports recall of the
  official KB term names, the missing ones, extracted-but-not-in-KB terms, and
  matched pairs sorted least-similar first with the numbers found on one side
  only, to eyeball formula and threshold differences. Name recall does not say a
  formula is right.
- **Status.** `FAKES`: nothing has been run against the gateway or the live stack.

## 4. Summary of all measurements

| ID | Date | Set | Engine or arm | Result | Kind | Tag |
|---|---|---|---|---|---|---|
| E01 | 11-10 | Pagila 13x3 | empty index, loosened grader | 79.5% | invalid, retracted | REAL-E2E |
| E03 | 11-10 | Pagila 13x3, strict | `main` before #13/#15 | 61.5% | development | REAL-E2E |
| E03 | 11-10 | Pagila 13x3, strict | with #13 and #15 | 94.9% | development | REAL-E2E |
| E08 | 11-11 | Chinook 20x3 | pre-hardening 81f02eb2 | 70% | held-out | REAL-E2E |
| E08 | 11-11 | Chinook 20x3 | `main` d92eb4e7 | 100% | held-out | REAL-E2E |
| E09 | 11-11 | LSB 180x1, evidence | 81f02eb2 | 54/180 (30.0%) | held-out | REAL-E2E |
| E09 | 11-11 | LSB 180x1, evidence | `main` d92eb4e7 | 49/180 (27.2%); p = 0.40 vs 54 | held-out | REAL-E2E |
| E13 | 11-12 | LSB 180x1, evidence | `main` 02d166c0 (noise run) | 56/180 (31.1%); p = 0.17 vs 49 | held-out | REAL-E2E |
| E14 | 11-12 | LSB 180x1, no knowledge | arm A | 3/180 (1.7%) | LSB, held-out for this arm | REAL-E2E |
| E15 | 11-12 | LSB 180x1, KB as Terms | arm C | 4/180 (2.2%) | LSB | REAL-E2E |
| E16 | 11-12 | LSB 180x1, KB as Terms | arm C' (#42) | 55/180 (30.6%); vs C p < 1e-4; vs B p = 0.41, 1.0 | LSB, not held-out for #42 | REAL-E2E |
| E20 | 11-12 | Chinook EN 20x3 | translation off | 20/20, 60/60 | held-out | REAL-E2E |
| E20 | 11-12 | Chinook FR 20x3 | translation off | 17/20, 53/60 | held-out | REAL-E2E |
| E20 | 11-12 | Chinook FR 20x3 | translation on | 20/20, 59/60 | held-out | REAL-E2E |
| E20 | 11-12 | Chinook EN 20x3 | translation on | 20/20, 59/60 | held-out | REAL-E2E |
| E20 | 11-12 | Chinook FR 20x3 | reworked #49 | 20/20, 59/60 | held-out | REAL-E2E |
| E20 | 11-12 | Chinook EN 20x1 | reworked #49 | 18/20 | held-out | REAL-E2E |
| E20 | 11-12 | Chinook EN 20x3 | reworked #49 | 20/20, 58/60 | held-out | REAL-E2E |
| E22 | 11-12 | Chinook, one question x10 | `main` before #52 | 9/10 correct, 6 slow, 1 cut at 300 s | development | REAL-E2E |
| E22 | 11-12 | same question x10 | with #52 | 10/10 correct, 0 slow (49-62 s) | development | REAL-E2E |
| E22 | 11-12 | Chinook 20x3, Pagila 13x3 | with #52 | 60/60, 39/39 | held-out / development | REAL-E2E |
| E26 | 11-13 | Chinook values 14x3 | `main` then combined build with #58 | 83.3% to 95.2%, 6 improved 1 regressed | held-out | REAL-E2E |
| E26 | 11-15 | Chinook values 14x3 | `main` | 100.0% | held-out | REAL-E2E |
| E26 | 11-15 | Chinook values 14x3 | `main` plus #58 | 97.6% (1 regressed); `REJECT` | held-out | REAL-E2E |
| E26 | 11-15 | Chinook 20x3 | `main` and `main` plus #58 | 98.3% and 98.3% (1 improved, 1 regressed) | held-out | REAL-E2E |

Engineering findings without a score: E02 (empty index), E04 (FK extraction), E05
(value probes and privacy incident), E06 (VIP term), E07 (learned test question),
E10 (connection exhaustion), E11 (host crash), E12 (429 storm), E17 (startup
re-ingestion), E18 (trace), E19 (flaky test), E21 (Terms API), E23 (domain grouping, not scored),
E24 (semantic contract review; the measurement was stopped twice and has no result),
E25 (domain map review), E26 (value-anchor repair, not merged), E27 (unanswerable questions: baseline), E28 (certified metric, change not merged), E29 (rule on the SQL, exploration).

## 5. What is NOT yet measured

- **Accuracy gains on real, messy data.** Every score is on Pagila (development),
  Chinook (clean, well known) or LiveSQLBench (curated). Nothing is measured on a
  customer's own databases and questions.
- **Knowledge extraction from documents.** E16 starts from a curated KB. Whether
  Lexis can compile a prose wiki into correct Terms, and whether that beats plain
  retrieval over the same text, is planned (alien and archeology wiki texts, 20
  questions) and **not run**.
- **Value linking and clarification.** `chinook_values.json` and the clarification
  flow have never been measured. The "Indai" probe failed (E05).
- **Whether FK extraction (E04) changes accuracy.** Not measured.
- **Run-to-run variance beyond one pair.** One noise pair (E13); no multi-run
  confidence interval. 
- **Official-harness agreement.** `lsb-score` was checked against the frozen
  reports, synthetic data and a transcription, not against the benchmark's own
  harness on many tasks.
- **Concurrency limits as implemented.** PRs #35, #38, #40 are fake-tested; a
  live 429 burst, an orphaned-run kill and the slot cap under load are not
  re-measured end to end with the final code.
- **Human review** of the 20 Chinook expected answers and of the Pagila
  reference answers.
- **The semantic contract's effect on accuracy** (E24): no result yet; the isolated
  environment must be rebuilt with the Chinook schema `public` first.
- **The "answers the question" signal** (E27): designed and gated, not yet measured on
  the candidate; needs the held-out probes, Chinook and the 180 LiveSQLBench tasks.
- **Value-anchor literal repair (PR #58):** measured (E26), no gain on current `main`,
  not merged. No held-out set of messy values exists to test it harder.
- **Domain names** (E23): not graded by anyone.
- **Whether PR #52's evidence wording changes the 180 LiveSQLBench questions** (E22).
- **Self-improving behaviour** (learned Terms, promotion, consolidation) is a
  design only; no code or measurement.
- **Paraphrase robustness** of questions (memorisation check): not covered by the
  bench yet.
- **Other connectors** beyond Postgres in real use, and the MySQL/ClickHouse
  read-only checks beyond the one-off manual runs in the register.

## 6. Reproduction

**Environment.** A local stack from `docker-compose.yml` (backend :3001,
ingestion :3002, Postgres with the vector store, the web app), a model gateway
that is OpenAI-compatible, configured with the gateway's default chat model, an
embedding model and a rerank model (see [configuration.md](./configuration.md)).
Do not commit `.env` values. The semantic index must be populated for the target
database (`GET /api/semantic-compilation/status`); `run` refuses otherwise. Keep
the machine awake, use at most 8 concurrent chats and no more than about 12
concurrent gateway calls per IP. `--workers` above the backend's
`/api/health` cap is lowered by `bench`.

**Pagila (E03).** Load `dev_tools/fixtures/sql/pagila.sql`, ingest, compile, then
`python -m dev_tools.evals run --url http://localhost:3001 --label X --out X.json`
for each engine; `python -m dev_tools.evals compare main.json cand.json`. About
an hour for 13 x 3. Pagila is a development set.

**Chinook (E08, E20).** Load `dev_tools/fixtures/sql/chinook.sql` into a
Postgres database named `chinook` (the SQLite fixture must be converted: quoted
CamelCase names, 11 foreign keys), register and ingest it, compile, then
`python -m dev_tools.evals run --cases dev_tools/evals/cases/chinook.json
--target-db chinook --repeats 3 --workers 4 --label X --out X.json`. Verify
expected rows with `snapshot --check ... --dsn sqlite:///chinook.sqlite`. For the
French arms use `chinook_fr.json` from PR #49 and a backend built from that
branch. Scripts: `lang_eval.sh`, `lang2_eval.sh`.

**LiveSQLBench (E09, E13-E16).** Data must be obtained from the benchmark: the
public questions and knowledge-base files from
`huggingface.co/datasets/birdsql/livesqlbench-base-lite`, the database dumps
published by the benchmark, and the ground truth by e-mail request to the BIRD
team (see evaluation.md); keep all of it and every derived file outside the
repository. Then, as in evaluation.md: `lsb-build` (with `--oracle` for arm B;
without for arms A, C, C'), register and ingest the 18 databases, compile, run per
database (`python -m dev_tools.evals run --cases <db>.json --target-db <db>
--repeats 1 --workers 4`), `replay` infrastructure failures under one rule for all
arms, and `lsb-score --reports ... --cases ... --dsn-template ...` (official mode).
Arm C and C': `python -m dev_tools.evals lsb-kb --kb-dir <kb> --db <db> --apply`
first (undo with `--remove`), arm C' with `TERM_DEFINITIONS_IN_GENERATION=true`
(default since PR #42; set it to `false` to reproduce arm C). Run arm A before
loading any Terms. Check the frozen hashes before and after.
Scripts (maintainer machine, outside the repository): `nokb_run.sh`,
`noise_run.sh`, `kbterms_run.sh`, `cprime_run.sh`, helper `heavy.sh` (a lock that
serialises heavy commands). Scores: `lexis-evals/` and `livesqlbench/pr33-check/
fixed/` (`armA-vs-B.txt`, `noise.txt`, `armC.txt`, `armCprime.txt`, `official.txt`,
`clean.txt`). The raw reports are not in the repository, so E09-E16 are
**manual runs, not repeatable from the repository alone**; the repository gives
the tooling and the method.

**Repeatability warning.** Generation is not deterministic; expect about 4 points
of spread on a 180-question single run (E13) and use the paired test, not a bare
difference.
