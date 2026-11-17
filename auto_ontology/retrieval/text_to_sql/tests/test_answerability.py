# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""The answerability check: refusal path behind ``answerability_check_enabled``.

All with a fake model. Nothing here shows how a real model behaves on the
prompt; that is what the evaluation gate is for.
"""

from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, TypedDict, cast

import pytest

from langgraph.graph import END, StateGraph

from auto_ontology.retrieval.text_to_sql import text_to_sql_graph as graph_module
from auto_ontology.retrieval.text_to_sql.agents import answerability_check
from auto_ontology.retrieval.text_to_sql.answerability_escalation import (
    EscalationItem,
    EscalationModel,
    build_outline,
)
from auto_ontology.retrieval.text_to_sql.agents.answerability_check import (
    AnswerabilityCheckAgent,
)
from auto_ontology.retrieval.text_to_sql.answerability import (
    PROCEED,
    REFUSE,
    AnswerabilityItem,
    AnswerabilityModel,
    closest_columns,
    normalize_identifier,
    offered_columns,
    verify_items,
)
from auto_ontology.retrieval.text_to_sql.base import agent_wrapper
from auto_ontology.retrieval.text_to_sql.clarification import USER_DEFINITION_PREFIX
from auto_ontology.retrieval.text_to_sql.state import AgentState, TextToSQLPayload
from auto_ontology.utils import llm_invoke

TABLES = [
    {
        "name": "staff",
        "schema_name": "public",
        "columns": [
            {"name": "staff_id", "data_type": "integer"},
            {"name": "first_name", "data_type": "text"},
            {"name": "hire_date", "data_type": "date", "description": "day hired"},
        ],
    },
    {
        "name": "payment",
        "schema_name": "public",
        "columns": [
            {"name": "payment_id", "data_type": "integer"},
            {"name": "amount", "data_type": "numeric"},
        ],
    },
]

CATALOG = [
    *TABLES,
    {
        "name": "address",
        "schema_name": "public",
        "columns": [
            {"name": "address_id", "data_type": "integer"},
            {"name": "country", "data_type": "text"},
        ],
    },
]

ABSENT = AnswerabilityItem(what="salary of each staff member", status="absent")
IN_SCHEMA = AnswerabilityItem(
    what="first name", status="in_schema", columns=["staff.first_name"]
)
DERIVABLE = AnswerabilityItem(
    what="years employed",
    status="derivable",
    columns=["staff.hire_date"],
    formula="current_date - hire_date",
)


class _Calls:
    """Records every structured-output call the check makes."""

    def __init__(self, reply: Any, escalation: Any = None) -> None:
        self.reply = reply
        self.escalation = escalation
        self.count = 0  # first-pass calls
        self.escalations = 0  # second-pass calls
        self.messages: list[Any] = []

    def __call__(self, llm: Any, messages: list[Any], schema: Any) -> Any:
        if schema is EscalationModel:
            self.escalations += 1
            self.escalation_messages = messages
            if isinstance(self.escalation, Exception):
                raise self.escalation
            if self.escalation is not None:
                return self.escalation
            # Default: the catalog does not hold any of the items either.
            asked = [
                line[2:]
                for line in messages[-1].content.splitlines()
                if line.startswith("- ")
            ]
            return EscalationModel(
                items=[EscalationItem(what=w, status="still_absent") for w in asked]
            )
        self.count += 1
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _model(*items: AnswerabilityItem, message: str = "") -> AnswerabilityModel:
    return AnswerabilityModel(items=list(items), user_message=message)


def _state(**overrides: Any) -> AgentState:
    path_state: dict[str, Any] = {
        "relevant_tables": TABLES,
        "normalized_question": "salary of each staff member",
        "target_db": "hr",
    }
    path_state.update(overrides.pop("path_state", {}))
    state: dict[str, Any] = {
        "llm": object(),
        "initial_question": "What is the salary of each staff member?",
        "evidence": "",
        "messages": [],
        "decision": "",
        "path_state": path_state,
    }
    state.update(overrides)
    return cast(AgentState, state)


def _run_check(
    monkeypatch: pytest.MonkeyPatch,
    reply: Any,
    escalation: Any = None,
    catalog: Any = None,
    **overrides: Any,
) -> tuple[dict[str, Any], _Calls]:
    calls = _Calls(reply, escalation)
    monkeypatch.setattr(answerability_check, "invoke_with_structured_output", calls)
    loader = catalog if callable(catalog) else (lambda _db: catalog or CATALOG)
    overrides.setdefault("path_state", {}).setdefault("target_db", "hr")
    update = agent_wrapper(AnswerabilityCheckAgent(catalog_loader=loader))(
        _state(**overrides)
    )
    return update, calls


def _codes(update: dict[str, Any]) -> list[str]:
    return [c["code"] for c in update["path_state"].get("caveats") or []]


# -- verification (no model) -------------------------------------------------


def test_absent_item_is_refused_with_the_marker_and_no_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, calls = _run_check(monkeypatch, _model(IN_SCHEMA, ABSENT))

    assert calls.count == 1 and calls.escalations == 1
    assert update["decision"] == REFUSE
    final = update["path_state"]["final_response"]
    assert final["sql_code"] is None
    assert final["sql_response_from_db"] is None
    assert final["refusal"]["missing"] == ["salary of each staff member"]
    assert "salary of each staff member" in final["refusal"]["reason"]
    assert [c["code"] for c in final["caveats"]] == ["unanswerable"]
    assert update["messages"][-1].content == final["response"]


# -- version 2: escalation and computed measures ----------------------------


def _found(what: str, *columns: str) -> EscalationModel:
    return EscalationModel(
        items=[EscalationItem(what=what, status="found", columns=list(columns))]
    )


def test_escalation_turns_a_first_pass_absent_into_proceed_and_adds_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = AnswerabilityItem(what="customer country", status="absent")
    update, calls = _run_check(
        monkeypatch,
        _model(IN_SCHEMA, missing),
        escalation=_found("customer country", "address.country"),
    )

    assert calls.escalations == 1
    assert update["decision"] == PROCEED
    assert "final_response" not in update["path_state"]
    assert "unanswerable" not in _codes(update)
    names = [t["name"] for t in update["path_state"]["relevant_tables"]]
    assert names == ["staff", "payment", "address"]
    # The second pass saw the whole catalog as names and types, no descriptions.
    outline = calls.escalation_messages[-1].content
    assert "address(address_id integer, country text)" in outline
    assert "day hired" not in outline


def test_no_second_call_when_the_first_pass_found_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _run_check(monkeypatch, _model(IN_SCHEMA, DERIVABLE))
    assert calls.escalations == 0


def test_still_absent_after_escalation_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, calls = _run_check(monkeypatch, _model(ABSENT))
    assert calls.escalations == 1
    assert update["decision"] == REFUSE
    reason = update["path_state"]["final_response"]["refusal"]["reason"]
    assert "whole catalog" in reason and "3 tables" in reason


def test_a_found_claim_citing_nothing_in_the_outline_is_still_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, _ = _run_check(
        monkeypatch,
        _model(ABSENT),
        escalation=_found("salary of each staff member", "payroll.gross"),
    )
    assert update["decision"] == REFUSE


def test_a_truncated_outline_never_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        answerability_check,
        "build_outline",
        lambda tables, words: build_outline(tables, words, budget=60),
    )
    update, calls = _run_check(monkeypatch, _model(ABSENT))
    assert calls.escalations == 1
    assert update["decision"] == PROCEED
    assert _codes(update) == ["answerability_unchecked"]
    assert "final_response" not in update["path_state"]


def test_a_truncated_outline_can_still_rescue_an_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        answerability_check,
        "build_outline",
        lambda tables, words: build_outline(tables, words, budget=70),
    )
    missing = AnswerabilityItem(what="customer country", status="absent")
    update, _ = _run_check(
        monkeypatch,
        _model(missing),
        escalation=_found("customer country", "address.country"),
    )
    assert update["decision"] == PROCEED
    assert _codes(update) == []


def test_outline_truncation_prefers_tables_sharing_words_with_the_items() -> None:
    tables = [
        {"name": "alpha", "columns": [{"name": "one", "data_type": "int"}]},
        {"name": "country", "columns": [{"name": "name", "data_type": "text"}]},
    ]
    full = build_outline(tables, ["country"], budget=10_000)
    assert not full.truncated
    assert [t["name"] for t in full.tables] == ["alpha", "country"]
    cut = build_outline(tables, ["country"], budget=25)
    assert cut.truncated and cut.total_tables == 2
    assert [t["name"] for t in cut.tables] == ["country"]


@pytest.mark.parametrize(
    "escalation",
    [EscalationModel(items=[]), RuntimeError("down"), "not a model"],
    ids=["empty", "raises", "wrong-type"],
)
def test_escalation_that_cannot_run_fails_open(
    monkeypatch: pytest.MonkeyPatch, escalation: Any
) -> None:
    update, _ = _run_check(monkeypatch, _model(ABSENT), escalation=escalation)
    assert update["decision"] == PROCEED
    assert _codes(update) == ["answerability_unchecked"]


def test_empty_catalog_and_catalog_read_failure_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, _ = _run_check(monkeypatch, _model(ABSENT), catalog=lambda _db: [])
    assert update["decision"] == PROCEED
    assert _codes(update) == ["answerability_unchecked"]

    def boom(_db: str) -> list[dict]:
        raise OSError("no catalog")

    update, _ = _run_check(monkeypatch, _model(ABSENT), catalog=boom)
    assert update["decision"] == PROCEED
    assert _codes(update) == ["answerability_unchecked"]


def test_a_computed_measure_marked_derivable_proceeds_with_no_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measure = AnswerabilityItem(
        what="total amount per staff member",
        status="derivable",
        columns=["payment.amount", "staff.staff_id"],
        formula="SUM(payment.amount) GROUP BY staff.staff_id",
    )
    update, calls = _run_check(monkeypatch, _model(measure))
    assert update["decision"] == PROCEED and calls.escalations == 0


def test_first_pass_prompt_states_computed_measures_are_not_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _run_check(monkeypatch, _model(IN_SCHEMA))
    system = calls.messages[0].content
    assert "MEASURE COMPUTED from columns" in system
    assert "ONLY for a thing that no offered column" in system
    assert "not a separate item" in system


def test_derivable_item_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    update, _ = _run_check(monkeypatch, _model(IN_SCHEMA, DERIVABLE))

    assert update["decision"] == PROCEED
    assert "final_response" not in update["path_state"]
    assert _codes(update) == []


def test_cited_column_that_does_not_exist_counts_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invented = AnswerabilityItem(
        what="pay", status="in_schema", columns=["staff.salary", "payroll.gross"]
    )

    update, _ = _run_check(monkeypatch, _model(IN_SCHEMA, invented))

    assert update["decision"] == REFUSE
    refusal = update["path_state"]["final_response"]["refusal"]
    assert refusal["missing"] == ["pay"]
    assert "staff.salary" in refusal["reason"]


def test_a_claim_with_no_column_at_all_counts_as_absent() -> None:
    claim = AnswerabilityItem(what="x", status="derivable", formula="a + b")
    (checked,) = verify_items([claim], offered_columns(TABLES), "")
    assert checked.status == "absent"


def test_one_valid_column_is_enough_and_qualified_names_are_read() -> None:
    claim = AnswerabilityItem(
        what="x",
        status="derivable",
        columns=['"public"."staff"."Hire_Date"', "staff.nope"],
    )
    (checked,) = verify_items([claim], offered_columns(TABLES), "")
    assert checked.status == "derivable"
    assert checked.valid_columns == ["staff.hire_date"]
    assert checked.invalid_columns == ["staff.nope"]


def test_item_defined_by_a_term_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = (
        "Business definitions\n- Tenured: a staff member hired more than "
        "five years ago, measured from the hire date."
    )
    defined = AnswerabilityItem(
        what="tenured staff",
        status="defined",
        quote="a staff member  HIRED more than five years ago",
    )

    update, _ = _run_check(monkeypatch, _model(IN_SCHEMA, defined), evidence=evidence)

    assert update["decision"] == PROCEED


def test_definition_claim_without_a_real_quote_or_column_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made_up = AnswerabilityItem(
        what="tenured staff", status="defined", quote="tenured means long service"
    )

    update, _ = _run_check(
        monkeypatch, _model(made_up), evidence="Business definitions\n- Other: x."
    )

    assert update["decision"] == REFUSE


def test_certified_attribute_text_counts_as_a_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defined = AnswerabilityItem(
        what="revenue", status="defined", quote="SUM(payment.amount)"
    )
    update, _ = _run_check(
        monkeypatch,
        _model(defined),
        path_state={"sql_attributes_str": "Revenue: SUM(payment.amount)"},
    )
    assert update["decision"] == PROCEED


# -- fail open ---------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [None, _model(), RuntimeError("endpoint down"), "not a model"],
    ids=["none", "no-items", "raises", "wrong-type"],
)
def test_a_broken_check_proceeds_with_the_unchecked_caveat(
    monkeypatch: pytest.MonkeyPatch, reply: Any
) -> None:
    update, calls = _run_check(monkeypatch, reply)

    assert calls.count == 1
    assert update["decision"] == PROCEED
    assert _codes(update) == ["answerability_unchecked"]
    assert "final_response" not in update["path_state"]


def test_nothing_offered_to_check_against_proceeds_unchecked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, calls = _run_check(
        monkeypatch, _model(ABSENT), path_state={"relevant_tables": []}
    )
    assert calls.count == 0
    assert update["decision"] == PROCEED
    assert _codes(update) == ["answerability_unchecked"]


def test_no_model_client_proceeds_unchecked(monkeypatch: pytest.MonkeyPatch) -> None:
    update, calls = _run_check(monkeypatch, _model(ABSENT), llm=None)
    assert calls.count == 0
    assert _codes(update) == ["answerability_unchecked"]


# -- what the model is shown -------------------------------------------------


def test_prompt_holds_both_wordings_names_types_and_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _run_check(
        monkeypatch,
        _model(IN_SCHEMA),
        initial_question="Quel est le salaire ?",
        evidence="Business definitions\n- Tenured: long service.",
        path_state={
            "normalized_question": "What is the salary?",
            "question_language": "fr",
        },
    )

    system, human = (m.content for m in calls.messages)
    assert "NOT a match" in system
    assert "French" in system
    assert "Quel est le salaire ?" in human and "What is the salary?" in human
    assert "staff.hire_date (date) - day hired" in human
    assert "payment.amount (numeric)" in human
    assert "Tenured: long service." in human
    # Retrieval samples and sample values are not part of this prompt.
    assert "sample" not in human.lower()


# -- refusal text ------------------------------------------------------------


def test_refusal_text_follows_the_question_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, _ = _run_check(
        monkeypatch,
        _model(ABSENT),
        initial_question="Quel est le salaire de chaque employé ?",
        path_state={"question_language": "fr"},
    )
    text = update["path_state"]["final_response"]["response"]
    assert text.startswith("Les données disponibles ne contiennent pas")
    assert "Je n'ai exécuté aucune requête" in text

    update, _ = _run_check(monkeypatch, _model(ABSENT))
    assert update["path_state"]["final_response"]["response"].startswith(
        "The data available here does not hold"
    )

    update, _ = _run_check(
        monkeypatch, _model(ABSENT), path_state={"question_language": "sw"}
    )
    assert update["path_state"]["final_response"]["response"].startswith(
        "The data available here does not hold"
    )


def test_the_models_own_message_is_used_when_it_wrote_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update, _ = _run_check(
        monkeypatch,
        _model(
            ABSENT, message="Les salaires ne sont pas stockés ; rien n'a été exécuté."
        ),
        path_state={"question_language": "fr"},
    )
    assert update["path_state"]["final_response"]["response"].startswith(
        "Les salaires ne sont pas stockés"
    )


def test_refusal_names_close_offered_columns_only() -> None:
    columns = offered_columns(TABLES)
    assert closest_columns(["staff hire date"], columns) == [
        "staff.hire_date",
        "staff.staff_id",
        "staff.first_name",
    ]
    # Nothing shared (another language): fall back to what retrieval matched,
    # and only when it was offered.
    assert closest_columns(
        ["salaire"], columns, hints=["payment.amount", "ghost.col"]
    ) == ["payment.amount"]
    assert closest_columns(["salaire"], columns) == []
    assert normalize_identifier("amount") is None


def test_refusal_response_lists_suggestions_from_the_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = AnswerabilityItem(what="staff payment amount", status="absent")
    update, _ = _run_check(monkeypatch, _model(item))
    text = update["path_state"]["final_response"]["response"]
    assert "Closest columns offered:" in text
    assert "payment.amount" in text
    assert "ghost" not in text


# -- wiring: gate, graph, no call when off -----------------------------------


class _S(TypedDict, total=False):
    llm: Any
    initial_question: str
    evidence: str
    messages: list
    decision: str
    skip_evidence_refinement: bool
    path_state: dict


class _Graph:
    """The real routers and node around fake generation nodes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, reply: Any, flag: bool):
        self.calls = _Calls(reply)
        monkeypatch.setattr(
            answerability_check, "invoke_with_structured_output", self.calls
        )
        monkeypatch.setattr(
            graph_module, "is_answerability_check_enabled", lambda: flag
        )
        self.visited: list[str] = []

        def stop(name: str) -> Callable[[dict], dict]:
            def node(state: dict) -> dict:
                self.visited.append(name)
                return {}

            return node

        g = StateGraph(_S)
        g.add_node("prepare_candidates", lambda s: {})
        g.add_node(
            "check_answerability",
            agent_wrapper(AnswerabilityCheckAgent(catalog_loader=lambda _db: CATALOG)),
        )
        g.add_node("refine_evidence", stop("refine_evidence"))
        g.add_node("construct_sql_from_candidates", stop("construct"))
        g.set_entry_point("prepare_candidates")
        g.add_conditional_edges(
            "prepare_candidates",
            graph_module._gate_answerability(graph_module.route_evidence_refinement),
            {
                "check_answerability": "check_answerability",
                "refine_evidence": "refine_evidence",
                "construct_sql_from_candidates": "construct_sql_from_candidates",
            },
        )
        g.add_conditional_edges(
            "check_answerability",
            graph_module.route_after_answerability,
            {
                "refuse": END,
                "refine_evidence": "refine_evidence",
                "construct_sql_from_candidates": "construct_sql_from_candidates",
            },
        )
        g.add_edge("refine_evidence", "construct_sql_from_candidates")
        g.add_edge("construct_sql_from_candidates", END)
        self.app = g.compile()

    def run(self, state: dict) -> dict:
        return self.app.invoke(state)


