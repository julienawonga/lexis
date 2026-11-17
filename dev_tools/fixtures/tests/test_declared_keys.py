# SPDX-License-Identifier: Apache-2.0

"""Key detection against a known schema (roadmap step 12, part B).

Three independent sources must agree on the primary and foreign keys of each
fixture database:

1. the SQL the database is built from, read by ``declared_keys.py``;
2. ``golden/declared_keys.json``, committed;
3. what the repository's own key extraction (``get_pks`` / ``get_fks`` of the
   SQLite and Postgres connectors) reports from a live database.

(1) against (2) needs no database and catches a fixture edited without its
golden. (3) against (2) catches a connector that loses or invents a key, and the
message names each key. The Postgres half needs the CI service (``pagila`` is
seeded there, ``rentals`` is loaded into a throwaway database here) and is
skipped without one; the SQLite half needs nothing.

Chinook is a SQLite fixture on the stack (the Postgres connector never sees
it); ``rentals`` is portable SQL and is checked on both engines. Only keys the
SQL declares are tested; undeclared relations are documented in the golden and
not tested.
"""

from __future__ import annotations

import os
import sqlite3
import textwrap
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import pytest

from auto_ontology.connectors.postgres import PostgresDatabase
from auto_ontology.connectors.sqlite import SQLiteDatabase
from dev_tools.fixtures import build_sqlite_fixtures
from dev_tools.fixtures.declared_keys import (
    DATABASES,
    SQL_DIR,
    declared_keys,
    diff_keys,
    load_golden,
    parse_declared_keys,
)


def _golden(name: str) -> dict[str, Any]:
    return load_golden()["databases"][name]


def detected_keys(database: Any) -> dict[str, Any]:
    """The keys a connector reports, in the golden's shape."""
    pks: pd.DataFrame = database.get_pks()
    fks: pd.DataFrame = database.get_fks()
    primary: dict[str, list[str]] = {}
    if len(pks):
        for (schema, table), rows in pks.groupby(["table_schema", "table_name"]):
            ordered = rows.sort_values("ordinal_position")
            primary[f"{schema}.{table}"] = list(ordered["column_name"])
    foreign = []
    if len(fks):
        foreign = sorted(
            [
                r.table_schema,
                r.table_name,
                r.column_name,
                r.referenced_schema,
                r.referenced_table,
                r.referenced_column,
            ]
            for r in fks.itertuples(index=False)
        )
    return {"primary_keys": dict(sorted(primary.items())), "foreign_keys": foreign}


def _assert_matches_golden(name: str, database: Any) -> None:
    drift = diff_keys(_golden(name), detected_keys(database))
    assert not drift, (
        f"key detection drifted from the keys declared in the {name} fixture:\n  "
        + "\n  ".join(drift)
    )


# --- the golden is the SQL ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(DATABASES))
def test_golden_is_what_the_fixture_sql_declares(name: str) -> None:
    drift = diff_keys(declared_keys(name), _golden(name))
    assert not drift, (
        f"golden/declared_keys.json is out of date for {name} (the fixture SQL "
        "changed?). If intended: python -m dev_tools.fixtures.declared_keys "
        "--write\n  " + "\n  ".join(drift)
    )


def test_golden_counts_were_checked_by_hand() -> None:
    """Counts read off the SQL by eye once, so a parser bug cannot hide in both."""
    counts = {
        name: (len(g["primary_keys"]), len(g["foreign_keys"]))
        for name, g in load_golden()["databases"].items()
    }
    assert counts == {"pagila": (17, 24), "chinook": (11, 11), "rentals": (12, 16)}


def test_parser_reads_every_declaration_shape() -> None:
    sql = """
    CREATE TABLE a (id integer PRIMARY KEY, name text);
    CREATE TABLE b (
        x int, y int,
        a_id int REFERENCES a,
        c_id int REFERENCES public.c (cid) ON DELETE CASCADE,
        CONSTRAINT b_pk PRIMARY KEY (x, y),
        FOREIGN KEY (x, y) REFERENCES d (p, q)
    );
    CREATE TABLE c (cid int);
    CREATE TABLE d (p int, q int);
    CREATE TEMPORARY TABLE scratch (id int PRIMARY KEY);
    CREATE TABLE ev (id int, at date) PARTITION BY RANGE (at);
    CREATE TABLE ev_1 (id int, at date);
    ALTER TABLE ONLY ev ATTACH PARTITION ev_1 FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
    ALTER TABLE ONLY ev_1
        ADD CONSTRAINT ev_1_pkey PRIMARY KEY (at, id);
    ALTER TABLE ONLY ev_1
        ADD CONSTRAINT ev_1_a FOREIGN KEY (id) REFERENCES public.a(id);
    ALTER TABLE ONLY d ADD CONSTRAINT d_pkey PRIMARY KEY (p, q);
    """
    keys = parse_declared_keys(textwrap.dedent(sql), "postgres")
    assert keys["primary_keys"] == {
        "public.a": ["id"],
        "public.b": ["x", "y"],
        "public.d": ["p", "q"],
        "public.ev": ["at", "id"],
    }
    assert keys["foreign_keys"] == [
        ["public", "b", "a_id", "public", "a", "id"],
        ["public", "b", "c_id", "public", "c", "cid"],
        ["public", "b", "x", "public", "d", "p"],
        ["public", "b", "y", "public", "d", "q"],
        ["public", "ev", "id", "public", "a", "id"],
    ]


