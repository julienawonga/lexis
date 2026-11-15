<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Semantic contract v0.1 — handoff

Updated: 2026-11-15  
Working branch: `codex/semantic-contract`

This note is the continuation point for any agent taking over the semantic
contract and governance work. Read [`AGENTS.md`](../../AGENTS.md),
[`CLAUDE.md`](../../CLAUDE.md), and
[`semantic-contract.md`](./semantic-contract.md) first.

## Goal and current product boundary

The goal is a robust, portable semantic model that different agents can
interpret consistently. The current implementation is experimental v0.1. It
exposes a typed, agent-neutral contract and a proposal/review lifecycle.

An approved snapshot currently overlays `GET /api/semantic-model` and the MCP
`get_semantic_model` read tool. Approval does **not** update legacy Term rows or
the text-to-SQL planner. Do not claim planner integration or production-ready
cross-agent reliability yet.

## Work already in the branch

- Pydantic semantic objects and validation in `auto_ontology/semantic/`.
- Portable semantic projection, catalog fingerprints, and stale-source handling
  in `auto_ontology/server/model_interchange/`.
- Proposal/event persistence, append-only event enforcement, review service,
  and API router in `auto_ontology/dal/semantic_governance.py` and
  `auto_ontology/server/semantic_governance/`.
- Next.js authenticated read/write routes under
  `frontend/app/api/semantic-model/`.
- OpenAPI, MCP tool, ontology-management skill, and design documentation
  updates.
- Alembic migration `29ac894b925b_semantic_proposal_governance.py`, based on
  `a7c2e91d4b68`.

The changes are currently uncommitted. Preserve the user's unrelated
`.vscode/launch.json` change and untracked `dev_tools/websearch.py`.

## Verification evidence already reported

Prior isolated-environment validation reported:

- 49 focused pytest cases passed across semantic contract, model interchange,
  and governance service tests.
- Ruff passed on changed backend modules.
- Migration upgrade, downgrade, and re-upgrade passed; `alembic check`
  reported no pending operations.
- TypeScript `tsc --noEmit` passed after the Next route-context type fix.
- A DAO integration check confirmed event history and database rejection of
  event mutation.
- The focused regression test for a null SQL-attribute source passes in the
  project virtualenv (`1 passed`); the test now lives in
  `auto_ontology/server/model_interchange/tests/test_model_interchange.py`.
- Next production build was not verified; the earlier attempt was blocked by
  unavailable Google Fonts network access.

Fresh validation on 2026-11-15 using `.venv/Scripts/python.exe` passed all 50
focused semantic-contract, model-interchange, and governance tests. Ruff check
and format-check passed for the changed model-interchange module and its unit
test. `git diff --check` also passed. The system Python lacks pytest; use the
repository virtualenv for follow-up.

Fresh isolated-database e2e on 2026-11-15 (`dev_tools/e2e_semantic_governance.py`,
REAL-ENGINE, row added to `docs/verification-status.md`): an isolated
`pgvector/pgvector:pg17` container on port 5433 was migrated with the branch's
full Alembic chain, then the real FastAPI app (in-process TestClient, two seeded
admin users) ran proposal → self-approval refusal → evidence refusal →
independent approval → certified overlay readback → source drift →
`needs_revalidation` → rejection path → append-only event enforcement →
proposal-deletion blockage. All nine checks passed. The same container then
passed downgrade, re-upgrade, and `alembic check`. The running local compose
stack was not touched: its `alembic_version` is `d04a88c1b790`, a revision this
branch's chain does not contain — verify what code produced it before ever
pointing this branch at that database.

Docker was previously unreachable from agent sessions; it is available as of
2026-11-15, so isolated-database verification is repeatable.

## External review findings — hypotheses to verify

Pi/GLM received the focused semantic-governance diff through the user's
configured enterprise LiteLLM gateway. Its review raised the following points.
The nullable-source issue was confirmed against the local schema and model and
fixed by restoring the existing `SQL_ATTR_SOURCE_MANUAL` fallback in
`auto_ontology/dal/model_interchange.py`. The other points were checked against
local source as follows:

