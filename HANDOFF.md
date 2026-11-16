<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Maintainer handoff (state at 2026-11-16, evening)

For whoever continues the work (a new maintainer or another coding agent).
Read [`CLAUDE.md`](./CLAUDE.md) first: it holds the build, lint and PR rules.
This file adds the project's state, its working rules and its traps.
The user-facing roadmap is in the [README](./README.md#️-roadmap); the plan
below is the same list with the detail a maintainer needs. A ready-to-use goal
prompt for the next agent is in [`GOAL.md`](./GOAL.md).

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
- The owner dislikes walls of "test and verification" wording. Verify in depth
  only what changes the engine's answers (prompts, retrieval, candidate
  preparation, validation); for the rest, one real try by the owner is enough.
  Say what a protocol will cost (time, model calls) before starting one over
  about fifteen minutes, and say what it will teach.
- The owner fears calibrating the project on the public benchmarks (Chinook,
  Pagila, LiveSQLBench). Frozen questions guard against tuning after seeing
  results, not against fitting the shape of those databases. Do not tune a
  constant on them without saying so; real data is the missing ingredient.
- Log every experiment, failures included, in `docs/experiments.md` (E-numbers),
  for the owner's future presentation.

## Current state

- `origin/main` = `2a3a9e2f` (PR #84). Merged on 2026-11-16: #79 (docs, E27 to
  E29), #81 (a one-row result with more than four values is a table, not four
  clipped tiles), #80 (E30), #82 (a clarification option pins the answer to its
  database), #83 (CLAUDE.md traps), #84 (README roadmap rewritten in plain terms).
  All workflows were green after each merge.
- The local stack (Docker compose project `auto-ontology`) runs an image built
  from `main`. Alembic head `d04a88c1b790`. No rollback image is kept for it;
  keep one before any redeploy.
- **Open, parked:** PR #62 (semantic contract, draft, branch
  `codex/semantic-contract`: needs a measurement and an `alembic merge`). Branch
  `answerability` is pushed, not merged (E27, E29): it flags unanswerable
  questions (24 of 24) with no false alarm on 14 controls, but flags 52% of
  answerable LiveSQLBench tasks, which fails its frozen criterion 5.
- Backups of discarded work: `HomeLab/lexis-evals/backups/` (outside the repo):
  patches of the old `internal-auth`, `answer-used` (the start of roadmap
  step 7, to redo from `main`) and `map-domains`, the dropped rename stash, and
  `local-only-branches.bundle` (three old experiment branches).

### Known limits (evidence in `docs/experiments.md`)

