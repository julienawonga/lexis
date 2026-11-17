<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Learned definitions

When Lexis asks "what do you mean by VIP customers?" and you answer, your answer is worth
keeping. With this feature on, it is saved as a **draft definition** in your own space:
who said it, when, and in which conversation. You can edit it, and when you are happy
with it you can submit it for review. An owner then approves it for everyone, or sends it
back.

!!! note "What this does not do yet"
    A draft does **not** change the answers Lexis gives, not even yours. Lexis does not
    read drafts when it writes SQL, and an approved definition is not yet added to the
    business Terms. This page covers saving, editing and reviewing only.

## Switching it on

It is **off by default**. It is switched on by the `knowledge_items_enabled` row of the
configuration table (`true`). While it is off:

- every `/api/knowledge-items` route answers `404` with
  "Knowledge items are not enabled on this server.";
- an answer to a clarification question is not saved;
- the "Learned" entry of the sidebar and the page are hidden.

A second row, `knowledge_admin_audit_enabled`, lets administrators read other people's
personal drafts (for organisations that must audit them). Off by default: a personal
draft is visible to its owner only, administrators included.

## Who sees and does what

| | Owner of the draft | Another user | Admin | Owner of the database or Term |
|---|---|---|---|---|
| See a personal draft | yes | no | only with the audit setting | only once submitted for review |
| Edit a draft | yes | no | no | no |
| Submit for review | yes | no | yes (if they can see it) | yes (if they can see it) |
| Approve, reject, request changes | not their own | no | yes, not their own | yes, not their own |
| Withdraw | yes | no | no | no |

Nobody approves what they proposed. An agent never approves: certification is a human act.
Approving a personal item first shares it with everyone, as its own step in the history,
and then certifies it. These rules live in the database layer, not in the web app, so no
route can skip them.

## The page

**Learned** in the sidebar opens two tabs.

- **My drafts**: your own items. Edit a definition, submit it for review, or withdraw it.
- **To review**: items in review that you may approve. Each shows the proposed definition,
  who proposed it and when, how it came to be (for example "Learned from a clarification
  question: they chose an option"), and its history. **Approve** asks you to confirm;
  **Reject** and **Request changes** need a comment.

If someone changed an item since you opened it, your action is refused with "This item
changed since you opened it": nothing is overwritten. Reload and try again.

In the chat, an answer that taught Lexis a term shows "Saved as your draft definition:
VIP customers" with a link to the page. The line appears on the live answer only.

## API

All routes are under `/api/knowledge-items` and need the same permission as using the chat.
A person's own draft, and anything shared, is what a list returns.

| Route | What it does |
|---|---|
| `GET /knowledge-items/status` | `{"enabled": true or false}`. Never `404`. |
| `GET /knowledge-items` | List, newest first. Filters `status`, `kind`, `database`, `mine`, `reviewable`; page with `limit` and `cursor` (pass `next_cursor` back). |
| `GET /knowledge-items/{id}` | One item with its history. `404` if you may not see it. |
| `POST /knowledge-items` | Create a personal draft. `kind` is `term` (`name`, `definition`) or `synonym` (`term`, `synonyms`). |
| `PATCH /knowledge-items/{id}` | Edit a draft you own. Send `expected_version`. |
| `POST /knowledge-items/{id}/submit` | Send a draft for review. |
| `POST /knowledge-items/{id}/approve` | Approve an item in review. |
| `POST /knowledge-items/{id}/reject` | Reject it. A `comment` is required. |
| `POST /knowledge-items/{id}/request-changes` | Send it back to its owner. A `comment` is required. |
| `POST /knowledge-items/{id}/withdraw` | Withdraw your own item. |
| `POST /knowledge-items/{id}/deprecate` | Retire an item (someone who may approve it, or its owner). |
| `POST /knowledge-items/{id}/promote-scope` | Share a personal item in review without approving it. |

Every item carries `current_version` and `allowed_actions`. Send `current_version` back
as `expected_version` on an edit, and optionally on any other action: if the item changed
meanwhile the answer is `409` and nothing is written.

Errors: `404` not found, or not visible to you, or the feature is off; `403` you may not do
this; `409` the item is in a state that does not allow it, or changed since you loaded it;
`422` the request is malformed (for example an empty definition, or a missing comment).

## What is recorded

Each action is a row in the item's own history (who, what, when, your comment), and the
mutating routes also write to the [audit log](audit-log.md) as `knowledge.propose`,
`knowledge.submit`, `knowledge.approve`, `knowledge.reject`, `knowledge.request_changes`,
`knowledge.deprecate` and `knowledge.promote_scope`. The audit log keeps the item id, its
kind and the status or scope change. It never keeps the definition or a comment, which
may quote your question.
