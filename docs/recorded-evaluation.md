<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Recorded-model regression check

A few frozen questions are run through the real pipeline in CI with the model
replaced by a recording ("cassettes"). It needs no model and no secret, and it
fails when a change alters what the pipeline sends to the model or what it does
with the answers.

## What it does and does not prove

It catches:

- a prompt, a retrieved table or column, a model parameter or a request shape that
  changed (the request is no longer in the cassettes: a *miss*, with the hash and
  a diff against the nearest recorded request);
- the pipeline doing something different with the same model answers: another
  SQL at the end, or another sequence of graph steps.

It does **not** prove:

- anything about model quality. The answers are the ones recorded once; a replayed
  pass says nothing about a new model, a new prompt that was re-recorded, or a
  question that was not recorded;
- that the ontology or semantic layer helps. The recorded flow ingests the
  catalog and embeds it (the raw schema is retrieved), it does not compile a
  semantic layer;
- any measurement. It is a golden-file test, not an evaluation: use
  [`evaluation.md`](./evaluation.md) for that.

Cassettes contain the prompts, so they are recorded **for the public fixture
databases only** (Pagila, Chinook). Never record against a real company database.

## How it works

`auto_ontology/utils/cassette.py` wraps the transport of the shared HTTP client
that every chat, embedding and rerank call goes through. Two environment
variables, both off by default (unset changes nothing):

| Variable | Meaning |
|---|---|
| `LLM_CASSETTE_MODE` | `record`: forward to the real endpoint and store each exchange. `replay`: never touch the network, answer from disk, fail on a miss. |
| `LLM_CASSETTE_DIR` | The directory of cassette files (one `<hash>.json` per request). |

**Secrets.** Request headers are never stored, so neither `Authorization` nor an
API key can be written; of the response only `content-type` is kept. As a second
line of defence every secret the process knows (the bearer token, any
environment variable with KEY, TOKEN or SECRET in its name) is replaced by
`<redacted>` if it appears anywhere in a cassette. `test_cassette.py` proves it
with a fake key and a server that echoes it back. Before committing, glance at
`git diff --stat` anyway.

**Request identity.** The hash covers the method, the URL path (not the host) and
the JSON body, normalized:

- the current date and time is removed: any `YYYY-MM-DD hh:mm:ss[.ffffff]` or
  `...T...Z` inside a string becomes `<DATETIME>`. This matters because
  `retrieval/text_to_sql/main.py` formats `datetime.now()` into the main system
  prompt, and the catalog writes timestamps that can reach a prompt. A bare date
  such as `2022-05-24` is kept (it is usually data);
- UUIDs inside strings become `<UUID>` (ids minted at each ingestion);
- the top-level keys `user`, `request_id`, `trace_id`, `session_id` are dropped;
- keys are sorted.

Everything else counts, which is the point. Two identical requests (a retry) are
replayed in the order they were recorded, then the last one repeats.

Streaming responses are buffered when recorded and replayed as one body.

## Recording the first set (maintainer, once)

Use a throwaway Postgres with the `pagila` fixture loaded, not the running stack:
the recording runs ingestion, which rewrites the catalog and vector store of the
database it points at. Nothing needs to run in a container; the script calls the
pipeline in-process.

1. Prepare the database as CI does (`docker compose up -d postgres`, then
   `uv run --no-sync python -m dev_tools.fixtures.seed_fixtures` and
   `uv run --no-sync alembic upgrade head`) with `POSTGRES_*` pointing at it.
2. Export the real model configuration the stack uses: `REASONING_ENDPOINT`,
   `REASONING_API_KEY`, `REASONING_MODEL` (and the same for `NON_REASONING_*`,
   `EMBED_*`, `RERANK_*` if you use them, `EMBED_DIMENSIONS`).
3. Create the manifest `dev_tools/cassettes/pagila_smoke/manifest.json` naming
   cases of a frozen file by id (never copying the question):

   ```json
   {
     "database": "pagila",
     "cases_file": "pagila.json",
     "case_ids": ["pagila.top5_films_revenue"]
   }
   ```

   Pick three to five ids from `dev_tools/evals/cases/pagila.json`, covering a
   join, an aggregate and a ranking. Do not use them to judge a change: this
   check is not an evaluation.
4. Record:

   ```bash
   uv run --no-sync python -m dev_tools.cassettes.run_set --set pagila_smoke --mode record
   ```

   This deletes any old cassette of the set, runs ingestion (embeddings are
   recorded) and each question (chat calls are recorded), then writes the SQL and
   the graph steps of each question and the non-secret model names into the
   manifest. It exits non-zero if a question failed.
5. Check it replays offline before committing:

   ```bash
   LEXIS_REPLAY_PIPELINE=1 uv run --no-sync pytest dev_tools/cassettes -q
   ```

6. `git add dev_tools/cassettes/pagila_smoke` and commit. The CI step runs the
   same command as step 5 as soon as a `manifest.json` exists.

## When a change makes the check fail

A failure `No recorded response for POST /v1/chat/completions (request hash ...)`
followed by a diff means the request differs from the recorded one. Read the diff:

- If it is the change you meant to make (a prompt edit, a new retrieval field),
  re-record on purpose with the command of step 4, review the cassette diff like
  a golden file, and commit it with the change. Say in the pull request that the
  cassettes were re-recorded and why.
- If it is not (a stray whitespace, a date format, an id), it is a regression of
  prompt construction: fix the code, or, if the new value is volatile by nature,
  extend the normalization in `cassette.py` with a test.

A failure `SQL changed` or `graph steps changed` means the same model answers led
the pipeline somewhere else.

## Wiring in CI

`dev_tools/cassettes/tests/test_recorded_pipeline.py` always runs in the normal
suite (manifests valid, cassettes parse, no credential shape in them). With no
cassette committed it **passes with a printed note** rather than skipping, so it
does not count toward the guard that fails CI above three skipped tests. A
dedicated step after the suite sets `LEXIS_REPLAY_PIPELINE=1` and runs the real
replay when a set exists; it comes after the suite because it re-ingests the
fixture database into the CI Postgres.

## Status

The mechanism is tested with a fake model server (`httpx.MockTransport`) through
the real chat, embedding and rerank call sites
(`auto_ontology/utils/tests/test_cassette.py`). **No real cassette has been
recorded**, and the in-process pipeline run (`run_set`) has not been executed
end to end yet: it is first exercised when the maintainer records. Register row:
[`verification-status.md`](./verification-status.md), level FAKES.
