# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``fetch_semantic_domains`` must count only tables in the requested database.

A Term is global: the same Term can be REPRESENTS-linked to a table in the
live database *and* to a same-named table in another database. The domain
payload's ``table_count`` and every cross-domain link's
``shared_table_count`` are computed from ``fetch_term_table_pairs`` pairs, so
those pairs must be filtered to the requested database's tables — exactly the
scoping ``fetch_semantic_exploration_graph`` already applies with
``_table_ids_for_database``.

No database here: ``fetch_semantic_domains`` is driven with fakes for every
DAL read it makes, and the pure pair-filtering helper is tested directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from auto_ontology.dal import exploration as e


TERM_ID = "term-1"
THIS_DB_TABLE = "table-this-db"
OTHER_DB_TABLE = "table-other-db"
DATABASE_ID = "db-live"


def _pairs() -> list[dict[str, Any]]:
    """One Term linked to one table here and one table elsewhere."""
    return [
        {"term_id": TERM_ID, "table_id": THIS_DB_TABLE, "path": "REPRESENTS"},
        {"term_id": TERM_ID, "table_id": OTHER_DB_TABLE, "path": "REPRESENTS"},
    ]


def test_filter_pairs_for_database_keeps_only_requested_database_tables() -> None:
    """The pure helper drops pairs whose table is not in the requested DB."""
    kept = e._filter_pairs_for_database(_pairs(), {THIS_DB_TABLE})
    assert [row["table_id"] for row in kept] == [THIS_DB_TABLE]


def test_filter_pairs_for_database_keeps_all_when_all_tables_match() -> None:
    kept = e._filter_pairs_for_database(_pairs(), {THIS_DB_TABLE, OTHER_DB_TABLE})
    assert len(kept) == 2


def test_filter_pairs_for_database_empty_when_no_tables_match() -> None:
    assert e._filter_pairs_for_database(_pairs(), set()) == []


@pytest.fixture()
def patched_reads(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake every DAL read ``fetch_semantic_domains`` performs."""
    graph = {
        "nodes": [
            {
                "id": TERM_ID,
                "name": "Case",
                "relationship_count": 0,
                "column_attributes_count": 0,
                "sql_attributes_count": 0,
            }
        ],
        "links": [],
    }
    domains = [
        {
            "id": "domain-1",
            "name": "Cases",
            "description": None,
            "origin": "auto",
            "term_ids": [TERM_ID],
        }
    ]
    terms = [{"id": TERM_ID, "certification": None}]
    monkeypatch.setattr(e, "fetch_semantic_exploration_graph", lambda **_: graph)
    monkeypatch.setattr(e, "fetch_domains", lambda _database_id: domains)
    monkeypatch.setattr(e, "fetch_all_terms", lambda zone_ids=None: terms)
    monkeypatch.setattr(e, "_table_ids_for_database", lambda _db: {THIS_DB_TABLE})
    return {"pairs": _pairs()}


def test_table_count_excludes_tables_of_other_databases(
    monkeypatch: pytest.MonkeyPatch, patched_reads: dict[str, Any]
) -> None:
    """A Term linked here and elsewhere counts 1 table, not 2."""

    def fake_pairs(zone_ids: Any = None, term_ids: list[str] | None = None) -> list:
        assert term_ids == [TERM_ID]
        return patched_reads["pairs"]

    monkeypatch.setattr(e, "fetch_term_table_pairs", fake_pairs)

    payload = e.fetch_semantic_domains(DATABASE_ID)
    domain = next(d for d in payload["domains"] if d["id"] == "domain-1")
    assert domain["table_count"] == 1


def test_shared_table_count_excludes_tables_of_other_databases(
    monkeypatch: pytest.MonkeyPatch, patched_reads: dict[str, Any]
) -> None:
    """Two Terms sharing only an other-database table share 0 tables here."""
    other_term = "term-2"
    graph = {
        "nodes": [
            {
                "id": TERM_ID,
                "name": "Case",
                "relationship_count": 1,
                "column_attributes_count": 0,
                "sql_attributes_count": 0,
            },
            {
                "id": other_term,
                "name": "Matter",
                "relationship_count": 1,
                "column_attributes_count": 0,
                "sql_attributes_count": 0,
            },
        ],
        "links": [
            {
                "source": TERM_ID,
                "target": other_term,
                "relationship_types": ["REPRESENTS"],
            }
        ],
    }
    domains = [
        {
            "id": "domain-1",
            "name": "Cases",
            "description": None,
            "origin": "auto",
            "term_ids": [TERM_ID],
        },
        {
            "id": "domain-2",
            "name": "Matters",
            "description": None,
            "origin": "auto",
            "term_ids": [other_term],
        },
    ]
    terms = [{"id": TERM_ID, "certification": None}, {"id": other_term}]
    monkeypatch.setattr(e, "fetch_semantic_exploration_graph", lambda **_: graph)
    monkeypatch.setattr(e, "fetch_domains", lambda _database_id: domains)
    monkeypatch.setattr(e, "fetch_all_terms", lambda zone_ids=None: terms)
    monkeypatch.setattr(e, "_table_ids_for_database", lambda _db: {THIS_DB_TABLE})

    def fake_pairs(zone_ids: Any = None, term_ids: list[str] | None = None) -> list:
        # The two terms share ONLY the other-database table; term-1 also has
        # one table in this database.
        return patched_reads["pairs"] + [
            {"term_id": other_term, "table_id": OTHER_DB_TABLE, "path": "REPRESENTS"}
        ]

    monkeypatch.setattr(e, "fetch_term_table_pairs", fake_pairs)

    payload = e.fetch_semantic_domains(DATABASE_ID)
    link = next(edge for edge in payload["links"] if edge["weight"] > 0)
    assert link["shared_table_count"] == 0