def test_drift_is_named() -> None:
    golden = {
        "primary_keys": {"main.t": ["id"], "main.u": ["a", "b"]},
        "foreign_keys": [["main", "t", "u_id", "main", "u", "a"]],
    }
    detected = {
        "primary_keys": {"main.t": ["id"], "main.v": ["id"], "main.u": ["b", "a"]},
        "foreign_keys": [["main", "t", "v_id", "main", "v", "id"]],
    }
    assert diff_keys(golden, detected) == [
        "DIFFERENT primary key main.u: expected ['a', 'b'], got ['b', 'a']",
        "EXTRA primary key main.v['id']",
        "MISSING foreign key main.t.u_id -> main.u.a",
        "EXTRA foreign key main.t.v_id -> main.v.id",
    ]


# --- SQLite connector -----------------------------------------------------------


def test_sqlite_detects_the_chinook_keys() -> None:
    path = build_sqlite_fixtures.build(build_sqlite_fixtures.FIXTURES[0])
    database = SQLiteDatabase(str(path))
    try:
        _assert_matches_golden("chinook", database)
    finally:
        database.close()


def test_sqlite_detects_the_rentals_keys(tmp_path: Path) -> None:
    path = tmp_path / "rentals.sqlite"
    with sqlite3.connect(path) as con:
        con.executescript((SQL_DIR / "rentals.sql").read_text(encoding="utf-8"))
    database = SQLiteDatabase(str(path))
    try:
        _assert_matches_golden("rentals", database)
    finally:
        database.close()


def test_a_dropped_key_would_fail_the_check(tmp_path: Path) -> None:
    """The check is not vacuous: remove one key from a copy and it must fail."""
    sql = (SQL_DIR / "rentals.sql").read_text(encoding="utf-8")
    broken = sql.replace(
        "staff_id INTEGER NOT NULL REFERENCES staff (staff_id),\n    stat_cd",
        "staff_id INTEGER NOT NULL,\n    stat_cd",
    )
    assert broken != sql
    path = tmp_path / "broken.sqlite"
    with sqlite3.connect(path) as con:
        con.executescript(broken)
    database = SQLiteDatabase(str(path))
    try:
        with pytest.raises(
            AssertionError, match="MISSING foreign key main.rental.staff_id"
        ):
            _assert_matches_golden("rentals", database)
    finally:
        database.close()


# --- Postgres connector ---------------------------------------------------------


def _pg_params() -> dict[str, str]:
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    return {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }


def _dsn(params: dict[str, str], dbname: str) -> str:
    return (
        f"postgresql://{params['user']}:{params['password']}"
        f"@{params['host']}:{params['port']}/{dbname}"
    )


@pytest.fixture
def pagila() -> Iterator[PostgresDatabase]:
    params = _pg_params()
    try:
        database = PostgresDatabase(_dsn(params, "pagila"))
    except Exception as exc:  # noqa: BLE001 - no fixture database here
        pytest.skip(f"pagila not reachable: {exc}")
    try:
        yield database
    finally:
        database.close()


def test_postgres_detects_the_pagila_keys(pagila: PostgresDatabase) -> None:
    """Includes partitioned ``payment`` (keys declared on its partitions only)
    and the ``analytics`` schema with its cross-schema and self-referencing keys."""
    _assert_matches_golden("pagila", pagila)


@pytest.fixture
def rentals_pg() -> Iterator[PostgresDatabase]:
    params = _pg_params()
    name = f"lexis_rentals_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(dbname="postgres", autocommit=True, **params)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres not reachable: {exc}")
    try:
        admin.execute(f'CREATE DATABASE "{name}"')
        with psycopg.connect(dbname=name, **params) as conn:
            conn.execute((SQL_DIR / "rentals.sql").read_text(encoding="utf-8"))
        database = PostgresDatabase(_dsn(params, name))
        try:
            yield database
        finally:
            database.close()
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def test_postgres_detects_the_rentals_keys(rentals_pg: PostgresDatabase) -> None:
    # The golden's schema name is the engine-neutral one; Postgres calls it public.
    golden = _golden("rentals")
    renamed = {
        "primary_keys": {
            k.replace("main.", "public.", 1): v
            for k, v in golden["primary_keys"].items()
        },
        "foreign_keys": [
            ["public", r[1], r[2], "public", r[4], r[5]] for r in golden["foreign_keys"]
        ],
    }
    drift = diff_keys(renamed, detected_keys(rentals_pg))
    assert not drift, (
        "key detection drifted from the keys declared in the rentals fixture:\n  "
        + "\n  ".join(drift)
    )
