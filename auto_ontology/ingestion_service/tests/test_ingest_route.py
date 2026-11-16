# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""``POST /ingest`` refuses a connection it could not look up."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_ontology.ingestion_service import router as ingest_router


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(ingest_router, "trigger_ingest", calls.append)
    return calls


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ingest_router.router)
    return TestClient(app)


@pytest.mark.parametrize(
    "body", [{}, {"database": ""}, {"database": "   "}, {"host": "h"}]
)
def test_a_connection_without_a_database_name_is_refused(
    started: list[dict], body: dict
) -> None:
    response = _client().post("/ingest", json=body)

    assert response.status_code == 422
    assert "database" in response.json()["detail"]
    assert started == []


def test_a_named_connection_is_accepted(started: list[dict]) -> None:
    response = _client().post("/ingest", json={"database": "pagila"})

    assert response.status_code == 202
    assert started == [{"database": "pagila"}]
