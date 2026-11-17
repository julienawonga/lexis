# SPDX-License-Identifier: Apache-2.0

"""The ``declared`` signal: tags in the prompt, the model's list, its verification.

No model is called: the LLM is a fake that returns a canned structured output.
"""

from __future__ import annotations

import importlib

from types import ModuleType, SimpleNamespace
from typing import Any, Iterator, cast

import pytest

from auto_ontology.retrieval.text_to_sql import knowledge_tags as kg
from auto_ontology.retrieval.text_to_sql import knowledge_trace as kt
from auto_ontology.retrieval.text_to_sql.agents import sql_from_semantic
from auto_ontology.retrieval.text_to_sql.agents.sql_from_semantic import (
    SQLFromCandidatesAgent,
)
from auto_ontology.retrieval.text_to_sql.models import (
    SQLGenerationModel,
    SQLGenerationWithAppliedModel,
)
from auto_ontology.retrieval.text_to_sql.state import TextToSQLPayload
from auto_ontology.utils import llm_invoke

SQL = "SELECT SUM(amount) - SUM(refund) AS net FROM sales.orders"


def _path_state(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "target_db": "shop",
        "primary_attribute": None,
        "relevant_tables": [],
        "relevant_queries": [],
        "offered_terms": [
            {"id": "t1", "name": "Net Revenue", "description": "gross minus refund"},
            {"id": "t2", "name": "Shipped", "description": "status shipped"},
        ],
        "sql_attributes": [
            {"id": "a1", "name": "net", "expression": "sum(amount) - sum(refund)"}
        ],
        "custom_analyses": [
            {"id": "c1", "name": "Orders", "sql": "SELECT carrier FROM shipments"}
        ],
        "retrieved_column_attributes": [{"id": "v1", "name": "Order amount"}],
        "column_attribute_contexts": {"v1": {"col_name": "amount"}},
    }
    base.update(extra)
    return base


def _run(
    monkeypatch: pytest.MonkeyPatch,
    flag: bool,
    declared: list[str] | None,
    path_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list, Any]:
    """Run the generation node; return its result, the messages and the schema."""
    seen: dict[str, Any] = {}

    def fake_invoke(_llm: object, messages: list, schema: type) -> Any:
        seen["messages"] = list(messages)
        seen["schema"] = schema
        fields = dict(thought="t", sql_code=SQL, response="Net revenue.")
        if schema is SQLGenerationWithAppliedModel and declared is not None:
            return schema(**fields, applied_knowledge=declared)
        return schema(**fields)

    monkeypatch.setattr(
        sql_from_semantic, "safe_invoke_with_structured_output", fake_invoke
    )
    monkeypatch.setattr(
        sql_from_semantic, "is_knowledge_applied_record_enabled", lambda: flag
    )
    result = SQLFromCandidatesAgent().execute(
        {
            "llm": object(),
            "initial_question": "net revenue?",
            "evidence": "",
            "messages": [],
            "connectors": [],
            "path_state": path_state if path_state is not None else _path_state(),
        }
    )
    return result, seen["messages"], seen["schema"]


def test_tags_follow_the_trace_order_and_are_rendered_in_one_section() -> None:
    section = kg.render_tag_section(_path_state())
    assert section.startswith("OFFERED KNOWLEDGE (tags)")
    assert kg.INSTRUCTION in section
    assert "[T1] business definition: Net Revenue" in section
    assert "[T2] business definition: Shipped" in section
    assert "[A1] SQL attribute: net" in section
    assert "[C1] custom analysis: Orders" in section
    assert "[V1] column attribute: Order amount (column amount)" in section
    assert kg.render_tag_section({}) == ""


def test_tags_are_rendered_only_when_the_flag_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, on_messages, on_schema = _run(monkeypatch, True, [])
    _, off_messages, off_schema = _run(monkeypatch, False, None)

    assert on_schema is SQLGenerationWithAppliedModel
    assert any("OFFERED KNOWLEDGE (tags)" in m.content for m in on_messages)
    assert not any("OFFERED KNOWLEDGE" in m.content for m in off_messages)
    assert off_schema is SQLGenerationModel


