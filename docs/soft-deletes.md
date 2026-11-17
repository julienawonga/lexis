<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Soft deletes

Many application databases never remove a row when a user deletes it. They fill
a nullable timestamp (`deleted_at`) and leave the row in place. A person who
asks "How many customers do we have?" means the rows that are not deleted, but
nothing in the question says so, and the engine used to count all of them.

When the `soft_delete_hint_enabled` flag is on, Lexis detects such columns and
tells the model, next to each offered table, to exclude the deleted rows by
default.

## The convention

A soft-delete marker is a column that is **all** of:

- a date or timestamp type (`date`, `timestamp`, `timestamptz`, `datetime`, ...;
  a time of day or an interval does not count);
- nullable (a column of unknown nullability does not count);
- named, after splitting into tokens (snake_case, camelCase, any separator),
  with a deletion word and a time word, or exactly a deletion word.

Deletion words: `deleted`, `removed`, `archived`, `voided`, `trashed`,
`discarded`. Time words: `at`, `on`, `dt`, `date`, `time`, `ts`, `timestamp`.
So `deleted_at`, `deletedAt`, `archived_on`, `date_deleted` and a nullable
timestamp called just `deleted` all match.

The word list is a naming convention taken from common ORMs and frameworks
(Rails `discard` and `paranoia`, Laravel `SoftDeletes`, Django third-party
soft-delete apps, Hibernate `@SQLDelete`). It was not derived from any
benchmark or evaluation set. Business states are on purpose not in it:
`cancelled_at`, `retired_on`, `closed_on`, `expires_at`, `ended_at`,
`inactive_since` describe the life of the thing, not that the row was deleted,
and a question about them must still see those rows. The tests check these
look-alikes.

The detector lives in `auto_ontology/retrieval/text_to_sql/soft_delete.py` and
uses only name, type and nullability from the catalog. It does not look at the
data: a check that the column is NULL for some rows and filled for others would
need value statistics the candidate tables do not carry.

## What the model sees

For each offered table that has a marker, one sentence is added after the table
line in the schema context (`format_tables_for_prompt`, used by SQL generation,
reconstruction and evidence refinement) and on the matching line of the intent
validation context (`format_used_schema_for_prompt`):

> Soft delete: this table soft-deletes rows through `deleted_at` (a row where it
> is not NULL is deleted); exclude deleted rows by default by adding
> `deleted_at IS NULL` to this table's filter, also when the table is joined,
> unless the question explicitly asks about deleted, removed or archived records
> or about all history.

The intent validator is told, only when such a note is present, that the added
`IS NULL` filter is expected and must not be flagged as a filter the question
did not request.

The trace: `path_state["soft_delete_columns_applied"]` lists
`table.column` for every marker offered (for example `customer.deleted_at`), so
the interface could show "excluded deleted rows". It is not yet put in the
answer dict.

## The flag

`soft_delete_hint_enabled` in the `configurations` table, read per request,
**off by default**. With the flag off no table is annotated, no key is added to
`path_state`, and every prompt is byte for byte what it was before (checked by
a test against the pre-change rendering).

## Must pass the gate before it is turned on

The note changes what the model sees. Per `CLAUDE.md` it is not judged by CI:
measure it with the evaluation harness ([evaluation.md](evaluation.md)) and
turn the flag on only after an `ACCEPT`. The rentals set is the motivating set
for this change, so it is a development set for it, not held out; Chinook and
Pagila have no such columns and are the regression guard (the flag must change
nothing there). The tests use fake catalogs and never call a model.

## What it does not handle

- Boolean flags: `is_deleted BOOLEAN`, `deleted BOOLEAN`, `is_active`. Whether
  to add them is the owner's decision; they are not handled now.
- Status codes: `status = 'deleted'` or `'archived'`.
- Deletion recorded in a separate table, or by a column whose name does not use
  a deletion word (`dropped_on`, `gone_at`).
- A marker column the catalog reports as non-nullable or of unknown nullability.
