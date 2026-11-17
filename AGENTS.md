<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# AGENTS.md: Lexis agent entry point

Skills that teach an agent to **set up** Lexis and **use** its ontology layer, in `skills/` (one directory per skill, `ontology-*`). This file is for developers bringing Lexis up and partners embedding it in an agent harness. Maintainer conventions (build, test, schema, frontend) are in [`CLAUDE.md`](./CLAUDE.md): do not fold them into the skills.

## Which skill

- [`skills/ontology-setup/`](./skills/ontology-setup/): Helm (the official install), Compose, developer mode, MCP against a running instance, troubleshooting. Start here when Lexis is not up yet.
- [`skills/ontology-management/`](./skills/ontology-management/): inspect, model, modify and publish glossary terms, SQL attributes, relationships and model YAML. MCP cannot write; this skill covers the approved write paths.
- [`skills/ontology-query/`](./skills/ontology-query/): call Lexis (MCP first, REST fallback), discover meaning, validate SQL, rows and answers. Start here when Lexis is deployed.

The lifecycle is install and readiness, then inspect and model, then staged apply, query validation, governed publication and a fresh readback. A step the product does not support must return an explicit gap, never an invented operation.

## Sources of truth (do not duplicate)

Skills encode workflow, order and pitfalls. They are not a second API catalog or installer.

| Job | Owner |
|---|---|
| Install | `DEPLOYMENT.md` (Helm), `docker-compose.yml`, `dev_tools/setup_env.sh` |
| Live read tools | `mcp/auto_ontology_mcp/tools.py` (the handshake list wins over any skill text) |
| REST shapes and permissions | `docs/openapi/auto-ontology-api.json` |

MCP is read-only by design; writes go through the web app's `/api/...`.

## Skill files

Each skill has `SKILL.md` (its `name:` matches the directory), `skill-card.md`, `evals/evals.json`, and `references/` or `assets/`. `BENCHMARK.md` is inherited from the upstream project and not regenerated: treat its numbers as historical. Rename a skill in all of these together. Skills are public: no staging hostnames, cluster names, Vault paths or credentials.
