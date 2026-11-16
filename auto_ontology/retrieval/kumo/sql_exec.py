# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""The only two ways the prediction path runs SQL.

``run_model_sql`` is for SQL a language model wrote: it goes through the same
helper as the chat (parse-time read-only guard, database read-only mode, row
cap), so the guard is not duplicated here. ``run_catalog_sql`` is for SQL this
package builds from quoted catalog identifiers: not model-written, but still
read-only and capped.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from auto_ontology.infra.feature_flags import get_kumo_table_max_rows
from auto_ontology.retrieval.text_to_sql.chat_sql import _cut_at, execute_chat_sql


def run_model_sql(connector: Any, sql: str) -> pd.DataFrame:
    """Run model-written *sql*; raises ``UnsafeSqlError`` unless it is one SELECT."""
    return execute_chat_sql(connector, sql, kind="kumo entity SQL")


def run_catalog_sql(
    connector: Any, sql: str, *, max_rows: int | None = None
) -> pd.DataFrame:
    """Run SQL built by our own code, read-only and capped at *max_rows*.

    *max_rows* defaults to the Kumo table cap setting.
    """
    limit = get_kumo_table_max_rows() if max_rows is None else max_rows
    options: dict[str, Any] = {}
    if getattr(connector, "supports_read_only_execution", False):
        options["read_only"] = True
    if getattr(connector, "supports_row_limit", False):
        options["max_rows"] = limit
    return _cut_at(connector.execute(sql, **options), limit)