- **Clarification** (flag `clarification_enabled`, E31): the offered labels
  change from one conversation to the next (14 distinct sets over 20 runs on
  `main`, 12 on the candidate); on fully specified Chinook questions with no
  database selected ("How much did we sell in 2023?", "top 5 countries by
  sales") the engine asks 3 times out of 3 on both versions, not investigated;
  the skip threshold for certified definitions (0.62) sits inside the range of
  unrelated questions (0.55 to 0.64 against 0.38 to 0.46 for related ones, one
  metric only), left alone because it cannot be tuned without real data.
- **The evaluation harness is stateless** (no `conversation_id`), so it cannot
  reach anything that needs a conversation, such as clarification. The protocol
  used for E31 (probe and report scripts, frozen questions) lives in
  `HomeLab/lexis-evals/clarification/`, outside the repo; it should move into
  `dev_tools/evals`.
- **Unanswerable questions:** on Chinook, of 28 runs, 4 refused cleanly and 21
  answered another question (E27). Not solved.
- **API authentication** (internal token) has never been tried live: it needs a
  stack restart with `INTERNAL_API_TOKEN` set.
- **"Used" mark** under answers is a text heuristic that is often undecided
  (roadmap step 7).
- Quality of the generated domain names is not graded.
- Everything measured so far comes from public test databases. The owner has no
  real questions to provide, so roadmap step 6 is skipped, and no result says
  how the engine does on a company's own data.

## Plan, in order

1. Audit first (read only): list the limits of the engine and the frontend with
   evidence, ranked by severity and cost. See [`GOAL.md`](./GOAL.md).
2. Make it operational: one documented way to deploy from scratch, health checks,
   clear errors, no crash under the load limit, API authentication tried live,
   backup and restore documented, the main frontend paths free of errors.
3. Make the engine robust, one cause at a time, each change through the
   evaluation gate in `CLAUDE.md`.
4. Improve the evaluation without fitting it to the public benchmarks: bring
   the conversation-aware protocol into the repo, add held-out sets on more
   databases, reduce noise (repeats, paired tests), keep a regression history.
5. Then the roadmap in the README, in order: metrics people can trust (step 5),
   what each answer used (7), learned terms (8), review and promotion (9),
   team features (10), database-enforced read-only on four engines (11), checks
   in CI (12).
6. Later: "Variant E" (user documents turned into ontology Terms rather than
   plain RAG); the items under "Later" in the README.

## Running the stack (Windows host, Docker Desktop)

- Services: frontend :3000, backend :3001, ingestion :3002, Postgres :5432,
  pgAdmin :5050. Start: `docker compose up -d --no-build` from the main tree
  (it holds `.env`; never print `.env` secrets). Health:
  `curl http://localhost:3001/api/health`.
- Models come from the owner's LiteLLM gateway (chat `openai/gpt-6-luna`,
  embeddings `text-embedding-005` at 768 dimensions, a Cohere rerank). The
  gateway rate-limits: stay at or below 12 concurrent chats per IP.
- The images tagged `:latest` are built from `main` (2026-11-16). Tag a rollback
  before every redeploy (`docker tag auto-ontology:latest auto-ontology:pre-<x>`).
- **Rollback trap:** an image older than the database's Alembic revision
  (`d04a88c1b790`) crashes at start on the unknown revision. Run the matching
  `alembic downgrade` from the newer image, or restore a dump from
  `HomeLab/lexis-backups` (`pg_dump -U postgres`; the role is `postgres`). Ask
  the owner before any downgrade or restore.
- Rebuild the backend: `docker build -t auto-ontology:latest .` from a clean
  worktree (tag a rollback first). Rebuild the frontend: `docker compose stop`,
  build one image at a time from `frontend/`, then `up -d --no-build`. The
  Docker VM crashes if a frontend build runs next to the stack (`.wslconfig`
  limits it to 7 GB).
- Load limit: each concurrent chat spawns a Python subprocess; 18 at once
  crashed the host. Keep load tests at 8 or fewer, away from builds.

## Tests and checks on this machine

- `uv sync` used to fail on Windows (a dependency needs MSVC). On 2026-11-16
  `uv run pytest <files>` and `uv run python -m dev_tools.generate_backend_openapi`
  worked natively for the backend files touched that day; the full suite with
  Postgres fixtures runs in CI. If native fails, run in Docker:
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
- Bash on Windows rewrites `/app/...` style paths given to `docker exec` and
  `docker run`: set `MSYS_NO_PATHCONV=1`. Subprocess output from Docker needs
  `encoding='utf-8', errors='replace'` in Python.
- `git worktree remove` can fail with "Filename too long" or "Permission denied"
  on Windows: delete the folder with a literal `\\?\` path in PowerShell, then
  `git worktree prune`. Check `git status` and unpushed commits before deleting.
- Docs-only pull requests trigger no CI workflow (path filters); GitHub then
  shows no checks, and the merge state is `CLEAN`.

## Where things are documented

`docs/verification-status.md` (what is really verified, one row per
capability), `docs/evaluation.md` (harness rules), `docs/query-safety.md`
(read-only, row-capped agent SQL), `docs/exploration-map.md`,
`docs/design/self-improving-ontology.md` (design of learned terms),
`docs/experiments.md` (measurements log).
