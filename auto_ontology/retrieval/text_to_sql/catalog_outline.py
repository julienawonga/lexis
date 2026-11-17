# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Every table and column of one database, from the catalog the engine has.

Composed from existing DAL reads (databases, schemas, tables of a schema, then
one frame of columns for all those tables), so no DAL function is added. The
result has the shape of ``relevant_tables`` entries, so a table found here can be
appended to the offered tables as is.
"""

from __future__ import annotations

import logging

from auto_ontology.dal.datasources import (
    fetch_databases,
    fetch_schemas_for_database,
    fetch_tables_and_columns_by_node_ids,
    fetch_tables_for_schema,
)

logger = logging.getLogger(__name__)


def load_catalog_tables(database_name: str) -> list[dict]:
    """Tables of *database_name* with ``columns`` ``[{name, data_type}]``.

    Raises on a read failure (the caller fails open). Returns ``[]`` when the
    database is not in the catalog.
    """
    wanted = database_name.casefold()
    database = next(
        (d for d in fetch_databases() if str(d.get("name") or "").casefold() == wanted),
        None,
    )
    if database is None:
        return []
    schemas = (fetch_schemas_for_database(database["id"]) or {}).get("schemas") or []
    table_ids: list[str] = []
    for schema in schemas:
        table_ids += [t["id"] for t in fetch_tables_for_schema(schema["id"])]
    if not table_ids:
        return []
    tables_df, columns_df, _ = fetch_tables_and_columns_by_node_ids(table_ids)

    by_key: dict[tuple[str, str], dict] = {}
    ordered: list[dict] = []
    for row in tables_df.to_dict("records"):
        key = (str(row["table_schema"]), str(row["table_name"]))
        table = {
            "name": str(row["table_name"]),
            "schema_name": str(row["table_schema"]),
            "database_name": str(row.get("database_name") or database["name"]),
            "columns": [],
        }
        by_key[key] = table
        ordered.append(table)
    for row in columns_df.to_dict("records"):
        table = by_key.get((str(row["table_schema"]), str(row["table_name"])))
        if table is not None:
            table["columns"].append(
                {
                    "name": str(row["column_name"]),
                    "data_type": str(row.get("data_type") or "unknown"),
                }
            )
    return ordered
