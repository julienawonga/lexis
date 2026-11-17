# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""The primary and foreign keys a fixture's SQL *declares*, read from the SQL text.

This is the independent side of the key-detection check
(``dev_tools/fixtures/tests/test_declared_keys.py``): the connectors read keys
from a live database catalog, this module reads them from the fixture files the
database was built from, and ``golden/declared_keys.json`` pins the result. A
connector that loses or invents a key, a fixture edited without its golden, and
a parser that drifts from the SQL each fail a different assertion.

It understands exactly the shapes the fixtures use, and nothing more:

* ``CREATE TABLE`` with an inline ``PRIMARY KEY`` / ``REFERENCES``, or the
  table-level ``[CONSTRAINT n] PRIMARY KEY (..)`` / ``FOREIGN KEY (..)
  REFERENCES t (..)`` forms, with ``"x"``, ``[x]`` or bare identifiers;
* pg_dump's ``ALTER TABLE [ONLY] t ADD CONSTRAINT n PRIMARY KEY|FOREIGN KEY``;
* ``ALTER TABLE ONLY parent ATTACH PARTITION child``, so a key declared on a
  partition is reported for its partitioned root, which is the only name the
  catalog lists (the same mapping ``connectors/postgres.py`` applies).

``TEMPORARY`` tables are skipped. Statements are only recognised at the start
of a line, so the ``INSERT`` data and function bodies are never scanned.

Regenerate the golden after an intentional fixture change::

    python -m dev_tools.fixtures.declared_keys --write
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SQL_DIR = Path(__file__).resolve().parent / "sql"
GOLDEN = Path(__file__).resolve().parent / "golden" / "declared_keys.json"

# name -> (dialect, files). ``rentals`` is portable SQL and loaded into both
# engines by the tests; its dialect here only sets the default schema.
DATABASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "pagila": ("postgres", ("pagila.sql", "pagila_analytics.sql")),
    "chinook": ("sqlite", ("chinook.sql",)),
    "rentals": ("sqlite", ("rentals.sql",)),
}

Table = tuple[str, str]

