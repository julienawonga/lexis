# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Message 2 keeps the rows next to a chart, so the interface can switch."""

from __future__ import annotations

import json

from auto_ontology.server.chat.helpers import build_result_message

ROWS = ['[{"shop": "A", "revenue": 10}, {"shop": "B", "revenue": 7}]']
CHART = {"type": "bar", "title": "Revenue per shop"}


def test_a_chart_comes_with_the_stored_rows() -> None:
    built = build_result_message(ROWS, [CHART])
    assert built is not None
    content, sql_response = built
    assert content.startswith("```chart\n")
    assert json.loads(content.split("\n", 1)[1].rsplit("\n```", 1)[0]) == CHART
    assert sql_response is not None
    assert "revenue" in sql_response


def test_rows_alone_are_still_the_table_message() -> None:
    assert build_result_message(ROWS, None) == ("", json.dumps(ROWS))
    assert build_result_message(ROWS, []) == ("", json.dumps(ROWS))


def test_a_chart_without_rows_has_no_table() -> None:
    content, sql_response = build_result_message(None, [CHART])  # type: ignore[misc]
    assert content.startswith("```chart")
    assert sql_response is None


def test_nothing_to_show() -> None:
    assert build_result_message(None, None) is None
    assert build_result_message("   ", []) is None


def test_a_cut_result_says_so_in_the_table_message() -> None:
    built = build_result_message(ROWS, None, truncated_at=10_000)
    assert built is not None
    content, sql_response = built
    assert "Showing the first 10,000 rows" in content
    assert "Totals computed from this table are incomplete." in content
    assert sql_response == json.dumps(ROWS)


def test_a_cut_result_says_so_above_the_chart() -> None:
    built = build_result_message(ROWS, [CHART], truncated_at=500)
    assert built is not None
    content, _ = built
    assert content.startswith("> **Result note:** Showing the first 500 rows")
    assert "```chart\n" in content


def test_a_complete_result_has_no_note() -> None:
    assert build_result_message(ROWS, None, truncated_at=None) == (
        "",
        json.dumps(ROWS),
    )
