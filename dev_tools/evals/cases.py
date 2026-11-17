# SPDX-License-Identifier: Apache-2.0

"""Evaluation cases: a question, and every answer accepted for it.

A case file keeps the **gold SQL** as the source of truth and a snapshot of the
rows it returns as ``expected``. Scoring uses the snapshot, so a run needs no
access to the source database; ``snapshot --check`` re-runs the gold SQL and
fails when the data has drifted from the snapshot, so a stale snapshot is
noticed instead of silently grading against the wrong rows.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from dev_tools.evals.compare import compare_rows
from dev_tools.evals.refusal import (
    EXPECT_REFUSAL,
    EXPECT_ROWS,
    EXPECTS,
    validate_refusal_case,
)

DEFAULT_CASES_DIR = Path(__file__).parent / "cases"


@dataclass(frozen=True)
class GoldAnswer:
    label: str
    sql: str
    expected: list[list[Any]] | None = None


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    gold: tuple[GoldAnswer, ...]
    ordered: bool = False
    allow_extra_columns: bool = False
    allow_missing_columns: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    # Sent with the question as the chat request's ``evidence``: context a
    # benchmark supplies (business definitions), never the expected answer.
    evidence: str = ""
    # The catalog database the question is asked of, for a file that mixes
    # databases. An explicit ``--target-db`` on the command line wins.
    target_db: str = ""
    # "refusal": the database cannot answer it; there is no gold and the run is
    # scored by dev_tools.evals.refusal. ``kind`` and ``reason`` describe it.
    expect: str = EXPECT_ROWS
    kind: str = ""
    reason: str = ""

    def accepted(self) -> dict[str, list[list[Any]]]:
        """Label -> expected rows for every accepted answer."""
        if self.expect == EXPECT_REFUSAL:
            return {}
        missing = [g.label for g in self.gold if g.expected is None]
        if missing:
            raise ValueError(
                f"{self.id}: no snapshot for {missing}; "
                "run `python -m dev_tools.evals snapshot`"
            )
        return {g.label: g.expected or [] for g in self.gold}


def parse_case(raw: dict[str, Any]) -> Case:
    expect = raw.get("expect", EXPECT_ROWS)
    if expect not in EXPECTS:
        raise ValueError(f"{raw.get('id')}: expect must be one of {EXPECTS}")
    if expect == EXPECT_REFUSAL:
        validate_refusal_case(raw)
    gold = tuple(
        GoldAnswer(g["label"], g["sql"], g.get("expected")) for g in raw.get("gold", [])
    )
    if not gold and expect == EXPECT_ROWS:
        raise ValueError(f"{raw.get('id')}: a case needs at least one gold answer")
    labels = [g.label for g in gold]
    if len(set(labels)) != len(labels):
        raise ValueError(f"{raw['id']}: duplicate gold labels {labels}")
    return Case(
        id=raw["id"],
        question=raw["question"],
        gold=gold,
        ordered=bool(raw.get("ordered", False)),
        allow_extra_columns=bool(raw.get("allow_extra_columns", False)),
        allow_missing_columns=bool(raw.get("allow_missing_columns", False)),
        tags=tuple(raw.get("tags", ())),
        description=raw.get("description", ""),
        evidence=str(raw.get("evidence") or ""),
        target_db=str(raw.get("database") or ""),
        expect=expect,
        kind=str(raw.get("kind") or ""),
        reason=str(raw.get("reason") or ""),
    )


def load_controls(path: Path) -> list[Case]:
    """The answerable cases a file names under ``controls``, loaded from their files.

    ``controls`` is ``[{"file": "chinook.json", "ids": [...]}]``, paths relative
    to *path*. They are run with the refusal cases to measure false refusals; an
    id that is missing, or that is itself a refusal case, raises.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[Case] = []
    for entry in raw.get("controls", []):
        source = path.parent / entry["file"]
        dataset = json.loads(source.read_text(encoding="utf-8")).get("dataset", "")
        by_id = {c.id: c for c in load_cases(source)}
        for cid in entry["ids"]:
            case = by_id.get(cid)
            if case is None or case.expect != EXPECT_ROWS:
                raise ValueError(f"{path.name}: control {cid} not in {source.name}")
            out.append(replace(case, target_db=case.target_db or dataset))
    return out


