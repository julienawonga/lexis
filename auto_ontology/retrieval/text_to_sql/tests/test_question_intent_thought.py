# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Display-only thought recorded by the question_intent graph node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from auto_ontology.retrieval.text_to_sql.agents import question_intent
from auto_ontology.retrieval.text_to_sql.agents.question_intent import (
    CalculationSubtype,
    QuestionIntentAgent,
    QuestionIntentModel,
    QuestionType,
    _intent_thought,
)


def _state(**updates: object) -> dict:
    state = {
        "llm": MagicMock(),
        "initial_question": "find revenue in test_dataset dataset",
        "path_state": {},
    }
    state.update(updates)
    return state


def test_thought_type_only() -> None:
    text = _intent_thought("information", None, None, "q", "q", "")

    assert text == "Information question."


def test_thought_type_with_subtype_shows_spaces() -> None:
    text = _intent_thought("calculation", "match_based", None, "q", "q", "")

    assert text == "Calculation (match based) question."


def test_thought_includes_database_when_present() -> None:
    text = _intent_thought("prediction", None, "sales", "q", "q", "")

    assert text == "Prediction question. Database: sales."


def test_thought_omits_database_when_absent() -> None:
    text = _intent_thought("information", None, None, "q", "q", "")

    assert "Database:" not in text


def test_thought_omits_rewritten_when_identical_to_original() -> None:
    text = _intent_thought(
        "information", None, None, "Find  revenue", "Find revenue", ""
    )

    assert "Rewritten as:" not in text


def test_thought_includes_rewritten_without_doubled_punctuation() -> None:
    text = _intent_thought(
        "information",
        None,
        None,
        "What is revenue by region in the finance database",
        "What is revenue by region?",
        "",
    )

    assert " Rewritten as: What is revenue by region?." not in text
    assert text.endswith("Rewritten as: What is revenue by region?")


def test_thought_appends_period_when_rewritten_lacks_punctuation() -> None:
    text = _intent_thought(
        "information", None, None, "revenue by region now", "revenue by region", ""
    )

    assert text.endswith("Rewritten as: revenue by region.")


def test_thought_includes_string_evidence() -> None:
    text = _intent_thought(
        "information", None, None, "q", "q", "Revenue excludes refunds."
    )

    # The evidence part always ends with a period, so evidence that already
    # ends with one is followed by a second period (spec has no exception here).
    assert text.endswith("Evidence given: Revenue excludes refunds.")


def test_thought_joins_list_evidence_with_semicolons() -> None:
    text = _intent_thought(
        "information", None, None, "q", "q", ["Rule one.", "Rule two."]
    )

    assert text.endswith("Evidence given: Rule one.; Rule two.")


def test_thought_truncates_long_evidence_with_ellipsis() -> None:
    evidence = "x" * 241

    text = _intent_thought("information", None, None, "q", "q", evidence)

    assert "…" in text
    assert text.endswith("Evidence given: " + "x" * 240 + "…")


def test_thought_keeps_evidence_at_exact_limit_untruncated() -> None:
    evidence = "x" * 240

    text = _intent_thought("information", None, None, "q", "q", evidence)

    assert "…" not in text
    assert text.endswith("Evidence given: " + "x" * 240 + ".")


@pytest.mark.parametrize(
    ("question_type", "subtype", "target_db", "rewritten", "evidence"),
    [
        ("information", None, None, "same", ""),
        ("calculation", "aggregation", "sales", "Find revenue", ""),
        ("prediction", None, None, "same", "Forecast 2026."),
        (
            "calculation",
            "ranking",
            None,
            "Top product",
            ["a", "b"],
        ),
    ],
)
def test_thought_has_no_newlines(
    question_type: str,
    subtype: str | None,
    target_db: str | None,
    rewritten: str,
    evidence: str | list[str],
) -> None:
    text = _intent_thought(
        question_type, subtype, target_db, "original", rewritten, evidence
    )

    assert "\n" not in text


def test_agent_records_intent_thought_in_thoughts_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        question_intent,
        "invoke_with_structured_output",
        lambda *_args, **_kwargs: QuestionIntentModel(
            question_type=QuestionType.CALCULATION,
            calculation_subtype=CalculationSubtype.AGGREGATION,
            rewritten_question="find revenue",
            extracted_evidence="",
            target_db="test_datset",
        ),
    )
    state = _state(connectors=[SimpleNamespace(database_name="test_dataset")])

    QuestionIntentAgent().execute(state)

    log = state["path_state"]["thoughts_log"]
    assert log and log[-1]["node"] == "question_intent"
    assert log[-1]["text"].startswith("Calculation")
