# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end governance flow against an isolated Postgres.

Run with the repo venv and POSTGRES_* pointing at the isolated container::

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_USER=e2e \
    POSTGRES_PASSWORD=... POSTGRES_DATABASE=auto_ontology \
    uv run --no-sync python wt-53-tmp/e2e_semantic_governance.py

Covers: base projection -> proposal by user A -> independent approval by
user B -> certified readback -> source drift -> needs_revalidation ->
rejection path -> self-approval refusal -> append-only event enforcement.
"""

from __future__ import annotations

import logging
import sys

import psycopg
import yaml
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("e2e")

DB_NAME = "retail"
USER_A = "user-alice"  # submitter
USER_B = "user-bob"  # independent reviewer


def _conn_str() -> str:
    from auto_ontology.infra.postgres import get_postgres_connection_string

    return get_postgres_connection_string()


def seed_frontend_users() -> None:
    """The Better Auth `frontend."user"` table is created by the Next stack;
    on this isolated DB we recreate the minimal shape the permission check reads."""
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
    """The importer assigns fresh ids; read back the one real term row."""
    with psycopg.connect(_conn_str()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM term WHERE name = 'Order'")
        (term_id,) = cur.fetchone()
    return term_id


def client() -> TestClient:
    from auto_ontology.server.__main__ import create_app

    return TestClient(create_app())


def main() -> int:
    seed_frontend_users()
    import_minimal_model()
    c = client()

    # -- 1. Base readback: the term projects as unverified_legacy -------------
    term_id = _term_id()
    r = c.get("/api/semantic-model", params={"database_name": DB_NAME})
    r.raise_for_status()
    base = r.json()
    concept = next(o for o in base["objects"] if o["id"] == term_id)
    assert concept["status"] == "unverified_legacy", concept["status"]
    assert concept["kind"] == "concept"
    log.info("[1] base projection is unverified_legacy: OK")

    # -- 2. User A proposes a revised definition ------------------------------
    proposal_obj = dict(concept)
    proposal_obj["definition"] = "A customer order submitted at checkout."
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
    proposal = r.json()["data"]
    pid = proposal["id"]
    assert proposal["state"] == "in_review", proposal
    log.info("[2] proposal %s created by A: OK", pid)

    # -- 3. Self-approval by A must be refused --------------------------------
    r = c.post(
        f"/api/semantic-model/proposals/{pid}/review",
        json={
            "database_name": DB_NAME,
            "decision": "approve",
            "evidence": [{"kind": "human_review", "reference": "rev-self"}],
            "comment": "self",
        },
        headers={"x-auto-ontology-user-id": USER_A},
    )
    assert r.status_code == 409, (r.status_code, r.text)
    log.info("[3] self-approval refused with 409: OK")

    # -- 4. Approval without human_review evidence must fail ------------------
    r = c.post(
        f"/api/semantic-model/proposals/{pid}/review",
        json={
            "database_name": DB_NAME,
            "decision": "approve",
            "evidence": [{"kind": "ticket", "reference": "no-review"}],
            "comment": "no evidence",
        },
        headers={"x-auto-ontology-user-id": USER_B},
    )
    assert r.status_code == 422, (r.status_code, r.text)
    log.info("[4] approval without human_review evidence refused: OK")

    # -- 5. Independent approval by B, then certified readback ----------------
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
    reviewed = r.json()["data"]
    assert reviewed["state"] == "approved", reviewed
    r = c.get("/api/semantic-model", params={"database_name": DB_NAME})
    r.raise_for_status()
    concept = next(o for o in r.json()["objects"] if o["id"] == term_id)
    assert concept["status"] == "certified", concept["status"]
    assert concept["definition"] == "A customer order submitted at checkout."
    assert concept["provenance"]["actor_id"] == USER_B
    assert concept["provenance"]["activity"] == "semantic_review"
    assert any(
        e["kind"] == "human_review" and e["reference"] == "review-42"
        for e in concept["provenance"]["evidence"]
    )
    log.info("[5] certified overlay readback with B's provenance: OK")

    # -- 6. Source drift -> needs_revalidation --------------------------------
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
    log.info("[6] source drift surfaces needs_revalidation: OK")

    # -- 7. Rejection path ----------------------------------------------------
    proposal_obj["definition"] = "Second attempt."
    r = c.post(
        "/api/semantic-model/proposals",
        json={
            "database_name": DB_NAME,
            "object": proposal_obj,
            "evidence": [],
            "comment": "Second proposal.",
        },
        headers={"x-auto-ontology-user-id": USER_A},
    )
    r.raise_for_status()
    pid2 = r.json()["data"]["id"]
    r = c.post(
        f"/api/semantic-model/proposals/{pid2}/review",
        json={
            "database_name": DB_NAME,
            "decision": "reject",
            "evidence": [],
            "comment": "Wrong grain.",
        },
        headers={"x-auto-ontology-user-id": USER_B},
    )
    r.raise_for_status()
    assert r.json()["data"]["state"] == "rejected", r.json()
    r = c.get("/api/semantic-model", params={"database_name": DB_NAME})
    r.raise_for_status()
    concept = next(o for o in r.json()["objects"] if o["id"] == term_id)
    assert concept["status"] == "needs_revalidation", concept["status"]
    log.info("[7] rejection keeps the prior state (no silent overlay): OK")

    # -- 8. Event history is append-only (DB-level enforcement) ---------------
    with psycopg.connect(_conn_str()) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT event_type, actor_id FROM semantic_governance_event "
            "ORDER BY created"
        )
        events = cur.fetchall()
    kinds = [e["event_type"] for e in events]
    assert kinds == ["proposed", "approved", "proposed", "rejected"], kinds
    assert all(e["actor_id"] in (USER_A, USER_B) for e in events)
    try:
        with psycopg.connect(_conn_str()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM semantic_governance_event")
        raise AssertionError("event DELETE should have been rejected by the trigger")
    except psycopg.errors.RaiseException:
        log.info("[8] events are append-only (%s), DELETE rejected: OK", kinds)

    # -- 9. Proposal deletion is structurally impossible (cascade x trigger) --
    try:
        with psycopg.connect(_conn_str()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM semantic_proposal")
        raise AssertionError("proposal DELETE should have failed via event cascade")
    except psycopg.errors.RaiseException:
        log.info("[9] proposal deletion blocked by append-only events: OK")

    log.info("E2E governance flow: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
