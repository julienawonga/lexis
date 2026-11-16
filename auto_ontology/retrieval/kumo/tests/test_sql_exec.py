# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Every statement the prediction path runs is guarded, read-only and capped."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from auto_ontology.retrieval.kumo import predictor
from auto_ontology.retrieval.kumo.pql_gen import _resolve_indices
from auto_ontology.retrieval.text_to_sql.sql_guard import UnsafeSqlError

PQL = "PREDICT SUM(orders.amt, 0, 30) FOR EACH customers.cid"


class _Connector:
    dialect = "postgres"
    supports_read_only_execution = True
    supports_row_limit = True
    database_name = "db"

    def __init__(self, rows: int = 3) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, **options: Any) -> pd.DataFrame:
        self.calls.append((sql, options))
        return pd.DataFrame({"cid": list(range(self.rows))})


@pytest.mark.parametrize(
    "bad",
    [
        "DELETE FROM customers",
        "DROP TABLE customers",
        "SELECT cid FROM customers; DROP TABLE customers",
        "WITH d AS (DELETE FROM customers RETURNING cid) SELECT cid FROM d",
    ],
)
def test_model_written_entity_sql_that_writes_is_refused(bad: str) -> None:
    connector = _Connector()

    with pytest.raises(UnsafeSqlError):
        _resolve_indices(PQL, bad, connector, 100, {"customers": "c"})

    assert connector.calls == []


def test_model_written_entity_sql_runs_read_only_and_capped() -> None:
    connector = _Connector()

    ids, _ = _resolve_indices(
        PQL, "SELECT cid FROM customers", connector, 100, {"customers": "c"}
    )

    assert ids == [0, 1, 2]
    ((_, options),) = connector.calls
    assert options["read_only"] is True
    assert options["max_rows"] == 10_000


def test_catalog_built_sql_runs_read_only_and_capped() -> None:
    connector = _Connector()

    _resolve_indices(PQL, None, connector, 100, {"customers": "c"})

    ((_, options),) = connector.calls
    assert options["read_only"] is True
    assert options["max_rows"] == 100_000


def test_table_load_is_read_only_and_capped_by_default() -> None:
    connector = _Connector(rows=2)
    spend = SimpleNamespace(check_deadline=lambda *_: None, add_table=lambda *_: None)
    tables = [{"name": "customers", "schema_name": "public", "columns": []}]

    predictor._load_relevant_frames([connector], tables, spend)  # type: ignore[arg-type]

    ((sql, options),) = connector.calls
    assert sql.endswith("LIMIT 100000")
    assert options == {"read_only": True, "max_rows": 100_000}
