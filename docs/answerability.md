<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Refusing a question the data cannot answer

Status: implemented, **off by default, never run against a model**. The owner
enables it only after it passes the evaluation gate (below).

## The problem

Retrieval always finds a nearest neighbour and SQL generation must emit SQL, so
a question about something the database does not hold gets a result for a nearby
column, silently (21 of 28 unanswerable runs in E27; audit finding E1). The
earlier attempt asked the model to grade its own finished answer ("fully,
partly, no") and flagged 52% of answerable questions; that design is not used
here.

## The mechanism

A node, `check_answerability`, runs between `prepare_candidates` and the step
that follows it (`refine_evidence` or `construct_sql_from_candidates`). It makes
one structured call on the non-reasoning model and decides in code.

1. **One call, claims not grades.** The model sees the user's own wording (and
   the translated one when translation ran), the offered tables with column
   names, types and descriptions, and the business definitions (Terms, certified
   SQL attributes, custom analyses, glossary, request evidence). It lists every
   distinct thing the question asks for and gives each a status: `in_schema`
   (with the `table.column` it relies on), `derivable` (with the columns and a
   one-line formula), `defined` (with a verbatim quote from the definitions) or
   `absent`. The prompt says a nearby but different column is not a match and
   that anything in the business definitions is available.
2. **Verification in code.** Every cited `table.column` must be one of the
   offered columns (quoting and schema prefixes are ignored). An `in_schema` or
   `derivable` item with no valid cited column becomes `absent`. A `defined`
   item must quote the definitions verbatim or cite a valid column, otherwise it
   becomes `absent`.
3. **The decision is code, with no threshold:** refuse if and only if at least
   one item is `absent` after verification.
4. **On refusal** no SQL is generated or run. The run ends with a normal
   `result` answer: `refusal: {missing: [...], reason: "..."}`, a caveat
   `{"code": "unanswerable", ...}`, `sql_code: null`, no
   `sql_response_from_db`, and a `response` in the user's language saying what
   the data does not hold and naming up to three offered columns that are
   closest. The closest columns are picked without a model (words shared with
   the missing item, else the columns retrieval had matched). The text is the
   model's own short message in the user's language; if it wrote none, a fixed
   template (English, French, Spanish, German, Italian, Portuguese) is used.
5. **Fail open.** No model client, nothing offered to check against, a failed
   call, no output or an empty item list: the question goes to normal
   generation and the answer carries the caveat `answerability_unchecked`. A
   broken check never blocks a question.

## The flag

`answerability_check_enabled`, a row of the `configurations` table
(`"true"` / `"false"`), read per request like `clarification_enabled`. Absent or
unreadable means off. Off means no node is entered and no extra model call is
made: the graph runs exactly as before.

Skipped even when on: prediction questions (no SQL to refuse), and turns that
answer a clarification the user chose an option for (the evidence line
`The user defined "..." as: ...` marks them; the user just said what the term
means). Information questions are answered from metadata before this point.

## What it can cost

It adds one model call per calculation question. It can refuse an answerable
question when the model fails to see that a column holds the thing asked for
(cryptic names, no descriptions), or cites a name that is not offered. It cannot
see a column that candidate selection left out of the offered tables: a table
dropped upstream makes its columns look absent. A `defined` claim whose quote is
trivially short passes, which errs toward answering. Only an evaluation can say
how often these happen.

## Before enabling it (owner decision)

It changes what the model sees, so it must pass the gate in
[`evaluation.md`](evaluation.md): the frozen unanswerable set with
`--with-controls`, then Chinook, Pagila and Rentals, compared against the same
engine with the flag off, with a fixed false-refusal criterion written before
the run. No constant of this mechanism may be tuned on those sets. Record the
result in `experiments.md` and update the row in
[`verification-status.md`](verification-status.md).

## Version 2

**Version 1 was rejected by its gate.** Measured on the local stack, it refused
105 of 105 scored runs on the 36 unanswerable questions (baseline 13%), but it
also refused 6 of 36 answerable control runs (baseline 0), so criterion C3
failed. The backend log showed two causes:

- a measure that has to be computed (a figure that exists only as payments joined
  through other tables) was declared absent;
- a table reached through several joins was not among the offered tables, because
  the relevance filter had dropped it, so something it holds looked absent.

Version 2 changes two things, in code and prompt. There is still no numeric
threshold, and nothing was tuned on any evaluation set.

1. **Computed measures are not absent.** The first-pass prompt now says that a
   revenue, total, count, average, share, ratio, rate per group, rank or period
   figure is a measure computed from columns, not a column, and is `derivable`
   whenever the columns it needs exist (named, with the formula in one line),
   even across a join. `absent` is only for a thing no offered column holds and
   no offered column can compute. An item that only says how to group, order,
   limit or present the result is not a separate item.
2. **Escalation before refusing.** For every item the first pass marks `absent`,
   one second call sees a compact outline of the whole catalog of the target
   database (table name, column names and types, no descriptions; built from
   existing DAL reads in `catalog_outline.py`). It answers `found` (with
   `table.column` identifiers) or `still_absent` per item. Code checks that the
   cited identifiers exist in the outline. The question is refused only if an item
   is still absent; otherwise generation proceeds as if answerable and the tables
   the second pass cited are appended to the offered tables (same dict shape as
   the other relevant tables; intermediate tables a join needs are not added).

The outline is capped at 60,000 characters (a documented size limit). A larger
catalog is cut to the tables sharing the most words with the items. A truncated
outline can rescue an item but never condemn one: if it is truncated and an item
is still absent, the check logs that and fails open with
`answerability_unchecked` instead of refusing. The same happens when there is no
database to read, the read or the call fails, or the second pass skips an item.

New risks. A catalog table matching the item only by name can now let a question
through that should have been refused (a missed refusal), and the second call
adds latency on every question that had an absent item. A very large catalog
refuses less often because truncation fails open. False refusals remain possible
when the second pass also misses a computed measure.

**Version 2 must pass a new gate on fresh question sets before the flag is
enabled.**
