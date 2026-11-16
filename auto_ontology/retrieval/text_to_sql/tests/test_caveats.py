# SPDX-License-Identifier: Apache-2.0

"""Every place validation lets SQL through unchecked leaves a structured caveat."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, TypedDict
from unittest.mock import MagicMock, patch

from langgraph.graph import END, StateGraph

from auto_ontology.retrieval.text_to_sql import main as ts_main
from auto_ontology.retrieval.text_to_sql.agents.response import ResponseAgent
from auto_ontology.retrieval.text_to_sql.agents.sql_parse_validation import (
    IntentValidationModel,
    SQLValidationAgent,
)
from auto_ontology.retrieval.text_to_sql.base import (
    BaseAgent,
    add_caveat,
    agent_wrapper,
)
from auto_ontology.retrieval.text_to_sql.tests.test_evidence_target_deadlock import (
    _EVIDENCE_REJECTION,
    _NO_RANKING_REJECTION,
    _ONLY_CUSTOMERS,
    _WITH_INVOICES,
    _validate,
)
from auto_ontology.retrieval.text_to_sql.text_to_sql_graph import (
    INTENT_VALIDATION_SKIPPED_AFTER,
    _make_soft_check_router,
)


class _S(TypedDict):
    decision: str
    path_state: dict


_MODULE = "auto_ontology.retrieval.text_to_sql.agents.sql_parse_validation"


def _codes(path_state: dict[str, Any]) -> list[str]:
    return [c["code"] for c in path_state.get("caveats") or []]


def test_add_caveat_deduplicates_by_code() -> None:
    path_state: dict[str, Any] = {}
    add_caveat(path_state, "a", "One.")
    add_caveat(path_state, "a", "Again.")
    add_caveat(path_state, "b", "Two.")
    assert path_state["caveats"] == [
        {"code": "a", "message": "One."},
        {"code": "b", "message": "Two."},
    ]


def test_intent_check_model_error_is_marked() -> None:
    state = {
        "llm": MagicMock(),
        "initial_question": "q",
        "connectors": [],
        "path_state": {"relevant_tables": []},
    }
    path_state = {**state["path_state"], "sql_code": "SELECT 1"}
    with patch(f"{_MODULE}.invoke_with_structured_output", side_effect=OSError("x")):
        result = SQLValidationAgent()._validate_intent(state, path_state, [], [])
    assert result["decision"] == "valid_sql"
    assert _codes(result["path_state"]) == ["validation_skipped"]


def test_intent_check_empty_reply_or_unexplained_invalid_is_marked() -> None:
    for verdict in (None, IntentValidationModel(is_valid=False)):
        result = _validate({"relevant_tables": []}, _ONLY_CUSTOMERS, [], verdict)  # type: ignore[arg-type]
        assert result["decision"] == "valid_sql"
        assert _codes(result["path_state"]) == ["validation_skipped"]


def test_a_real_pass_leaves_no_caveat() -> None:
    result = _validate(
        {"relevant_tables": []},
        _ONLY_CUSTOMERS,
        [],
        IntentValidationModel(is_valid=True),
    )
    assert result["decision"] == "valid_sql"
    assert _codes(result["path_state"]) == []


def test_oscillation_fallback_is_marked_and_keeps_its_prose_note() -> None:
    path_state: dict[str, Any] = {"relevant_tables": []}
    script = [
        (_ONLY_CUSTOMERS, ["public.Customer"], _NO_RANKING_REJECTION),
        (_WITH_INVOICES, ["public.Customer", "public.Invoice"], _EVIDENCE_REJECTION),
        (_ONLY_CUSTOMERS, ["public.Customer"], _NO_RANKING_REJECTION),
    ]
    for sql, tables, verdict in script:
        result = _validate(path_state, sql, tables, verdict)
        path_state = result["path_state"]
    assert _codes(path_state) == ["validation_unresolved"]
    assert "not fully validated" in path_state["validation_caveat"]


def test_soft_check_skip_after_repeated_failures_is_marked() -> None:
    route = _make_soft_check_router("precheck_combined")
    few: dict[str, Any] = {"failed_attempts": [{}] * INTENT_VALIDATION_SKIPPED_AFTER}
    assert route({"decision": "invalid_sql", "path_state": few}) == "invalid_sql"  # type: ignore[arg-type]
    assert _codes(few) == []

    many: dict[str, Any] = {
        "failed_attempts": [{}] * (INTENT_VALIDATION_SKIPPED_AFTER + 1)
    }
    assert route({"decision": "invalid_sql", "path_state": many}) == "valid_sql"  # type: ignore[arg-type]
    assert _codes(many) == ["soft_checks_skipped"]


def test_soft_check_mark_survives_inside_a_running_graph() -> None:
    def check(state: dict) -> dict:
        return {"decision": "invalid_sql"}

    graph = StateGraph(_S)
    graph.add_node("check", check)
    graph.add_node("run", lambda s: {})
    graph.set_entry_point("check")
    graph.add_conditional_edges(
        "check",
        _make_soft_check_router("check"),
        {"valid_sql": "run", "invalid_sql": END},
    )
    graph.add_edge("run", END)
    out = graph.compile().invoke(
        {
            "decision": "",
            "path_state": {
                "failed_attempts": [{}] * (INTENT_VALIDATION_SKIPPED_AFTER + 1)
            },
        }
    )
    assert _codes(out["path_state"]) == ["soft_checks_skipped"]


class _Boom(BaseAgent):
    def execute(self, state: Any) -> dict[str, Any]:
        raise RuntimeError("boom")


def test_swallowed_step_exception_is_marked_only_when_decision_stays() -> None:
    state: dict[str, Any] = {"decision": "valid_sql", "path_state": {}}
    update = agent_wrapper(_Boom("boom"))(state)
    assert "decision" not in update
    assert _codes(update["path_state"]) == ["validation_skipped"]

    state2: dict[str, Any] = {"decision": "valid_sql", "path_state": {}}
    update2 = agent_wrapper(_Boom("boom", failure_decision="invalid_sql"))(state2)
    assert update2["decision"] == "invalid_sql"
    assert _codes(update2["path_state"]) == []


def test_final_answer_carries_the_caveats() -> None:
    state = {
        "messages": [],
        "path_state": {
            "sql_generation_result": SimpleNamespace(sql_code="SELECT 1", response="r"),
            "candidates": [],
            "caveats": [{"code": "validation_skipped", "message": "m."}],
        },
    }
    final = ResponseAgent().execute(state)["path_state"]["final_response"]
    assert final["caveats"] == [{"code": "validation_skipped", "message": "m."}]
    state["path_state"].pop("caveats")
    final = ResponseAgent().execute(state)["path_state"]["final_response"]
    assert final["caveats"] == []


def test_main_fallback_sql_is_marked_in_the_answer() -> None:
    final_state: dict[str, Any] = {
        "full_pipeline_attempt": ts_main._MAX_FULL_PIPELINE_ATTEMPTS,
        "path_state": {"last_intent_rejected_sql": "SELECT 1"},
    }
    assert ts_main._apply_last_deterministic_sql_fallback(
        final_state, ts_main._UNCONSTRUCTABLE_NODE
    )
    answer = ts_main._extract_answer(final_state)
    assert answer["sql_code"] == "SELECT 1"
    assert [c["code"] for c in answer["caveats"]] == ["fallback_sql"]
