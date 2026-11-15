# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""E2E: an approved semantic object reaches the planner, stale ones do not.

Run with the repo venv and POSTGRES_* pointing at an isolated, migrated
container (same setup as ``dev_tools/e2e_semantic_governance.py``, whose full
governance lifecycle this script deliberately does not repeat)::

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_USER=e2e \
    POSTGRES_PASSWORD=... POSTGRES_DATABASE=auto_ontology \
    uv run --no-sync python -m dev_tools.e2e_semantic_planner

Covers the planner-consumption acceptance slice: with the flag off nothing
changes; after independent approval the certified concept is rendered into the
planner block with its id and definition; after a source edit the demoted
object no longer reaches the block until revalidated.
"""

from __future__ import annotations

import logging
import sys

import psycopg
import yaml
from fastapi.testclient import TestClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("e2e")

DB_NAME = "retail"
USER_A = "user-alice"
USER_B = "user-bob"
DEFINITION = "A customer order submitted at checkout."


def _conn_str() -> str:
    from auto_ontology.infra.postgres import get_postgres_connection_string

    return get_postgres_connection_string()


def seed_frontend_users() -> None:
    with psycopg.connect(_conn_str(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS frontend")
        cur.execute('CREATE TABLE IF NOT EXISTS frontend."user" (id text primary key)')
        cur.execute('ALTER TABLE frontend."user" ADD COLUMN IF NOT EXISTS role text')
        for user_id in (USER_A, USER_B):
            cur.execute(
                'INSERT INTO frontend."user" (id, role) VALUES (%s, %s) '
                "ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role",
                (user_id, "admin"),
            )
    log.info("seeded users %s / %s", USER_A, USER_B)


def import_minimal_model() -> None:
    from auto_ontology.dal.model_interchange import assemble_export_document
    from auto_ontology.server.model_interchange import service as model_service

    catalog = [
        {
            "db_id": "db-1",
            "db_name": DB_NAME,
            "schema_id": "sch-1",
            "schema_name": "main",
            "table_id": "tbl-1",
            "table_name": "orders",
            "table_description": "Orders table",
            "pk": ["id"],
            "table_type": "table",
            "column_id": "col-1",
            "column_name": "id",
            "column_description": "",
            "column_type": "INTEGER",
            "sample_values": '["1", "2"]',
            "is_unique": True,
            "is_nullable": False,
            "ordinal_position": 1,
        },
    ]
    rows = {
        "catalog": catalog,
        "foreign_keys": [],
        "joins": [],
        "terms": [
            {
                "id": "term-1",
                "name": "Order",
                "description": "An order",
                "represents": ["tbl-1"],
                "columns_attributes": [
                    {
                        "id": "attr-1",
                        "name": "order id",
                        "description": "",
                        "column_id": "col-1",
                    },
                ],
            },
        ],
        "semantic_fks": [],
        "sql_attributes": [],
        "custom_analyses": [],
    }
    document = assemble_export_document(
        rows,
        dialect_by_db_name={DB_NAME: "sqlite"},
        sql_column_resolver=lambda _sql, _db: [],
    )
    yaml_text = yaml.safe_dump(document.model_dump(mode="python"), sort_keys=False)
    summary = model_service.import_model(yaml_text, replace=True, embed=False)
    log.info("imported model: %s", summary)


def _term_id() -> str:
    with psycopg.connect(_conn_str()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM term WHERE name = 'Order'")
        (term_id,) = cur.fetchone()
    return term_id


def client() -> TestClient:
    from auto_ontology.server.__main__ import create_app

    return TestClient(create_app())


def approve_certified_concept(c: TestClient) -> str:
    """Propose a revised definition (A) and approve it independently (B)."""
    term_id = _term_id()
    r = c.get("/api/semantic-model", params={"database_name": DB_NAME})
    r.raise_for_status()
    concept = next(o for o in r.json()["objects"] if o["id"] == term_id)
    proposal_obj = dict(concept)
    proposal_obj["definition"] = DEFINITION
    r = c.post(
        "/api/semantic-model/proposals",
        json={
            "database_name": DB_NAME,
            "object": proposal_obj,
            "evidence": [],
            "comment": "Clarified the business definition.",
        },
        headers={"x-auto-ontology-user-id": USER_A},
    )
    r.raise_for_status()
    pid = r.json()["data"]["id"]
    r = c.post(
        f"/api/semantic-model/proposals/{pid}/review",
        json={
            "database_name": DB_NAME,
            "decision": "approve",
            "evidence": [{"kind": "human_review", "reference": "review-42"}],
            "comment": "Matches the finance definition.",
        },
        headers={"x-auto-ontology-user-id": USER_B},
    )
    r.raise_for_status()
    assert r.json()["data"]["state"] == "approved", r.json()
    log.info("proposal %s approved by the independent reviewer: OK", pid)
    return term_id


def main() -> int:
    import os

    from auto_ontology.retrieval.text_to_sql import semantic_contract as sc

    # The agent wiring reads the flag from the environment; the whole point of
    # this run is to measure the flag-on path.
    os.environ["SEMANTIC_CONTRACT_BLOCK"] = "1"

    seed_frontend_users()
    import_minimal_model()
    c = client()
    term_id = approve_certified_concept(c)
    settings = sc.SemanticContractSettings(enabled=True, budget_chars=2000)

    # -- 1. Flag off: the planner evidence path is unchanged ------------------
    assert (
        sc.build_semantic_contract_block(
            DB_NAME, sc.SemanticContractSettings(enabled=False, budget_chars=2000)
        )
        is None
    )
    log.info("[1] flag off -> no block, planner behavior unchanged: OK")

    # -- 2. Flag on: the certified concept reaches the planner block ----------
    found = sc.build_semantic_contract_block(DB_NAME, settings)
    assert found is not None, "a certified object must reach the planner block"
    assert [o.id for o in found.objects] == [term_id], found.objects
    assert "certified" not in found.block  # status is the filter, not prompt text
    assert DEFINITION in found.block
    assert term_id in found.block
    log.info("[2] certified object in the planner block with id+definition: OK")

    # -- 3. The wiring merges it into the evidence ----------------------------
    from auto_ontology.retrieval.text_to_sql.agents.candidates_retrieval import (
        CandidateRetrievalAgent,
    )

    agent = object.__new__(CandidateRetrievalAgent)
    agent.logger = logging.getLogger("e2e.planner")
    merged = agent._with_semantic_contract("request evidence", DB_NAME)
    assert merged is not None
    assert merged.startswith("request evidence\n\n" + sc.BLOCK_HEADER)
    assert DEFINITION in merged
    log.info("[3] certified block merged into the planner evidence: OK")

    # -- 4. Source drift: the demoted object leaves the block -----------------
    with psycopg.connect(_conn_str(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE term SET description = 'An order (edited)' WHERE id = %s",
            (term_id,),
        )
        assert cur.rowcount == 1
    r = c.get("/api/semantic-model", params={"database_name": DB_NAME})
    r.raise_for_status()
    concept = next(o for o in r.json()["objects"] if o["id"] == term_id)
    assert concept["status"] == "needs_revalidation", concept["status"]
    assert sc.build_semantic_contract_block(DB_NAME, settings) is None, (
        "a demoted object must not reach the planner"
    )
    assert agent._with_semantic_contract("request evidence", DB_NAME) is None
    log.info("[4] source drift -> needs_revalidation -> block empty: OK")

    log.info("E2E planner-consumption slice: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
