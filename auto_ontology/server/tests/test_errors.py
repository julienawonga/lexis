# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""An unplanned error answers as JSON, with an id that is also in the logs."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auto_ontology.server.errors import INTERNAL_ERROR_DETAIL, install_error_handler

SECRET = "password=hunter2 host=db.internal"


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handler(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(SECRET)

    @app.get("/planned")
    def planned() -> None:
        raise HTTPException(status_code=404, detail="Term not found")

    return app


def test_an_unhandled_error_is_json_with_an_id_and_no_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app(), raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="auto_ontology.server.errors"):
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == INTERNAL_ERROR_DETAIL
    assert SECRET not in response.text
    # The same id is on the log line, with the traceback next to it.
    record = next(r for r in caplog.records if body["error_id"] in r.getMessage())
    assert "GET /boom" in record.getMessage()
    assert record.exc_info is not None and SECRET in str(record.exc_info[1])


def test_two_errors_get_two_ids() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)

    first = client.get("/boom").json()["error_id"]
    second = client.get("/boom").json()["error_id"]

    assert first != second


def test_a_planned_error_keeps_its_own_answer() -> None:
    response = TestClient(_app(), raise_server_exceptions=False).get("/planned")

    assert response.status_code == 404
    assert response.json() == {"detail": "Term not found"}
