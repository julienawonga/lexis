# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""``load_catalog_tables`` composes existing DAL reads into the table shape."""

import pandas as pd
import pytest

from auto_ontology.retrieval.text_to_sql import catalog_outline


def test_loader_builds_tables_with_columns_for_one_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog_outline,
        "fetch_databases",
        lambda: [{"id": "d1", "name": "Hr"}, {"id": "d2", "name": "other"}],
    )
    monkeypatch.setattr(
        catalog_outline,
        "fetch_schemas_for_database",
        lambda db_id: {"schemas": [{"id": "s1"}]} if db_id == "d1" else None,
    )
    monkeypatch.setattr(
        catalog_outline,
        "fetch_tables_for_schema",
        lambda schema_id: [{"id": "t1"}, {"id": "t2"}],
    )
    tables = pd.DataFrame(
        [
            {"id": "t1", "table_name": "staff", "table_schema": "public"},
            {"id": "t2", "table_name": "address", "table_schema": "public"},
        ]
    )
    columns = pd.DataFrame(
        [
            {
                "table_name": "staff",
                "table_schema": "public",
                "column_name": "staff_id",
                "data_type": "integer",
            },
            {
                "table_name": "address",
                "table_schema": "public",
                "column_name": "country",
                "data_type": None,
            },
        ]
    )
    monkeypatch.setattr(
        catalog_outline,
        "fetch_tables_and_columns_by_node_ids",
        lambda ids: (tables, columns, "Hr"),
    )

    loaded = catalog_outline.load_catalog_tables("hr")

    assert [t["name"] for t in loaded] == ["staff", "address"]
    assert loaded[0]["columns"] == [{"name": "staff_id", "data_type": "integer"}]
    assert loaded[1]["columns"] == [{"name": "country", "data_type": "unknown"}]
    assert catalog_outline.load_catalog_tables("missing") == []