def test_refusal_stops_the_graph_before_any_sql_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _Graph(monkeypatch, _model(ABSENT), flag=True)

    out = graph.run(dict(_state()))

    assert graph.calls.count == 1 and graph.calls.escalations == 1
    assert graph.visited == []  # neither refinement nor construction ran
    assert out["path_state"]["final_response"]["refusal"]["missing"]


def test_answerable_question_continues_to_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _Graph(monkeypatch, _model(IN_SCHEMA), flag=True)
    graph.run(dict(_state()))
    assert graph.visited == ["construct"]

    graph = _Graph(monkeypatch, _model(IN_SCHEMA), flag=True)
    graph.run(dict(_state(evidence="Tenured means long service.")))
    assert graph.visited == ["refine_evidence", "construct"]


def test_flag_off_makes_no_extra_call_and_changes_no_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = [
        _state(),
        _state(evidence="Tenured means long service."),
        _state(evidence="x", skip_evidence_refinement=True),
    ]
    for state in states:
        graph = _Graph(monkeypatch, _model(ABSENT), flag=False)
        route = graph_module._gate_answerability(graph_module.route_evidence_refinement)
        assert route(state) == graph_module.route_evidence_refinement(state)
        graph.run(dict(state))
        assert graph.calls.count == 0
        assert "check_answerability" not in str(graph.visited)
        assert "final_response" not in state["path_state"]
    assert graph.visited and graph.visited[-1] == "construct"


