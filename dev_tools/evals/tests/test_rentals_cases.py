# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""The held-out Rentals set: the fixture builds and every gold answer reproduces.

Everything here runs on the SQLite build of ``rentals.sql``; nothing calls the
engine or a model. The same SQL file also loads into PostgreSQL, which these
tests cannot check (no server): see the portability test for what is guarded.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from dev_tools.evals.cases import SQLITE_PREFIX, load_cases, run_gold
from dev_tools.evals.compare import compare_rows
from dev_tools.integrity.freeze import file_cases_sha256

ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT / "dev_tools" / "evals" / "cases" / "rentals.json"
SQL_PATH = ROOT / "dev_tools" / "fixtures" / "sql" / "rentals.sql"


@pytest.fixture(scope="module")
def dsn(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("rentals") / "rentals.sqlite"
    con = sqlite3.connect(path)
    try:
        con.executescript(SQL_PATH.read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()
    return f"{SQLITE_PREFIX}{path.as_posix()}"


def test_the_sqlite_build_loads(dsn: str) -> None:
    path = Path(dsn[len(SQLITE_PREFIX) :])
    con = sqlite3.connect(path)
    try:
        tables = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert 8 <= len(tables) <= 12
        total = sum(
            con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608
            for t in tables
        )
        assert 300 <= total <= 1500
    finally:
        con.close()


def test_the_file_loads_with_the_case_loader() -> None:
    cases = load_cases(CASES_PATH)
    assert len(cases) == 24


def test_ids_are_unique_and_prefixed() -> None:
    ids = [c.id for c in load_cases(CASES_PATH)]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("rentals.") for i in ids)


def test_every_gold_query_returns_its_snapshot(dsn: str) -> None:
    for case in load_cases(CASES_PATH):
        for gold in case.gold:
            rows = run_gold(dsn, gold.sql)
            assert gold.expected is not None, f"{case.id}/{gold.label}"
            verdict = compare_rows(rows, gold.expected, ordered=case.ordered)
            assert verdict.passed, f"{case.id}/{gold.label}: {verdict.detail}"


def test_no_empty_expected_set_unless_the_case_says_so() -> None:
    for case in load_cases(CASES_PATH):
        for gold in case.gold:
            if "empty-answer" not in case.tags:
                assert gold.expected, f"{case.id}/{gold.label} expects no rows"


def test_needs_definition_cases_carry_evidence_and_no_others_do() -> None:
    for case in load_cases(CASES_PATH):
        assert bool(case.evidence) == ("needs-definition" in case.tags), case.id


def test_evidence_never_contains_an_expected_number() -> None:
    # Evidence may decode codes (so their labels appear in it) but must not state
    # a number the answer contains. Small numbers are skipped: they occur in prose.
    for case in load_cases(CASES_PATH):
        for gold in case.gold:
            for row in gold.expected or []:
                for cell in row:
                    if isinstance(cell, (int, float)) and abs(cell) >= 100:
                        assert str(cell) not in case.evidence, f"{case.id}: {cell}"


def test_the_set_is_frozen() -> None:
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert raw["frozen_sha256"] == file_cases_sha256(CASES_PATH)


def test_the_fixture_stays_in_the_portable_subset() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    assert not sql.startswith("﻿")
    for token in (
        "AUTOINCREMENT",
        "PRAGMA",
        "WITHOUT ROWID",
        "SERIAL",
        "ENUM",
        "BOOLEAN",
        "strftime",
        "datetime(",
    ):
        assert not re.search(rf"{re.escape(token)}", sql, re.I), token
    assert re.search(r"^CREATE TABLE ", sql, re.M)
