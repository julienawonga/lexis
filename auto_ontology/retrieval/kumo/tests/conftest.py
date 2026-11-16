# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Keep the settings reads of the prediction path off the database."""

from __future__ import annotations

import pytest

from auto_ontology.retrieval.kumo import sql_exec
from auto_ontology.retrieval.text_to_sql import chat_sql


@pytest.fixture(autouse=True)
def _stored_row_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_sql, "get_sql_result_max_rows", lambda: 10_000)
    monkeypatch.setattr(
        sql_exec, "get_kumo_table_max_rows", lambda: 100_000, raising=False
    )
    from auto_ontology.retrieval.kumo import predictor

    monkeypatch.setattr(
        predictor, "get_kumo_table_max_rows", lambda: 100_000, raising=False
    )
