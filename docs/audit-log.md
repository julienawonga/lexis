<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Audit log

A persistent, queryable record of administrative and governance actions: who did
what to which target, and when. Administrators read it in **Settings, Audit
Log** or through `GET /api/audit-events`.

The log lives in the `audit_event` table. It is append-only by convention (like
`knowledge_event`): the code only inserts and reads, and nothing updates or
deletes a row.

## What is recorded

One event per successful action. The action is a short dotted verb.

| Action | When |
|---|---|
| `term.create`, `term.update`, `term.delete` | A business Term is created, edited or deleted |
| `connection.create`, `connection.update`, `connection.delete` | A database connection is added, rewritten or removed |
| `semantic_compilation.reset`, `semantic_compilation.reindex` | The semantic layer is rebuilt, or one database's index is re-embedded |
| `group.create`, `group.update`, `group.delete` | A group is created, edited (including its members) or deleted |
| `zone.create`, `zone.update`, `zone.delete`, `zone.set_status` | A zone is created, edited, deleted, enabled or disabled |
| `sql_attribute.create`, `sql_attribute.update`, `sql_attribute.delete` | A SQL attribute changes |
| `custom_analysis.create`, `custom_analysis.update`, `custom_analysis.delete` | A custom analysis changes |
| `semantic_domain.generate`, `semantic_domain.rename`, `semantic_domain.move_terms` | Business domains change |
| `knowledge.propose`, `knowledge.submit`, `knowledge.approve`, `knowledge.reject`, `knowledge.request_changes`, `knowledge.deprecate`, `knowledge.promote_scope` | A learned definition is created, submitted, decided on, withdrawn or shared. Only the item id, its kind and the status or scope change are kept, never the definition or a comment |

Each event carries:

- `at`, the time of the action;
- the actor: user id and email **as they were at the time** (an account that is
  deleted later stays named), and an actor kind, `user`, `api_token` or `system`;
- the target: kind, id and, where it is an identifier, name;
- `request_id`, only when the caller sent an `x-request-id` header (the JSON
  error contract carries an `error_id`, not a request id, so it is usually
  empty);
- `details`: a small object, see below.

The actor is the Lexis user id the web app forwards in
`x-auto-ontology-user-id`, the same identity every `audit:` log line already
names. A call that reaches the private API without that header is recorded as
`system`. The web app does not say whether a person used a session or an API
token, so `api_token` is a valid kind that nothing sets yet. The existing
`audit:` log lines are unchanged.

Settings stored by the web app directly in its own database (the semantic
compilation toggle, PII settings, SSO configuration) do not pass through the API
and are **not recorded yet**.

## What is never recorded

- **Secrets.** `details` is an allowlist of fields per action
  (`ALLOWED_DETAILS` in `auto_ontology/dal/audit.py`). Anything else is dropped,
  an action with no entry keeps no details, and values are cut down to short
  scalars, so a nested object cannot ride along under an allowed key. A
  connection event holds only the engine type and the ontology language: never a
  host, a user name, a password, a key, or even the names of the fields sent.
  Tests write a fake password through every connection action and check it never
  reaches the table.
- **Question text, or anything a user typed about their data.** Custom
  analyses, which are titled by a question, are recorded by id only.
- **The client IP address.**

## Failure behaviour

A failing audit write is logged at error level and swallowed. The action it
describes has already succeeded, and the audit must not turn it into a 500. The
cost is a missing line, which the error log makes visible.

## Reading it

`GET /api/audit-events`, administrators only: 401 without a named caller, 403
for anyone who is not an admin. Filters: `action_prefix` (for example `term.`),
`actor_id`, `target_kind`, `target_id`, `since`, `until`. Events come newest
first; pass `next_cursor` back as `cursor` for the next page (keyset pagination,
so a page never shifts when new events arrive). In the web app the route is
gated by the `group:manage` permission, which only admins hold.

## Retention

None yet. Events are kept forever and nothing prunes the table. Decide a
retention period before the table grows large, and prune with a scheduled job
rather than by hand.
