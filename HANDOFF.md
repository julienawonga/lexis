<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Maintainer handoff (state at 2026-11-14)

For whoever continues the work (a new maintainer or another coding agent).
Read [`CLAUDE.md`](./CLAUDE.md) first: it holds the build, lint and PR rules.
This file adds the project's state, its working rules and its traps.
The user-facing roadmap is in the [README](./README.md#️-roadmap); the plan
below is the same list with the detail a maintainer needs.

## What Lexis is

A fork of NVIDIA's Apache-2.0 `auto-ontology`, renamed Lexis, owned by
`julienawonga` (GitHub repo `julienawonga/lexis`). It turns a company's
databases into a business ontology (Terms, ColumnAttributes, SqlAttributes),
then answers questions in chat by writing SQL against that ontology. Goal:
an enterprise-ready, honest text-to-SQL engine, then a self-improving agent
(learned terms), entity resolution and clarification questions. Keep the
legal files (SPDX headers, LICENSE, NOTICE); do not put NVIDIA forward in the
product or docs.

Stack: Next.js frontend (`frontend/`), FastAPI backend (`auto_ontology/`),
ingestion service, Postgres with pgvector (catalog and semantic index in
`vdb.*`), Alembic migrations, Helm chart, MCP server (`mcp/`).

## How to work with the owner

- The owner writes and reads French. Answer in simple, short French; drop
  jargon, use plain analogies. Code, commits and docs stay in English.
- They test by clicking in the UI and paste screenshots. Say what was verified
  and what was not; never round a claim up (see `docs/verification-status.md`).
- Evaluation is strict: fix the cases before measuring, report strict and
  tolerant scores, judge on held-out data from another database, never write an
  eval question or gold value into prompts or code. Details in
  `docs/evaluation.md`. They have caught shortcuts before.
- Merge only with their explicit OK. Ask before any Alembic downgrade, database
  restore or deleting a worktree.
- Commits: concise imperative, explicit `git add <paths>` (never `git add -A`
  while `.claude/worktrees/` exists). Co-author trailer only on commits the
  agent mostly wrote (rule in `CLAUDE.md`).
- Always pass `--repo julienawonga/lexis` to `gh`: with no repo it resolves to
  the NVIDIA upstream.

## Current state

- `origin/main` = `a534cc1b` (PRs #59 and #61 merged).
- **Open: branch `map-domains-llm`** (worktree `.claude/worktrees/domains-llm`),
  pushed, **no PR yet**, CI never ran on it. It adds the business-domain map
  (database, then domain, then Terms): tables `domain` and `term_domain`
  (migration `d04a88c1b790`), `dal/domains.py`, `retrieval/domains`, routes under
  `/api/exploration/semantic-domains`, the frontend `DomainOverview` and its
  banner/breadcrumb, and `docs/exploration-map.md`. OpenAPI specs are
  regenerated. Remaining before the PR: run the full gates in `CLAUDE.md`
  ("Opening a PR"), open it, wait for green CI.
- The same branch carries a small, unvalidated UI fix: small Term graphs start
  zoomed out (`initialZoomFactor` in `GraphCanvas.tsx`; thresholds 8 and 25
  nodes are guesses).
- **Open: PR #58 (draft)**, value-anchor literal repair. It changes the SQL
  engine, so it needs the eval harness measurement and an `ACCEPT` before merge.
  The `main` baseline on Chinook exists in `lexis-evals/combo/` (outside the
  repo, next to it in `HomeLab`).
- Quality of the domain grouping is **not measured**: tried by hand on Chinook
  (2 domains), Pagila (4), a cross-database set (6) and a 95-Term database (6);
  the groups read as sensible. The owner must judge the business names.
- Owner feedback not yet validated: link width by weight, dragging, animation,
  collapsible side panel, new "Business domain" header.

## Plan, in order

1. Owner validates the domain map; fix what they report.
2. Open the `map-domains-llm` PR; green CI; merge on their OK.
3. Decide with the owner: generate domains at compile time (today only a button
   and the endpoint), let a person move Terms between domains in the UI (the
   API `POST .../{id}/terms` exists, no UI), allow several domains per Term
   (today one per Term per database, `UNIQUE(term_id, database_id)`).
4. Finish the #58 measurement; merge only on `ACCEPT`.
5. "See what each answer used" (roadmap item 8): under each chat answer, the
   definitions, columns and values it relied on, marked certified or not, with
   a reliable record of what the SQL actually applied (decided when the SQL is
   written; today's "used" mark is an often-undecided text heuristic).
6. Learned terms (item 9), then review and promotion (item 10). Business metrics
   as verified definitions (item 6) come first: it is the mechanism a learned
   term is written into.
7. Later: rerun E-auto with the LaTeX fix, live check of API authentication,
   enterprise review items, recorded-model evaluation in CI, database-enforced
   read-only on Snowflake, Databricks, Kyuubi and HeavyDB. "Variant E": user
   documents turned into ontology Terms rather than plain RAG.

## Running the stack (Windows host, Docker Desktop)

- Services: frontend :3000, backend :3001, ingestion :3002, Postgres :5432,
  pgAdmin :5050. Start: `docker compose up -d --no-build` from the main tree
  (it holds `.env`; never print `.env` secrets). Health:
  `curl http://localhost:3001/api/health`.
- Models come from the owner's LiteLLM gateway (chat `openai/gpt-6-luna`,
  embeddings `text-embedding-005` at 768 dimensions, a Cohere rerank). The
  gateway rate-limits: stay at or below 12 concurrent chats per IP.
- **The images tagged `:latest` are built from the unmerged `map-domains-llm`
  branch.** Rollback tags: `:pre-domains` (main with #59) and `:pre-map`
  (main with #61 only).
- **Rollback trap:** the database is at Alembic `d04a88c1b790` and holds test
  domains. An older image crashes at start on the unknown revision. Run
  `alembic downgrade a7c2e91d4b68` from the new image, or restore a dump from
  `HomeLab/lexis-backups` (`pg_dump -U postgres`; the role is `postgres`).
- Rebuild the backend: `docker build -t auto-ontology:latest .` from a clean
  worktree (tag a rollback first). Rebuild the frontend: `docker compose stop`,
  build one image at a time from `frontend/`, then `up -d --no-build`. The
  Docker VM crashes if a frontend build runs next to the stack (`.wslconfig`
  limits it to 7 GB).
- Load limit: each concurrent chat spawns a Python subprocess; 18 at once
  crashed the host. Keep load tests at 8 or fewer, away from builds.

## Tests and checks on this machine

- `uv sync` does not work on Windows (a dependency needs MSVC). Run Python
  tests and the backend OpenAPI generator in Docker:
  `ghcr.io/astral-sh/uv:python3.12-bookworm`, `uv sync --locked --extra kumo`
  (without `--extra kumo` the sync hangs), then pytest. DAL tests need a
  throwaway pgvector Postgres (never the owner's `postgres` container):
  seed fixtures, `alembic upgrade head`, `seed_graph_fixture --reset`,
  `alembic check`. Copy the tree with `tar`, excluding `.git`, `node_modules`,
  `.venv` and `.claude`, but keep `frontend/` or `test_licensing` fails.
- `uvx ruff` works directly on Windows. Frontend checks run natively.
- Public OpenAPI spec: `pnpm openapi` in `frontend/` writes backslashes in
  `x-auto-ontology-source` on Windows. Replace them with `/` (regenerate in
  Linux Docker to avoid it) and regenerate both copies
  (`docs/openapi/auto-ontology-api.json`,
  `mcp/auto_ontology_mcp/auto-ontology-api.json`).
- A new public DAL function needs an entry in
  `auto_ontology/dal/tests/dal_surface.json`; changed reads need
  `python -m dev_tools.fixtures.capture_dal_golden` (review the diff).
- CI fails if more than 3 tests are skipped (the three opt-in live-engine
  tests). Add to the guard instead of silencing it.
- Files: the worktree may contain CRLF while the index is LF. Before pushing,
  `git ls-files --eol` must show no `i/crlf` file. Python scripts that rewrite
  files on Windows must open them with `encoding='utf-8'`.
- Do not `git checkout` in the main tree (another session may commit there):
  use `git worktree add .claude/worktrees/<name> -b <name> main`.
- GitHub is flaky: retry pushes, check with `git ls-remote`, and confirm a
  merge with `gh pr view --json state`.

## Where things are documented

`docs/verification-status.md` (what is really verified, one row per
capability), `docs/evaluation.md` (harness rules), `docs/query-safety.md`
(read-only, row-capped agent SQL), `docs/exploration-map.md`,
`docs/design/self-improving-ontology.md` (design of learned terms),
`docs/experiments.md` (measurements log).
