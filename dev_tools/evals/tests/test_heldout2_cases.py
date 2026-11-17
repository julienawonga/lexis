# SPDX-License-Identifier: Apache-2.0

"""The second-generation answerability sets: they load, are frozen and reproduce.

``unanswerable_rentals.json`` (24 refusals) and ``answerable_heldout.json`` (36
answerable cases over Chinook, Pagila and Rentals). Everything runs on the SQLite
builds of the fixtures; the Pagila gold is PostgreSQL and is only checked for a
non-empty snapshot here (the snapshot was taken on a throwaway PostgreSQL).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from dev_tools.evals.cases import (
    SQLITE_PREFIX,
    load_cases,
    parse_dsn_args,
    run_gold,
)
from dev_tools.evals.compare import compare_rows
from dev_tools.evals.refusal import EXPECT_REFUSAL, KINDS
from dev_tools.integrity.freeze import file_cases_sha256

ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = ROOT / "dev_tools" / "evals" / "cases"
SQL_DIR = ROOT / "dev_tools" / "fixtures" / "sql"
ANSWERABLE = CASES_DIR / "answerable_heldout.json"
REFUSALS = CASES_DIR / "unanswerable_rentals.json"
SQLITE_DATABASES = {"chinook": "utf-8-sig", "rentals": "utf-8"}


@pytest.fixture(scope="module")
def dsns(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, encoding in SQLITE_DATABASES.items():
        path = tmp_path_factory.mktemp(name) / f"{name}.sqlite"
        con = sqlite3.connect(path)
        try:
            con.executescript((SQL_DIR / f"{name}.sql").read_text(encoding=encoding))
            con.commit()
        finally:
            con.close()
        out[name] = f"{SQLITE_PREFIX}{path.as_posix()}"
    return out


def test_both_files_are_frozen() -> None:
    for path in (ANSWERABLE, REFUSALS):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["frozen_sha256"] == file_cases_sha256(path), path.name


def test_refusal_file_composition() -> None:
    cases = load_cases(REFUSALS)
    assert len(cases) == 24
    assert all(c.expect == EXPECT_REFUSAL and c.reason for c in cases)
    assert all(c.target_db == "rentals" for c in cases)
    assert all(c.id.startswith("unanswerable_rentals.") for c in cases)
    assert Counter(c.kind for c in cases) == {kind: 4 for kind in KINDS}
    assert 3 <= sum("fr" in c.tags for c in cases) <= 8


def test_refusal_questions_do_not_repeat_the_first_generation() -> None:
    first = {c.question for c in load_cases(CASES_DIR / "unanswerable.json")}
    assert not first & {c.question for c in load_cases(REFUSALS)}


def test_answerable_composition() -> None:
    cases = load_cases(ANSWERABLE)
    assert len(cases) == 36
    ids = [c.id for c in cases]
    assert len(set(ids)) == len(ids)
    for case in cases:
        assert case.id.startswith(f"heldout.{case.target_db}."), case.id
        assert len(case.tags) == 1 and case.tags[0] in {
            "computed",
            "far-table",
            "plain",
        }, case.id
    for db in ("chinook", "pagila", "rentals"):
        tags = Counter(c.tags[0] for c in cases if c.target_db == db)
        assert tags == {"computed": 6, "far-table": 4, "plain": 2}, db


def test_answerable_questions_are_distinct_from_the_frozen_sets() -> None:
    seen: set[str] = set()
    for name in ("chinook", "pagila", "rentals", "chinook_fr"):
        seen |= {c.question.lower() for c in load_cases(CASES_DIR / f"{name}.json")}
    mine = {c.question.lower() for c in load_cases(ANSWERABLE)}
    assert not seen & mine


def test_every_gold_has_a_non_empty_snapshot() -> None:
    for case in load_cases(ANSWERABLE):
        for gold in case.gold:
            assert gold.expected, f"{case.id}/{gold.label}"


def test_sqlite_gold_returns_its_snapshot(dsns: dict[str, str]) -> None:
    checked = 0
    for case in load_cases(ANSWERABLE):
        if case.target_db not in dsns:
            continue
        for gold in case.gold:
            rows = run_gold(dsns[case.target_db], gold.sql)
            assert gold.expected is not None
            verdict = compare_rows(rows, gold.expected, ordered=case.ordered)
            assert verdict.passed, f"{case.id}/{gold.label}: {verdict.detail}"
            checked += 1
    assert checked >= 24


def test_rentals_gold_does_not_depend_on_soft_deletes(
    dsns: dict[str, str], tmp_path: Path
) -> None:
    # The same gold on a copy with every soft-deleted row removed must give the
    # same rows, so these cases measure the check and not soft-delete handling.
    path = tmp_path / "purged.sqlite"
    con = sqlite3.connect(path)
    con.executescript((SQL_DIR / "rentals.sql").read_text(encoding="utf-8"))
    for table in ("staff", "customer", "equip_unit", "rental", "payment"):
        con.execute(f"DELETE FROM {table} WHERE deleted_at IS NOT NULL")  # noqa: S608
    con.commit()
    con.close()
    purged = f"{SQLITE_PREFIX}{path.as_posix()}"
    for case in load_cases(ANSWERABLE):
        if case.target_db != "rentals":
            continue
        for gold in case.gold:
            rows = run_gold(purged, gold.sql)
            verdict = compare_rows(rows, gold.expected or [], ordered=case.ordered)
            assert verdict.passed, f"{case.id}/{gold.label}: {verdict.detail}"


def test_parse_dsn_args() -> None:
    assert parse_dsn_args(["sqlite:///x.sqlite"]) == "sqlite:///x.sqlite"
    assert parse_dsn_args(["a=sqlite:///x", "b=postgresql://u:p@h/db"]) == {
        "a": "sqlite:///x",
        "b": "postgresql://u:p@h/db",
    }
    with pytest.raises(ValueError):
        parse_dsn_args(["a=sqlite:///x", "postgresql://u:p@h/db"])
    with pytest.raises(ValueError):
        parse_dsn_args(["sqlite:///x", "sqlite:///y"])


def test_snapshot_needs_a_dsn_for_every_database(tmp_path: Path) -> None:
    from dev_tools.evals.cases import snapshot_file

    with pytest.raises(ValueError, match="no --dsn"):
        snapshot_file(ANSWERABLE, {"pagila": "sqlite:///missing.sqlite"}, check=True)