def test_flag_off_means_the_flag_is_not_even_consulted_for_prediction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> bool:
        raise AssertionError("flag read for a prediction question")

    monkeypatch.setattr(graph_module, "is_answerability_check_enabled", boom)
    route = graph_module._gate_answerability(
        graph_module.route_question_type_or_evidence
    )
    state = _state(path_state={"question_type": "prediction"})
    assert route(state) == "prediction"


def test_clarification_answer_turns_skip_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph_module, "is_answerability_check_enabled", lambda: True)
    route = graph_module._gate_answerability(graph_module.route_evidence_refinement)
    plain = _state(evidence="Tenured means long service.")
    pinned = _state(
        evidence=f'Business definitions\n{USER_DEFINITION_PREFIX}Tenured" as: long service'
    )
    assert route(plain) == "check_answerability"
    assert route(pinned) == "refine_evidence"


def test_flag_defaults_off_when_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_ontology.infra import feature_flags

    def unreadable(_key: str) -> Any:
        raise OSError("no database")

    monkeypatch.setattr(feature_flags, "_read_configuration_row", unreadable)
    assert feature_flags.is_answerability_check_enabled() is False
    monkeypatch.setattr(feature_flags, "_read_configuration_row", lambda _k: ("true",))
    assert feature_flags.is_answerability_check_enabled() is True