_CREATE = re.compile(
    r"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)\s*\(",
    re.IGNORECASE | re.MULTILINE,
)
_ALTER_KEY = re.compile(
    r"^ALTER\s+TABLE\s+(?:ONLY\s+)?(\S+)\s+ADD\s+(?:CONSTRAINT\s+\S+\s+)?"
    r"(PRIMARY\s+KEY|FOREIGN\s+KEY)\s*\(([^)]*)\)"
    r"(?:\s+REFERENCES\s+(\S+?)\s*(?:\(([^)]*)\))?(?=[\s;]))?",
    re.IGNORECASE | re.MULTILINE,
)
_ATTACH = re.compile(
    r"^ALTER\s+TABLE\s+(?:ONLY\s+)?(\S+)\s+ATTACH\s+PARTITION\s+(\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_INLINE_REF = re.compile(r"\bREFERENCES\s+([^\s(]+)\s*(?:\(([^)]*)\))?", re.IGNORECASE)
_TABLE_KEY = re.compile(
    r"^(?:CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|FOREIGN\s+KEY)\s*\(([^)]*)\)"
    r"(?:\s*REFERENCES\s+([^\s(]+)\s*(?:\(([^)]*)\))?)?",
    re.IGNORECASE,
)


def _ident(token: str, dialect: str) -> str:
    token = token.strip()
    if token[:1] == '"' and token[-1:] == '"':
        return token[1:-1]
    if token[:1] == "[" and token[-1:] == "]":
        return token[1:-1]
    return token.lower() if dialect == "postgres" else token


def _table(name: str, dialect: str) -> Table:
    parts = [p for p in re.split(r"\.(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", name) if p]
    default = "public" if dialect == "postgres" else "main"
    if len(parts) == 1:
        return default, _ident(parts[0], dialect)
    return _ident(parts[-2], dialect), _ident(parts[-1], dialect)


def _columns(text: str, dialect: str) -> list[str]:
    return [_ident(c, dialect) for c in text.split(",") if c.strip()]


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", text)


def _body(text: str, start: int) -> str:
    """The text between the parenthesis opening at *start* and its match."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    raise ValueError("unbalanced parentheses in a CREATE TABLE")


def _split_top_level(body: str) -> list[str]:
    items, depth, current = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    items.append("".join(current))
    return [" ".join(i.split()) for i in items if i.strip()]


def parse_declared_keys(sql: str, dialect: str) -> dict[str, Any]:
    """``{"primary_keys": {"schema.table": [cols]}, "foreign_keys": [[...]]}``."""
    pks: dict[Table, list[str]] = {}
    # (table, columns, ref table, ref columns or None for "the target's key")
    fks: list[tuple[Table, list[str], Table, list[str] | None]] = []
    parents: dict[Table, Table] = {}

    for match in _CREATE.finditer(sql):
        head = sql[max(0, match.start()) : match.end()]
        if re.match(
            r"CREATE\s+(?:GLOBAL\s+|LOCAL\s+)?(?:TEMP|TEMPORARY|UNLOGGED)", head, re.I
        ):
            continue
        table = _table(match.group(1), dialect)
        body = _strip_comments(_body(sql, match.end() - 1))
        for item in _split_top_level(body):
            keyed = _TABLE_KEY.match(item)
            if keyed:
                kind = " ".join(keyed.group(1).upper().split())
                cols = _columns(keyed.group(2), dialect)
                if kind == "PRIMARY KEY":
                    pks[table] = cols
                elif keyed.group(3):
                    ref_cols = (
                        _columns(keyed.group(4), dialect) if keyed.group(4) else None
                    )
                    fks.append((table, cols, _table(keyed.group(3), dialect), ref_cols))
                continue
            first = item.split(None, 1)[0].upper()
            if first in {"CONSTRAINT", "UNIQUE", "CHECK", "EXCLUDE", "LIKE"}:
                continue
            column = _ident(item.split(None, 1)[0], dialect)
            if re.search(r"\bPRIMARY\s+KEY\b", item, re.IGNORECASE):
                pks[table] = [column]
            ref = _INLINE_REF.search(item)
            if ref:
                ref_cols = _columns(ref.group(2), dialect) if ref.group(2) else None
                fks.append((table, [column], _table(ref.group(1), dialect), ref_cols))

    for match in _ALTER_KEY.finditer(sql):
        table = _table(match.group(1), dialect)
        cols = _columns(match.group(3), dialect)
        if " ".join(match.group(2).upper().split()) == "PRIMARY KEY":
            pks[table] = cols
        elif match.group(4):
            ref_cols = _columns(match.group(5), dialect) if match.group(5) else None
            fks.append((table, cols, _table(match.group(4), dialect), ref_cols))

    for match in _ATTACH.finditer(sql):
        parents[_table(match.group(2), dialect)] = _table(match.group(1), dialect)

    def root(table: Table) -> Table:
        seen = set()
        while table in parents and table not in seen:
            seen.add(table)
            table = parents[table]
        return table

    primary: dict[Table, list[str]] = {}
    for table, cols in pks.items():
        primary[root(table)] = cols

    foreign: set[tuple[str, str, str, str, str, str]] = set()
    for table, cols, ref_table, ref_cols in fks:
        ref_table = root(ref_table)
        targets = ref_cols if ref_cols is not None else primary.get(ref_table)
        if targets is None or len(targets) != len(cols):
            raise ValueError(
                f"cannot resolve the referenced columns of {table} -> {ref_table}"
            )
        source = root(table)
        for column, target in zip(cols, targets):
            foreign.add((*source, column, *ref_table, target))

    return {
        "primary_keys": {f"{s}.{t}": c for (s, t), c in sorted(primary.items())},
        "foreign_keys": [list(row) for row in sorted(foreign)],
    }


def declared_keys(name: str) -> dict[str, Any]:
    """The declared keys of the fixture *name*, parsed from its SQL files."""
    dialect, files = DATABASES[name]
    sql = "\n".join((SQL_DIR / f).read_text(encoding="utf-8-sig") for f in files)
    return parse_declared_keys(sql, dialect)


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def diff_keys(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """One line per key present on one side only, naming it and the side."""
    lines = []
    for table in sorted(set(expected["primary_keys"]) | set(actual["primary_keys"])):
        want = expected["primary_keys"].get(table)
        got = actual["primary_keys"].get(table)
        if want == got:
            continue
        if got is None:
            lines.append(f"MISSING primary key {table}{want}")
        elif want is None:
            lines.append(f"EXTRA primary key {table}{got}")
        else:
            lines.append(f"DIFFERENT primary key {table}: expected {want}, got {got}")
    want_fks = {tuple(r) for r in expected["foreign_keys"]}
    got_fks = {tuple(r) for r in actual["foreign_keys"]}

    def show(row: tuple[str, ...]) -> str:
        return f"{row[0]}.{row[1]}.{row[2]} -> {row[3]}.{row[4]}.{row[5]}"

    lines += [f"MISSING foreign key {show(r)}" for r in sorted(want_fks - got_fks)]
    lines += [f"EXTRA foreign key {show(r)}" for r in sorted(got_fks - want_fks)]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="rewrite the golden")
    args = parser.parse_args()
    golden = load_golden() if GOLDEN.is_file() else {"databases": {}}
    for name in DATABASES:
        entry = golden["databases"].setdefault(name, {})
        entry.update(declared_keys(name))
        print(
            f"{name}: {len(entry['primary_keys'])} primary keys, "
            f"{len(entry['foreign_keys'])} foreign keys"
        )
    if args.write:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(
            json.dumps(golden, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    main()