1. **Deployment invariant — read authorization:** FastAPI proposal GET
   handlers and `GET /api/semantic-model` do not enforce `catalog:read`
   themselves. The Next.js routes do. `InternalTokenMiddleware` protects
   backend routes when `INTERNAL_API_TOKEN` is set. Helm generates and shares
   this token by default; Compose leaves it optional and binds the backend to
   localhost by default. The chart exposes the backend as `ClusterIP` and the
   frontend as `NodePort`. Verify the actual deployment has the token set and
   keeps the backend private.
2. **Deployment invariant — forwarded identity trust:** FastAPI trusts the
   Next.js forwarded-user header only after the internal-token middleware
   accepts the request. This is protected in the Helm default (generated
   shared token); it is not protected when operators leave the token unset, as
   Compose allows. Verify the deployment setting and network exposure.
3. **Resolved, not yet regression-tested — nullable SQL attribute source:**
   `sql_attribute.source` is nullable while `ModelSqlAttribute.source` is a
   `str`. `_export_sql_attributes` again falls back to
   `SQL_ATTR_SOURCE_MANUAL` when the database value is null. Add a focused
   regression test when tests are next run.
4. **Refuted — transaction/locking:** `store()` returns the active
   `StoreConn`, and `write_transaction()` installs it in a `ContextVar`. The
   `SELECT ... FOR UPDATE` and subsequent update share the same transaction
   and connection.
5. **Refuted — Next route user context:** `withPermission` injects `{ user }`
   into the handler context.
6. **Latent schema issue — append-only cascade:** the event FK uses
   `ON DELETE CASCADE`, while its trigger rejects event deletes. There is no
   proposal deletion endpoint now; define a retention/deletion policy before
   adding deletion or cleanup behavior.
7. **Open concurrency question — fingerprint race:** the service checks the
   catalog fingerprint before the DAL locks the proposal row. Decide whether
   source drift in that interval must prevent approval; the semantic
   projection detects drift on subsequent reads.
8. **Refuted — database name ambiguity:** `catalog_database.name` is unique in
   `auto_ontology/dal/schema.py`.

An attempted Gemini Enterprise verification of the code review was blocked by
the automatic approval reviewer. No repository code was transmitted to Gemini
for that review. Do not retry by changing the transport or packing the code
differently. The earlier minimal `agy` prompt test did work; it did not include
repository content.

## Decided policies (2026-11-15)

**Fingerprint race at approval time.** The service recomputes the baseline
fingerprint during review, outside the DAL's `FOR UPDATE` transaction, so a
source change in the milliseconds between the check and the commit could be
approved. Decision: accept the window and treat the read path as the final
source of truth. The overlay already recomputes the fingerprint on every
`GET /api/semantic-model` and demotes a drifted object to
`needs_revalidation`, so a stale approval is never presented as current. Do
not move the fingerprint computation inside the write transaction; if a future
requirement demands closing the window, recheck the fingerprint after locking
the proposal row rather than locking catalog rows.

**Proposal retention and deletion.** Keep the current structural lock: there
is no deletion endpoint, and the `ON DELETE CASCADE` from proposal to events
combined with the append-only trigger makes deleting a proposal with events
impossible. This is deliberate. A future retention policy must not become a
plain DELETE — it must be an explicit archival operation (for example a new
event type plus a state that removes the proposal from default listing while
keeping its events), designed and reviewed together with the audit
requirements. Never weaken the event trigger to make deletion pass.

## Recommended next steps

1. Verify that the deployed backend has `INTERNAL_API_TOKEN` set and is not
   exposed directly; Helm defaults to a shared generated token, Compose does
   not.
2. The null SQL-attribute source fallback regression test is added and passes.
   The fingerprint-race and deletion-retention policies are decided above.
3. ~~Run an end-to-end proposal → independent approval/rejection → semantic
   readback flow against an isolated test database~~ Done 2026-11-15, see the
   e2e paragraph above and the `dev_tools/e2e_semantic_governance.py` script.
   Re-run it after any governance change: reset the container database, run
   `alembic upgrade head`, then the script with `POSTGRES_*` pointing at it.
