<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Lexis

Full-stack repo: Next.js frontend (`frontend/`) and FastAPI backend (`auto_ontology/`).
This file is for maintainers. Agent skills for users and partners start at [`AGENTS.md`](./AGENTS.md); frontend rules are in [`frontend/CLAUDE.md`](./frontend/CLAUDE.md).

## Run (from the repo root)

| Command | What |
|---|---|
| `uv run uvicorn auto_ontology.server.__main__:create_app --factory --reload --host 127.0.0.1 --port 3001` | API on :3001 with reload |
| `uv run python -m auto_ontology.server` | API without reload (what the container runs) |
| `uv run python -m auto_ontology.ingestion_service` | Ingestion service on :3002 |

## Backend rules

- **The store is Postgres**, queried with SQLAlchemy Core (no ORM) in `auto_ontology/dal/`. `dal/schema.py` is the source of truth for the schema (read its comments before changing a table). Schema changes go through Alembic autogenerate, never by editing an applied migration.
- **Lint and format**: `uv run ruff check auto_ontology/` and `uv run ruff format auto_ontology/` before committing.
- **Dependencies**: `uv add`, never pip, never by hand in `pyproject.toml`.
- **API**: all routes under `/api/`; type hints on every signature; `@app.exception_handler` functions are plain `def`.

## Working with the owner

- The owner reads French: answer in simple, short French, with a table when comparing; code, commits and docs stay in English.
- Say what was verified and what was not; never claim more than the evidence. Merge only with the owner's explicit OK, and ask before anything destructive (an Alembic downgrade, a database restore, deleting unmerged work). Never print `.env`.
- Announce the cost (time, model calls) of any measurement over about 15 minutes, and what it will teach. Use `git add <paths>`, never `git add -A`, and work in worktrees (`git worktree add .claude/worktrees/<name> -b <name> origin/main`), not by switching the main tree's branch.

## The owner's machine (Windows, Docker Desktop)

- **Deploying** applies Alembic migrations at start, after which an older image refuses the database ([`docs/backup-restore.md`](./docs/backup-restore.md)): dump first, tag the running images, build the backend from a clean worktree, and build the frontend image **with the stack stopped** (the 7 GB Docker VM crashes otherwise).
- **Generated artefacts** (Alembic migrations, DAL snapshots, the public OpenAPI spec) are produced on Linux in Docker against a throwaway pgvector container, never the owner's `postgres` one. Before pushing, `git ls-files --eol` must show no `i/crlf`.
- **Measurements**: at most 8 concurrent chats (4 workers), the machine kept awake (a sleep corrupts a run), and read the log one minute after starting a background run. Never put `export MSYS_NO_PATHCONV=1` in a script that gives paths to `python.exe`.
- Remove a `node_modules` junction with a non-recursive delete, never `rm -rf`; a worktree Windows refuses to delete needs a literal `\?\` path in PowerShell, then `git worktree prune`.

## Git

- Concise imperative commit messages. Add a `Co-Authored-By: Claude <model name> <noreply@anthropic.com>` trailer, naming the model that wrote it, only on commits Claude mostly wrote. Branch from `main`.
- **A PR is done when every GitHub Actions workflow is green.** Poll `gh pr checks <n>`, fix, push, repeat, and report the final state honestly. Always pass `--repo julienawonga/lexis` to `gh`.
- Run the CI gates first:

| Check | Command |
|---|---|
| Ruff | `uv run ruff check auto_ontology/ && uv run ruff format --check auto_ontology/` |
| Pytest | `uv run pytest auto_ontology dev_tools -q` |
| OpenAPI | `uv run python -m dev_tools.generate_backend_openapi` |
| Frontend | `cd frontend && npx prettier --check . && pnpm lint && pnpm build` |

The committed `docs/openapi/*.json` embed each route's docstring: change a route's code or docs, regenerate and commit.

Traps:

- On Windows the OpenAPI generator can rewrite the specs with CRLF and an empty content diff: restore with `git checkout -- docs/openapi`.
- `test_dal_surface[sql_fragments]` can fail locally while CI passes: trust CI, never edit `dal_surface.json` to silence it.
- Fakes do not cover the worker-to-server boundary (PR #82 lost a clarification option there). Give anything that crosses it one live trial on the stack and log the result.

## Changing the text-to-SQL engine

A change to what the model sees or how its SQL is built (prompts, retrieval, candidate preparation, validation, the ontology) is judged by measurement, not by CI. Put it behind a flag, write the acceptance criteria **before** the first run, and merge only on an `ACCEPT`:

```bash
python -m dev_tools.evals run --label candidate --out candidate.json
python -m dev_tools.evals compare baseline.json candidate.json --margin 0.02
```

[`docs/evaluation.md`](./docs/evaluation.md) has the commands and the rules: fix the cases before measuring, use the same cases file for both sides, report strict and tolerant scores, keep the semantic index populated. Never put an eval question, expected value or gold literal in prompts, resources or code, never edit a frozen case file without re-freezing it on purpose, and never tune a constant on a public benchmark without saying so (`python -m dev_tools.integrity` checks the first two in CI).

Record each measurement, failures included, in [`docs/experiments.md`](./docs/experiments.md), and update the row in [`docs/verification-status.md`](./docs/verification-status.md): claim only the level reached (tests with fakes are `FAKES`).

Agent-issued SQL stays read-only and row-capped: read [`docs/query-safety.md`](./docs/query-safety.md) before touching `chat_sql.py`, `sql_guard.py` or a connector's `execute`.
