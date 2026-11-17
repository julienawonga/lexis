# SPDX-License-Identifier: Apache-2.0
"""The content shape of each writable kind."""

from __future__ import annotations

import pytest

from auto_ontology.server.knowledge.content import InvalidContent, validate_content


def test_a_term_is_trimmed_and_keeps_its_database() -> None:
    assert validate_content(
        "term", {"name": "  VIP ", "definition": " spends a lot ", "database": "shop"}
    ) == {"name": "VIP", "definition": "spends a lot", "database": "shop"}


@pytest.mark.parametrize(
    "content",
    [
        {},
        {"name": "VIP"},
        {"name": "", "definition": "x"},
        {"name": "VIP", "definition": "   "},
        {"name": "VIP", "definition": "x", "colour": "red"},
        {"name": "VIP", "definition": "x" * 2001},
        "not an object",
    ],
)
def test_a_malformed_term_is_refused(content: object) -> None:
    with pytest.raises(InvalidContent):
        validate_content("term", content)


def test_synonyms_are_deduplicated_ignoring_case() -> None:
    out = validate_content(
        "synonym", {"term": "Revenue", "synonyms": ["sales", "Sales", " turnover "]}
    )
    assert out["synonyms"] == ["sales", "turnover"]


@pytest.mark.parametrize("synonyms", [[], [" "], ["x" * 201]])
def test_bad_synonyms_are_refused(synonyms: list[str]) -> None:
    with pytest.raises(InvalidContent):
        validate_content("synonym", {"term": "Revenue", "synonyms": synonyms})


def test_a_kind_that_cannot_be_written_here_is_refused() -> None:
    with pytest.raises(InvalidContent, match="cannot be created here"):
        validate_content("relation", {"a": 1})
