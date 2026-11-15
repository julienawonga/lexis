<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Lexis semantic contract

Status: experimental v0.1. This is the first implementation slice of the
agent-neutral semantic model. It is not a stable external contract, and
existing catalog rows are not assumed to meet it.

The Pydantic source is [`auto_ontology/semantic/contract.py`](../../auto_ontology/semantic/contract.py).
It can emit JSON Schema through `SemanticModelDocument.model_json_schema()` and
JSON through Pydantic's `model_dump(mode="json")`. Those formats are
independent of MCP, REST, a model provider, or the text-to-SQL implementation.

## Design rules

- A stable opaque ID identifies an object; labels are language-tagged and are
  not identifiers.
- Internal references must resolve to an included object of the expected kind;
  a document cannot silently point an attribute at a missing concept.
- Concept, attribute, relation, metric, dimension, and verified-query objects
  have distinct typed fields. They are not all represented as free-form term
  descriptions.
- Status records epistemic and governance state. Vector similarity and usage
  must never promote an item to certified.
- Scope is explicit. Personal and team scopes require an owner; domain and
  database scopes require their corresponding ID.
- Every item records an actor and activity. Assertion time and evidence are
  captured when available. Certification requires a human reviewer and a
  `human_review` evidence reference.
- Catalog bindings point to physical data by opaque catalog ID, state the role,
  and include a qualified name when available so an agent can interpret the
  mapping. They do not copy credentials or sample values into the model.
- Validity and supersession are represented explicitly so consumers can avoid
  treating stale knowledge as current.

## Persistence and review

- The existing `Term`, `ColumnAttribute`, semantic-FK, and `SqlAttribute` rows
  remain the source for the legacy projection. Their certification flags are
  not enough to manufacture provenance or evidence, so those projected records
  remain `unverified_legacy`.
- Agent-neutral assertions persist separately as full object snapshots with an
  optimistic version, proposal author, review state, reviewer evidence, and
  append-only events. This preserves old catalog data and lets consumers audit
  who proposed and reviewed each contract revision.
- Submit through `POST /api/semantic-model/proposals`, inspect with `GET
  /api/semantic-model/proposals`, then approve or reject through `POST
  /api/semantic-model/proposals/{proposal_id}/review`. A different authenticated
  editor must approve with a `human_review` evidence reference.
- Approved snapshots overlay the matching object from `GET
  /api/semantic-model`. The service hashes the legacy source projection when a
  proposal is submitted; a later source change changes the visible status to
  `needs_revalidation` rather than silently presenting the old approval as
  current.
- This first review path is database-scoped. Existing physical bindings cannot
  be changed in a proposal, and new objects cannot invent physical bindings.
  The review evidence is a durable reference supplied by the reviewer; Lexis
  does not verify external evidence targets in this version.

## What v0.1 deliberately does not do

- Existing certification flags are not enough to manufacture provenance or
  evidence, so legacy projected records remain `unverified_legacy`.
- The review workflow does not rewrite old Term, attribute, or SQL-attribute
  rows and does not change the text-to-SQL planner. An approved snapshot is
  available through the portable contract and MCP `get_semantic_model` only.
- It does not define full metric expression execution semantics or
  database-specific query rules.
- There is no browser review UI, owner/group-scoped review policy, support for
  shared-scope edits, or automated verification of external evidence refs.
- MCP `get_semantic_model` stays read-only. Proposal writes go through the
  authenticated Next.js `/api/...` routes; legacy flag updates are not a
  substitute for review.
- Existing model interchange omits some source fields. The semantic export
  projection reads synonyms, ontology language, certification flags, and SQL
  attribute source directly from their DAL rows. Certification flags are
  exposed separately as `legacy_certification`; they do not upgrade the
  object's status because the old rows lack evidence and reviewer provenance.
- When one term spans databases with different ontology languages, its label
  language is `und` rather than choosing one database's language arbitrarily.

The first adapter projects concepts, column attributes, uniquely-resolvable
semantic foreign-key relations, and SQL attributes. It does not label SQL
attributes as metrics: the existing model does not establish their grain, unit,
or metric semantics. It omits custom analyses because the existing interchange
model does not say whether they are verified queries. Ambiguous source-term
relations are omitted rather than guessed.

The `0.1` version is intentionally provisional. Before widening persistence or
publishing this as a stable external API, review object types, metric grain and
unit semantics, relation direction/cardinality, multilingual labels, shared
scope rules, query-planner integration, and compatibility policy against
representative business models. The next large step is to make the reviewed
contract a source the query planner can consume, then measure cross-agent
interpretation against a versioned evaluation set.