def test_flag_off_prompt_and_schema_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off: no new message and the base class; on differs by exactly one message."""
    result_off, off_messages, off_schema = _run(monkeypatch, False, None)
    _, on_messages, _ = _run(monkeypatch, True, [])

    assert off_schema is SQLGenerationModel
    properties = SQLGenerationModel.model_json_schema()["properties"]
    assert "applied_knowledge" not in properties
    assert "knowledge_declared" not in result_off["path_state"]
    tag_message = [m for m in on_messages if "OFFERED KNOWLEDGE" in m.content]
    assert len(tag_message) == 1
    assert [m.content for m in on_messages if m is not tag_message[0]] == [
        m.content for m in off_messages
    ]


def test_the_extra_field_exists_only_on_the_subclass() -> None:
    base = SQLGenerationModel.model_json_schema()
    sub = SQLGenerationWithAppliedModel.model_json_schema()
    assert set(sub["properties"]) - set(base["properties"]) == {"applied_knowledge"}
    assert list(sub["properties"])[:-1] == list(base["properties"])
    assert sub["required"] == base["required"]
    made = SQLGenerationWithAppliedModel(thought="t", sql_code=SQL, response="r")
    assert made.applied_knowledge == []


def test_declared_tags_are_verified_and_unknown_ones_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, _ = _run(monkeypatch, True, ["T1", "[a1]", "T9", "A1", "nonsense", "X1"])
    assert result["path_state"]["knowledge_declared"] == {
        "tags": ["T1", "A1"],
        "dropped": 3,
    }


def test_empty_declaration_and_nothing_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, _ = _run(monkeypatch, True, [])
    assert result["path_state"]["knowledge_declared"] == {"tags": [], "dropped": 0}
    empty = _path_state(
        offered_terms=[],
        sql_attributes=[],
        custom_analyses=[],
        retrieved_column_attributes=[],
    )
    result, messages, _ = _run(monkeypatch, True, [], empty)
    assert "knowledge_declared" not in result["path_state"]
    assert not any("OFFERED KNOWLEDGE" in m.content for m in messages)


def test_verify_declared_ignores_duplicates_and_non_lists() -> None:
    offered = kg.tag_map(_path_state())
    assert kg.verify_declared(["T1", "t1", "[T1]"], offered) == (["T1"], 0)
    assert kg.verify_declared(None, offered) == ([], 0)
    assert kg.verify_declared("T1", offered) == ([], 0)


def test_agreement_classification() -> None:
    assert kg.agreement(True, True) == "agree"
    assert kg.agreement(False, False) == "agree"
    assert kg.agreement(True, False) == "declared_only"
    assert kg.agreement(False, True) == "found_only"
    assert kg.agreement(None, True) is None
    assert kg.agreement(True, None) is None


def _no_cert(_id: str) -> bool | None:
    return None


def test_trace_carries_both_signals_and_keeps_used() -> None:
    state = _path_state(knowledge_declared={"tags": ["A1", "C1"], "dropped": 0})
    trace = kt.build_knowledge_trace(state, SQL, certified_lookup=_no_cert)
    by = {(e["kind"], e["id"]): e for e in trace}
    sa = by[("sql_attribute", "a1")]
    assert (sa["declared"], sa["found_in_sql"], sa["used"], sa["tag"]) == (
        True,
        True,
        True,
        "A1",
    )
    ca = by[("custom_analysis", "c1")]
    # Declared but nothing in the SQL matches: both signals shown, not merged.
    assert (ca["declared"], ca["found_in_sql"]) == (True, False)
    assert by[("term", "t1")]["declared"] is False
    assert isinstance(sa["matched"], list)


def test_trace_declared_is_null_without_a_record() -> None:
    trace = kt.build_knowledge_trace(_path_state(), SQL, certified_lookup=_no_cert)
    assert trace
    assert all(e["declared"] is None and e["tag"] is None for e in trace)
    assert all(e["found_in_sql"] == e["used"] for e in trace)


@pytest.fixture(name="main")
def main_fixture(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(llm_invoke, "get_llm_client", lambda **_k: None)
    monkeypatch.setattr(llm_invoke, "get_non_reasoning_llm_client", lambda **_k: None)
    return importlib.import_module("auto_ontology.retrieval.text_to_sql.main")


def test_declared_travels_from_generation_state_to_the_result_event(
    main: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generation's state -> final answer dict -> streamed ``result`` event."""
    result, _, _ = _run(monkeypatch, True, ["A1"])
    path_state = {
        **result["path_state"],
        "final_response": {"response": "ok", "sql_code": SQL},
    }

    def items() -> Iterator[tuple[str, Any]]:
        yield ("updates", {"format_response": {"path_state": path_state}})

    monkeypatch.setattr(main, "_build_state", lambda payload: {"path_state": {}})
    monkeypatch.setattr(
        main,
        "app",
        SimpleNamespace(stream=lambda _s, stream_mode=None, config=None: items()),
    )
    monkeypatch.setattr(kt, "_default_certified", _no_cert)
    events = list(
        main.stream_agent_response(cast(TextToSQLPayload, {"question": "net?"}))
    )
    (event,) = [e for e in events if e["type"] == "result"]
    trace = {(e["kind"], e["id"]): e for e in event["answer"]["knowledge_trace"]}
    entry = trace[("sql_attribute", "a1")]
    assert entry["declared"] is True and entry["found_in_sql"] is True
