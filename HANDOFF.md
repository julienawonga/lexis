<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Maintainer handoff (state at 2026-11-17)

For whoever continues the work (a new maintainer or another coding agent). Read [`CLAUDE.md`](./CLAUDE.md) first: it holds the build, lint, PR and evaluation rules. This file adds the state, the owner's working rules and the traps of the owner's machine. The product roadmap is in the [README](./README.md#️-roadmap).

## What Lexis is

A fork of NVIDIA's Apache-2.0 `auto-ontology`, renamed Lexis, owned by `julienawonga` (repo `julienawonga/lexis`). It turns a company's databases into a business ontology (Terms, ColumnAttributes, SqlAttributes), then answers questions in chat by writing SQL against it. Keep the legal files (SPDX headers, LICENSE, NOTICE) and do not put NVIDIA forward in the product or docs.

Stack: Next.js frontend (`frontend/`), FastAPI backend (`auto_ontology/`), ingestion service, Postgres with pgvector (catalog and semantic index in `vdb.*`), Alembic, Helm chart, MCP server (`mcp/`).

## How to work with the owner

- The owner writes and reads French. Answer in simple, short French, no jargon, with tables when comparing; code, commits and docs stay in English.
- Say what was verified and what was not; never round a claim up ([`docs/verification-status.md`](./docs/verification-status.md)). The owner tests by clicking in the UI.
- Evaluation is strict: fix the cases and the acceptance criteria before measuring, report strict and tolerant scores, never put an eval question or gold value in code or prompts, and do not tune a constant on Chinook, Pagila or LiveSQLBench without saying so. Verify in depth only what changes the engine's answers. Announce the cost (time, model calls) of any protocol over about 15 minutes. Log every experiment, failures included, in [`docs/experiments.md`](./docs/experiments.md).
- Merge only with the owner's explicit OK. Ask before an Alembic downgrade, a database restore, or deleting anything not merged. Never print `.env`.
- Use `git add <paths>`, never `git add -A`, and work in worktrees (`git worktree add .claude/worktrees/<name> -b <name> origin/main`), not by switching the main tree's branch.

## State

- **`main` is green** and holds the audit fixes, the conversation-aware evaluation protocol and frozen sets on three databases (Chinook, Pagila, an invented rental company), read-only hardening, recorded-model CI checks, an admin audit log, and the first two slices of learned terms (tables, rules, API, capture, review page), all hidden behind flags.
- **Open drafts, flags off, none merged because none passed its gate:**
  - #112 answerability check (refuse what the data cannot answer). Version 1 was measured against criteria written first and rejected (E36): it refused every unanswerable question but also answerable ones. Version 2 is written, never run; fresh blind sets for it are in `answerable_heldout.json` and `unanswerable_rentals.json`.
  - #115 soft-delete hint (the dominant failure on the rental database, E37). Never measured.
  - #117 record of which knowledge the model says it applied. Never measured.
  - #62 semantic contract, parked since 2026-11-15 (needs a measurement and an `alembic merge`).
  A draft is merged only after its gate says ACCEPT. The full criteria and reports of the first gate were kept outside the repository, in `HomeLab/lexis-evals/archive/`.
- **The owner's stack** runs the backend and ingestion images built from `main` eef2c54b and the frontend image built from the same commit (2026-11-16): it lacks everything merged after that. The internal token is set in `.env`; the configuration rows are `clarification_enabled` and `semantic_compilation_enabled`. Rollback tags: `auto-ontology:pre-answerability` (the running one), `pre-phase2`, `pre-rebuild`, `pre-token`. Dumps are in `HomeLab/lexis-backups/`. Models come from the owner's LiteLLM gateway; stay at or below 12 concurrent chats per IP.
- **Deploying current `main`** applies two additive Alembic migrations (`157f86888f41` knowledge tables, `452f4d72c1f5` audit log); after that an older image refuses the database. Take a dump, tag the running images, build the backend from a clean worktree of `main`, stop the stack and build the frontend image alone, then `docker compose up -d --no-build` and check `/api/health`. CLAUDE.md asks one live trial for anything crossing the worker/server boundary, and it is owed for the clarification capture: enable `knowledge_items_enabled` for one trial, answer a clarification with `python -m dev_tools.evals conversation run`, check that a personal draft appears on the review page and a `knowledge.*` row in the audit log.
- **Owed by the owner:** a click-through of the web app (sign in, a question, the database line and notes, the error screens).

### Known limits (evidence in `docs/experiments.md`)

- **Unanswerable questions**: the engine refuses in about 13% of runs and otherwise answers another question (E27, E36).
- **Soft-deleted rows** are ignored, which costs about half the score on the rental database (E37).
- **Clarification** (flag `clarification_enabled`): option labels change between conversations, and it sometimes asks about a precise question when no database is selected; the skip threshold for certified definitions (0.62) cannot be tuned without real data (E31).
- The **"used" mark** under answers is a text heuristic, often undecided.
- Everything measured comes from public or invented databases; the owner has no real questions yet, so no result says how the engine does on a company's data.

## Running the stack (Windows host, Docker Desktop)

- Services: frontend :3000, backend :3001, ingestion :3002, Postgres :5432, pgAdmin :5050. Start with `docker compose up -d --no-build` from the main tree (it holds `.env`). Health: `curl http://localhost:3001/api/health`; chat readiness: `/api/health/chat` (with the token).
- **Rollback trap**: an image older than the database's Alembic revision refuses to start. Run the matching `alembic downgrade` from the newer image or restore a dump (`pg_dump -U postgres`); see [`docs/backup-restore.md`](./docs/backup-restore.md).
- Rebuild the backend with `docker build -t auto-ontology:latest .` from a clean worktree (tag a rollback first). Rebuild the frontend with the stack stopped, one image at a time: the Docker VM (7 GB) crashes if a frontend build runs next to it.
- Each concurrent chat spawns a Python subprocess; 18 at once crashed the host. Keep load tests at 8 or fewer, away from builds, and keep the machine awake (a sleep corrupts a run).

## Tests and checks on this machine

- Backend tests run natively with `uv run pytest <files>`; the full suite with Postgres fixtures runs in CI. Generated artefacts (Alembic migrations, DAL snapshots) must be produced on Linux, in Docker (`ghcr.io/astral-sh/uv:python3.12-bookworm`, `uv sync --locked --extra kumo`), against a throwaway pgvector container, never the owner's `postgres`.
- `uvx ruff` and the frontend checks run natively; use `node_modules/.bin/...`, not `npx`. The public OpenAPI spec from `pnpm openapi` writes backslashes on Windows: replace them with `/`, and regenerate both copies (`docs/openapi/auto-ontology-api.json`, `mcp/auto_ontology_mcp/auto-ontology-api.json`).
- A new public DAL function needs an entry in `auto_ontology/dal/tests/dal_surface.json`. CI fails above 3 skipped tests (the opt-in live-engine tests): add to the guard, do not silence it.
- Before pushing, `git ls-files --eol` must show no `i/crlf`; Python scripts that rewrite files must open them with `encoding='utf-8'`. Every new tracked file needs an SPDX header.
- Never put `export MSYS_NO_PATHCONV=1` in a script that passes paths to `python.exe`; set it only for `docker exec` or `docker run` calls with `/app/...` paths. After starting any background measurement, read its log one minute later: an empty token once cost an hour.
- To delete a worktree Windows refuses ("Filename too long"), remove the folder with a literal `\\?\` path in PowerShell, then `git worktree prune`. A `node_modules` junction must be removed with a non-recursive delete, never `rm -rf`.
- GitHub is flaky: retry pushes, check with `git ls-remote`, confirm a merge with `gh pr view --json state`. Docs-only PRs may trigger no CI.

## Where things are documented

`docs/verification-status.md` (what is really verified), `docs/evaluation.md` (harness and rules), `docs/experiments.md` (every measurement), `docs/query-safety.md` (read-only, row-capped SQL), `docs/backup-restore.md`, `docs/conversation-protocol.md`, `docs/design/self-improving-ontology.md` (learned terms), `docs/knowledge-items.md`, `docs/audit-log.md`.
