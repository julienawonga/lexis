# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Detect soft-delete marker columns in the catalog and describe them for the model.

A soft delete hides a row without removing it: a nullable timestamp or date
column is filled when the row is deleted and stays NULL while it is live. A
business reader means the live rows by default, so a count of "customers" that
includes deleted ones is wrong, yet nothing in the question mentions deletion.

Detection is structural and uses only what the catalog already holds for a
column (name, data type, nullability); see ``docs/soft-deletes.md``. It is
behind the ``soft_delete_hint_enabled`` flag and changes nothing when off.
"""

from __future__ import annotations

import re
from typing import Any

# Naming convention taken from common ORMs and frameworks (Rails ``discard`` and
# ``paranoia``: ``discarded_at`` / ``deleted_at``; Laravel ``SoftDeletes``:
# ``deleted_at``; Django third-party soft-delete apps; Hibernate ``@SQLDelete``
# patterns). It is NOT derived from any benchmark or evaluation set. Business
# states (cancelled, retired, closed, expired, ended, inactive, ``is_active``)
# are deliberately absent: they describe the life of the thing, not that the
# row was deleted, and must stay visible to a question about them.
DELETION_WORDS = frozenset(
    {"deleted", "removed", "archived", "voided", "trashed", "discarded"}
)
# A name with a deletion word needs one of these (``deleted_at``, ``removed_on``,
# ``date_archived``); the bare deletion word (``deleted``) needs the type alone.
TIME_WORDS = frozenset({"at", "on", "dt", "date", "time", "ts", "timestamp"})

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_TYPE_TOKEN = re.compile(r"[a-z0-9]+")


def _name_tokens(name: str) -> list[str]:
    spaced = _CAMEL_BOUNDARY.sub(" ", name)
    return [t.lower() for t in _NON_ALNUM.split(spaced) if t]


def _is_date_or_timestamp(data_type: str) -> bool:
    """True for date and timestamp types; false for time-of-day, interval, text."""
    for token in _TYPE_TOKEN.findall(data_type.lower()):
        if token == "date" or token.startswith(("timestamp", "datetime")):
            return True
    return False


def is_soft_delete_column(column: Any) -> bool:
    """Whether a catalog column looks like a soft-delete marker.

    Needs a nullable date or timestamp type (unknown nullability does not
    count) and a name with a deletion word plus a time word, or exactly the
    deletion word.
    """
    if not isinstance(column, dict):
        return False
    name = column.get("name")
    data_type = column.get("data_type")
    if not isinstance(name, str) or not isinstance(data_type, str):
        return False
    if column.get("is_nullable") is not True:
        return False
    if not _is_date_or_timestamp(data_type):
        return False
    tokens = _name_tokens(name)
    if not any(t in DELETION_WORDS for t in tokens):
        return False
    if len(tokens) == 1:
        return True
    return any(t in TIME_WORDS for t in tokens)


def soft_delete_columns(table: dict) -> list[str]:
    """Names of the table's soft-delete marker columns, in column order."""
    columns = table.get("columns")
    if not isinstance(columns, list):
        return []
    return [c["name"] for c in columns if is_soft_delete_column(c)]


def annotate_soft_deletes(tables: list[dict]) -> list[dict]:
    """Copy of *tables* where each table with a marker carries ``soft_delete_columns``.

    A table without a marker is returned as the same object, untouched.
    """
    annotated: list[dict] = []
    for table in tables:
        markers = soft_delete_columns(table) if isinstance(table, dict) else []
        annotated.append(
            {**table, "soft_delete_columns": markers} if markers else table
        )
    return annotated


def soft_delete_columns_applied(tables: list[dict]) -> list[str]:
    """``table.column`` for every marker on the annotated tables, for the trace."""
    return [
        f"{table.get('name', 'UNKNOWN')}.{column}"
        for table in tables
        for column in table.get("soft_delete_columns") or []
    ]


def soft_delete_note(markers: list[str]) -> str:
    """The one sentence given to the model next to a table that soft-deletes."""
    cols = " and ".join(f"`{m}`" for m in markers)
    filters = " and ".join(f"`{m} IS NULL`" for m in markers)
    return (
        f"Soft delete: this table soft-deletes rows through {cols} (a row where it "
        f"is not NULL is deleted); exclude deleted rows by default by adding "
        f"{filters} to this table's filter, also when the table is joined, unless "
        f"the question explicitly asks about deleted, removed or archived records "
        f"or about all history."
    )


# Appended to the intent-validation prompt only when a note above is shown.
VALIDATOR_CARVE_OUT = (
    "\nA `<column> IS NULL` filter that a 'Soft delete:' note asks for is expected: "
    "do not flag it as a filter the question did not request."
)
