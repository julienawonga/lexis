<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# What each answer used: two marks

Under an answer, the Knowledge breakdown lists the definitions, SQL attributes,
custom analyses and column attributes the SQL generator was given, whether each
is certified, and two separate marks about whether the SQL applied it. The
entry shape and the text match are in
[Knowledge-use trace](conversation-api.md#knowledge-use-trace); this page
describes the second mark and how the two relate.

## The two signals

| Key | Meaning | Where it comes from | What it is not |
|---|---|---|---|
| `found_in_sql` (same value as `used`) | The entry's own identifiers or literals appear in the final SQL: `true`, `false`, or `null` when the match cannot decide. | A deterministic text match on the final SQL, after the fact. | A cause. An identifier can appear for another reason. |
| `declared` | The model listed this entry among the knowledge it applied. `null` when recording is off or the model returned no list. | The model's own structured output, written together with the SQL. | Proof. The model can claim what it did not do, or omit what it did. |

They are never merged into one claim. The interface shows both, with these
labels:

- `Applied (the model said so)` for `declared`, and `found in SQL` for the text
  match.
- When they disagree, a plain line: "The model said it applied this but nothing
  in the SQL matches", or "Found in the SQL but not declared". A disagreement is
  shown, never hidden.

The old `matched` key is unchanged: it still lists the identifiers or literals
the text match found. The new boolean is named `found_in_sql` because `matched`
already carries that list.

## How `declared` is recorded

It is off by default. The configuration row `knowledge_applied_record_enabled`
(read per request, like the other flags in `infra/feature_flags.py`) turns it
on. With it off, the generation prompt and the output schema are exactly what
they were before the feature existed (tested).

With it on:

1. One extra system message is added to the SQL generation request, listing each
   offered item under a short tag, with a one-line instruction:

    ```text
    OFFERED KNOWLEDGE (tags)
    In applied_knowledge, list the tags of the items below whose definition, expression or column you actually applied in sql_code ([] if none).
    [T1] business definition: Net Revenue
    [A1] SQL attribute: net
    [C1] custom analysis: Orders
    [V1] column attribute: Order amount (column amount)
    ```

    Prefixes are `T` (Term whose definition is in the evidence), `A` (SQL
    attribute), `C` (custom analysis) and `V` (retrieved column attribute),
    numbered in the order the trace lists each kind.

2. The structured output uses `SQLGenerationWithAppliedModel`, a subclass of
   `SQLGenerationModel` with one extra field, `applied_knowledge: list[str]`
   (default empty). The base class is used whenever the flag is off, so its
   JSON schema is untouched.
3. In code, each returned tag is verified: it must be one that was offered
   (case and brackets are normalised). Unknown tags are dropped and counted
   (logged as `dropped`); repeats count once. The verified list is stored as
   `knowledge_declared` in the run state and read when the trace is built.

`declared` describes the first generation. If a later step repairs or replaces
the SQL, the record is not refreshed, so `declared` can describe an earlier
query than the one shown; this is one reason it is not proof.

## Evaluation

This changes what the model sees when on, so it is gated like any engine change
(see [Evaluating the text-to-SQL engine](evaluation.md)): the frozen sets with
the flag off against on must show no regression
(`compare --margin 0`). The agreement between `declared` and `found_in_sql` over
the run is reported as information only (`dev_tools.evals.report.knowledge_agreement`
counts `agree`, `declared_only`, `found_only` and `undecided`); no threshold is
set on it before it has been seen.