4. ~~Regenerate backend and public OpenAPI artifacts after route/docstring
   changes; keep the mirrored MCP spec identical.~~ Done 2026-11-15: backend
   spec regenerated (66 paths, 92 ops); the public and MCP mirrors were already
   in the branch.
5. ~~Run the repository checks below and update `docs/verification-status.md`
   with the level actually reached.~~ Done 2026-11-15: ruff check/format pass;
   the DAL surface snapshot was regenerated (`dal_surface.json`, 24 modules /
   263 functions) and `helm/auto-ontology/values.yaml` now pins head revision
   `29ac894b925b`; the full suite reports 25 failed / 2792 passed / 831 skipped
   with every failure environmental (18 kumo wiring tests have no Windows
   wheel, 4 CRLF byte comparisons, a cp1252 decode, an address-bearing frozen
   repr, a missing `POSTGRES_USER`, and a dead catalog DB) — see the new
   `docs/verification-status.md` row. Three test files whose DB fixtures hang
   without `connect_timeout` against the unreachable local Postgres
   (`test_incremental_ingest.py`, `test_source_connection_pooling.py`,
   `test_clarification_store.py`) were excluded from the run; fixing those
   fixtures is upstream work, not branch work.
6. Only after the governance path is stable, design planner consumption and a
   versioned cross-agent interpretation evaluation set as the next product
   milestone.

## Next product milestone: planner consumption

Start this only after the isolated proposal/review/readback flow passes. The
goal is for approved semantic knowledge to improve the existing SQL planner,
not to create a competing planner or silently change the meaning of existing
catalog rows.

1. **Trace the existing path.** In `auto_ontology/retrieval/text_to_sql/`, map
   how catalog columns, terms, relationships, and certified SQL attributes
   become candidates and prompt context. Identify the narrowest adapter point
   where agent-neutral objects can influence retrieval.
2. **Define the eligibility contract.** Initially allow only active,
   `certified` contract objects with valid bindings and current source
   fingerprints. Exclude drafts, rejected objects, `needs_revalidation`, and
   unverified legacy projections from the new contract adapter. Keep existing
   planner behavior available as the fallback when no eligible contract object
   applies.
3. **Adapt; do not dump the document into prompts.** Convert only the relevant
   concepts, attributes, relations, and verified queries for the selected
   database and candidate columns. Preserve object IDs, status, provenance,
   relation direction, and scope so the planner can cite why each candidate
   applies. Do not infer metric grain or units until those semantics are
   explicitly modeled and validated.
4. **Prove query behavior.** Add focused tests for eligibility, stale-source
   exclusion, database scoping, relation direction, and fallback. Then use the
   frozen evaluation set with identical cases and conditions for baseline and
   candidate; follow `CLAUDE.md` and `docs/evaluation.md`, and merge only on an
   `ACCEPT`. Never place gold answers or expected literals in prompts or
   retrieval resources.
5. **Show the complete path.** In an isolated database, approve one semantic
   object, confirm it reaches planner retrieval, ask a representative question,
   inspect generated SQL and rows, and prove that changing the source makes
   the approved object ineligible until revalidated.

Acceptance requires: unapproved or stale assertions cannot change generated
SQL; an approved and relevant assertion measurably improves its intended case
without degrading the evaluation gate; and the old path still works when no
eligible assertion exists. Report the exact evaluation and verification level
reached in `docs/verification-status.md`.

## Repository checks

From the repository root, per `CLAUDE.md`:

```powershell
uv run ruff check auto_ontology/
uv run ruff format --check auto_ontology/
uv run pytest auto_ontology dev_tools -q
uv run python -m dev_tools.generate_backend_openapi
```

From `frontend/`:

```powershell
npx prettier --check .
pnpm lint
pnpm build
```

Before working, inspect `git status` and `git diff`; do not reset or clean the
working tree. Never read or transmit `.env`, credentials, or provider tokens as
part of an agent review.