def control_files(path: Path) -> list[Path]:
    """The case files a file's ``controls`` point to."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [path.parent / e["file"] for e in raw.get("controls", [])]


def load_many(paths: Sequence[Path]) -> list[Case]:
    """Load several case files as one list; ids must be unique across them."""
    cases = [c for path in paths for c in load_cases(path)]
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate case ids across the case files: {dupes}")
    return cases


def load_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = [parse_case(c) for c in raw["cases"]]
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate case ids in {path.name}: {dupes}")
    return cases


def jsonable(value: Any) -> Any:
    """Turn a database value into something JSON can hold and compare can read."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


SQLITE_PREFIX = "sqlite:///"


def _run_sqlite(dsn: str, sql: str) -> list[list[Any]]:
    # mode=ro makes the file read-only at the driver level, so a gold query
    # cannot change the fixture even if it is wrong.
    path = Path(dsn[len(SQLITE_PREFIX) :]).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return [[jsonable(v) for v in row] for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def run_gold(dsn: str, sql: str) -> list[list[Any]]:
    """Execute gold SQL read-only and return JSON-able rows.

    ``sqlite:///path/to/file.sqlite`` selects SQLite; anything else is a
    Postgres DSN.
    """
    if dsn.startswith(SQLITE_PREFIX):
        return _run_sqlite(dsn, sql)
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)  # type: ignore[arg-type]
            return [[jsonable(v) for v in row] for row in cur.fetchall()]


def parse_dsn_args(values: Sequence[str]) -> str | dict[str, str]:
    """One DSN, or ``name=dsn`` entries mapping a case's ``database`` to its DSN.

    A file that mixes databases (``answerable_heldout.json``) is snapshotted with
    ``--dsn chinook=sqlite:///c.sqlite --dsn pagila=postgresql://...``.
    """
    mapped: dict[str, str] = {}
    for value in values:
        name, sep, rest = value.partition("=")
        if sep and name.isidentifier() and rest.startswith(("sqlite:", "postgres")):
            mapped[name] = rest
    if not mapped:
        if len(values) != 1:
            raise ValueError("pass one --dsn, or several as name=dsn")
        return values[0]
    if len(mapped) != len(values):
        raise ValueError("mix of a bare --dsn and name=dsn entries")
    return mapped


def snapshot_file(
    path: Path, dsn: str | dict[str, str], *, check: bool = False
) -> list[str]:
    """Fill each gold answer's ``expected`` from the database.

    ``dsn`` is one DSN, or a map from a case's ``database`` to its DSN for a file
    that mixes databases. With ``check`` nothing is written; the returned list
    names the gold answers whose live result no longer matches the stored
    snapshot.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    drifted: list[str] = []
    for case in raw["cases"]:
        if case.get("expect", EXPECT_ROWS) == EXPECT_REFUSAL:
            continue  # nothing to snapshot: the database cannot answer it
        if isinstance(dsn, str):
            case_dsn = dsn
        elif case.get("database") in dsn:
            case_dsn = dsn[case["database"]]
        else:
            raise ValueError(
                f"{case['id']}: no --dsn for database {case.get('database')!r}"
            )
        for gold in case["gold"]:
            rows = run_gold(case_dsn, gold["sql"])
            if check:
                stored = gold.get("expected")
                if (
                    stored is None
                    or not compare_rows(
                        rows, stored, ordered=bool(case.get("ordered"))
                    ).passed
                ):
                    drifted.append(f"{case['id']}/{gold['label']}")
            else:
                gold["expected"] = rows
    if not check:
        path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return drifted