def test_the_real_graph_has_the_node_and_its_edges() -> None:
    compiled = graph_module.create_graph().compile().get_graph()
    edges = {(e.source, e.target) for e in compiled.edges}
    assert ("prepare_candidates", "check_answerability") in edges
    assert ("check_answerability", "construct_sql_from_candidates") in edges
    assert ("check_answerability", "refine_evidence") in edges
    assert ("check_answerability", "__end__") in edges
    # The ungated routes are still there.
    assert ("prepare_candidates", "construct_sql_from_candidates") in edges
    from auto_ontology.retrieval.text_to_sql.node_labels import NODE_LABELS

    assert "check_answerability" in NODE_LABELS


# -- the answer survives assembly --------------------------------------------


@pytest.fixture(name="main")
def main_fixture(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(llm_invoke, "get_llm_client", lambda **_kwargs: None)
    monkeypatch.setattr(
        llm_invoke, "get_non_reasoning_llm_client", lambda **_kwargs: None
    )
    return importlib.import_module("auto_ontology.retrieval.text_to_sql.main")


def test_refusal_survives_stream_agent_response_assembly(
    main: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    update, _ = _run_check(monkeypatch, _model(ABSENT))
    steps = [{"check_answerability": update}]

    def stream(_state: Any, stream_mode: Any = None, config: Any = None) -> Any:
        for step in steps:
            for node in step:
                yield ("custom", {"type": "step_start", "node": node})
            yield ("updates", step)

    monkeypatch.setattr(
        main, "_build_state", lambda payload: {"path_state": {"target_db": "hr"}}
    )
    monkeypatch.setattr(main, "app", SimpleNamespace(stream=stream))
    events = list(
        main.stream_agent_response(cast(TextToSQLPayload, {"question": "salary?"}))
    )

    result = [e for e in events if e["type"] == "result"]
    assert len(result) == 1 and not [e for e in events if e["type"] == "sql"]
    answer = result[0]["answer"]
    assert answer["refusal"]["missing"] == ["salary of each staff member"]
    assert answer["sql_code"] is None
    assert answer["sql_response_from_db"] is None
    assert [c["code"] for c in answer["caveats"]] == ["unanswerable"]
    assert answer["database"] == "hr"
    assert "The data available here does not hold" in answer["response"]
    # A refusal ends the run: it is never retried as an unconstructable answer.
    assert (
        main._should_retry_full_pipeline(
            {"restore_from": {}, "path_state": {"final_response": answer}},  # type: ignore[arg-type]
            "check_answerability",
        )
        is False
    )
