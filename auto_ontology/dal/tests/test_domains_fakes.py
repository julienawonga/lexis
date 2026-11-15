# SPDX-License-Identifier: Apache-2.0
"""Faked-store tests for the domain rename/move invariants.

No database here: :class:`FakeStore` runs the DAL's own SQLAlchemy statements
against a lightweight in-memory SQLite schema mirroring the tables
``rename_domain`` and ``move_terms`` touch, so the statements themselves — not
mocked shapes — are what is under test. The one helper too heavy to mirror,
``fetch_term_table_pairs`` (the one definition of "Term related to a table"),
is patched per test with canned pairs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy.dialects import sqlite as sqlite_dialect

from auto_ontology.dal import domains

_DDL = """
CREATE TABLE domain (
    id TEXT PRIMARY KEY,
    database_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    origin TEXT NOT NULL DEFAULT 'auto'
);
CREATE TABLE term (
    id TEXT PRIMARY KEY,
    name TEXT,
    source TEXT NOT NULL DEFAULT 'semantic'
);
CREATE TABLE term_domain (
    term_id TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    database_id TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'auto',
    UNIQUE (term_id, database_id)
);
CREATE TABLE catalog_table (id TEXT PRIMARY KEY, schema_id TEXT NOT NULL);
CREATE TABLE catalog_schema (id TEXT PRIMARY KEY, database_id TEXT NOT NULL);
"""


class FakeStore:
    """Runs the DAL's statements against the in-memory schema above."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _execute(self, statement: Any) -> list[dict[str, Any]]:
        compiled = statement.compile(
            dialect=sqlite_dialect.dialect(),
            compile_kwargs={"render_postcompile": True},
        )
        params: list[Any] = []
        for value in compiled.params.values():
            if isinstance(value, list | tuple | set):
                params.extend(value)
            else:
                params.append(value)
        rows = self._connection.execute(str(compiled), params).fetchall()
        return [dict(row) for row in rows]

    def query_read(
        self, statement: Any, parameters: Any = None
    ) -> list[dict[str, Any]]:
        return self._execute(statement)

    def query_write(
        self, statement: Any, parameters: Any = None
    ) -> list[dict[str, Any]]:
        return self._execute(statement)

    def raw(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Run a helper statement and return its first row, if any."""
        rows = self._connection.execute(sql, params).fetchall()
        return dict(rows[0]) if rows else None


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStore]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_DDL)
    fake = FakeStore(connection)

    @contextmanager
    def transaction() -> Iterator[None]:
        yield

    monkeypatch.setattr(domains, "store", lambda: fake)
    monkeypatch.setattr(domains, "write_transaction", transaction)
    yield fake
    connection.close()


def test_rename_domain_marks_its_assignments_human(fake_db: FakeStore) -> None:
    """A renamed domain's assignments must be marked human in the same write.

    ``replace_auto_domains`` deletes every ``origin='auto'`` assignment, so an
    auto-marked assignment under a renamed domain would be emptied by the next
    regeneration — contradicting the module docstring.
    """
    fake_db.raw(
        "INSERT INTO domain (id, database_id, name, origin) VALUES (?, ?, ?, 'auto')",
        ("d1", "db1", "Old"),
    )
    fake_db.raw("INSERT INTO term (id, name) VALUES (?, ?)", ("t1", "T1"))
    fake_db.raw(
        "INSERT INTO term_domain (term_id, domain_id, database_id, origin)"
        " VALUES (?, ?, ?, 'auto')",
        ("t1", "d1", "db1"),
    )

    assert domains.rename_domain("d1", "Renamed") is True

    domain_row = fake_db.raw("SELECT * FROM domain WHERE id = 'd1'")
    assert domain_row is not None
    assert domain_row["name"] == "Renamed"
    assert domain_row["origin"] == "human"
    assignment = fake_db.raw("SELECT * FROM term_domain WHERE term_id = 't1'")
    assert assignment is not None
    assert assignment["origin"] == "human"
