# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Answerability node: refuse a question the offered data cannot answer.

Sits between ``prepare_candidates`` and SQL generation, only when the
``answerability_check_enabled`` flag is on (see ``text_to_sql_graph``). It makes
one structured call on the non-reasoning model, verifies the claims in code and
either ends the run with a refusal or lets generation proceed. The mechanism and
the reasons for each rule are in ``answerability.py`` and
``docs/answerability.md``.

It fails open: any problem with the check itself (no model, a failed or empty
call, nothing offered to check against) lets the question through to normal
generation with the ``answerability_unchecked`` caveat. A broken check must
never block a question.
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from auto_ontology.retrieval.entity_coverage.prompts import format_glossary_section
from auto_ontology.retrieval.text_to_sql.answerability import (
    NO_DEFINITIONS,
    PROCEED,
    REFUSE,
    SYSTEM_PROMPT,
    UNANSWERABLE_CAVEAT_CODE,
    UNANSWERABLE_CAVEAT_MESSAGE,
    UNCHECKED_CAVEAT,
    USER_PROMPT,
    AnswerabilityModel,
    build_refusal,
    build_refusal_response,
    closest_columns,
    format_offered_schema,
    language_rule,
    offered_columns,
    refusal_required,
    verify_items,
)
from auto_ontology.retrieval.text_to_sql.base import (
    BaseAgent,
    add_caveat,
    record_thought,
)
from auto_ontology.retrieval.text_to_sql.prompts import format_dual_question_block
from auto_ontology.retrieval.text_to_sql.question_language import (
    KEY_LANGUAGE,
    language_name,
)
from auto_ontology.retrieval.text_to_sql.state import (
    AgentState,
    get_original_question,
    get_question_for_processing,
)
from auto_ontology.utils.llm_invoke import invoke_with_structured_output

GRAPH_NODE_NAME = "check_answerability"


def _definitions_text(state: AgentState) -> str:
    """Everything the generation prompt treats as a definition, as one block.

    The request evidence already carries the retrieved Term definitions and what
    the user stated; certified SQL attributes, custom analyses and the glossary
    are added so that anything defined to the generator counts as available here
    too.
    """
    path_state = state.get("path_state", {})
    parts: list[str] = []
    evidence = (state.get("evidence") or "").strip()
    if evidence:
        parts.append(evidence)
    for key in ("custom_analyses_str", "sql_attributes_str"):
        value = path_state.get(key)
        if isinstance(value, (list, tuple)):
            value = "\n".join(str(v) for v in value)
        value = str(value or "").strip()
        if value:
            parts.append(value)
    synonyms = path_state.get("term_synonyms") or {}
    if isinstance(synonyms, dict) and synonyms:
        parts.append(
            "\n".join(
                f"{term}: also known as {', '.join(names)}"
                for term, names in synonyms.items()
            )
        )
    glossary = format_glossary_section(state.get("glossary") or [])
    if glossary:
        parts.append(glossary)
    return "\n\n".join(parts)


def _semantic_hints(path_state: dict[str, Any]) -> list[str]:
    """``table.column`` of the columns retrieval matched to the question."""
    entries = [
        path_state.get("primary_attribute"),
        *(path_state.get("attribute_join_paths") or []),
    ]
    return [
        f"{e['table_name']}.{e['col_name']}"
        for e in entries
        if isinstance(e, dict) and e.get("table_name") and e.get("col_name")
    ]


class AnswerabilityCheckAgent(BaseAgent):
    """Decide whether the offered tables and definitions can answer the question.

    Output: ``decision`` is ``"answerable"`` (carry on to generation, possibly
    with the ``answerability_unchecked`` caveat) or ``"unanswerable"`` (the run
    ends with ``path_state["final_response"]`` carrying the refusal).
    """

    def __init__(self) -> None:
        super().__init__("answerability_check", failure_decision=PROCEED)

    def execute(self, state: AgentState) -> Dict[str, Any]:
        try:
            return self._check(state)
        except Exception as exc:  # noqa: BLE001 - a broken check must not block
            self.logger.warning(
                "Answerability check failed (%s: %s); answering without it",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return self._unchecked(state)

    def _unchecked(self, state: AgentState) -> Dict[str, Any]:
        path_state = state.get("path_state", {})
        add_caveat(path_state, *UNCHECKED_CAVEAT)
        return {"path_state": path_state, "decision": PROCEED}

    def _check(self, state: AgentState) -> Dict[str, Any]:
        path_state = state.get("path_state", {})
        llm = state.get("llm")
        columns = offered_columns(path_state.get("relevant_tables"))
        if llm is None or not columns:
            self.logger.warning(
                "Answerability check skipped: llm=%s offered_columns=%d",
                llm is not None,
                len(columns),
            )
            return self._unchecked(state)

        language_code = path_state.get(KEY_LANGUAGE)
        try:
            language = language_name(str(language_code)) if language_code else None
        except Exception:  # noqa: BLE001 - language metadata is best effort
            language = None
        definitions = _definitions_text(state)
        question_block = format_dual_question_block(
            get_original_question(state), get_question_for_processing(state)
        )
        messages = [
            SystemMessage(
                content=SYSTEM_PROMPT.format(language_rule=language_rule(language))
            ),
            HumanMessage(
                content=USER_PROMPT.format(
                    question_block=question_block,
                    schema=format_offered_schema(columns),
                    definitions=definitions or NO_DEFINITIONS,
                )
            ),
        ]
        result = invoke_with_structured_output(llm, messages, AnswerabilityModel)
        if not isinstance(result, AnswerabilityModel) or not result.items:
            # None (call failed), unparsable output, or a list with no item: the
            # model did not make a single checkable claim, so there is nothing
            # to verify and no basis to refuse.
            self.logger.warning("Answerability check returned no usable items")
            return self._unchecked(state)

        checked = verify_items(result.items, columns, definitions)
        if not refusal_required(checked):
            record_thought(
                path_state,
                GRAPH_NODE_NAME,
                "Every thing the question asks for is held by the offered data: "
                + "; ".join(f"{c.what} ({c.status})" for c in checked)
                + ".",
            )
            return {"path_state": path_state, "decision": PROCEED}

        refusal = build_refusal(checked)
        suggested = closest_columns(
            refusal["missing"], columns, _semantic_hints(path_state)
        )
        text = build_refusal_response(
            missing=refusal["missing"],
            suggested=suggested,
            model_message=result.user_message,
            language=str(language_code) if language_code else None,
        )
        add_caveat(path_state, UNANSWERABLE_CAVEAT_CODE, UNANSWERABLE_CAVEAT_MESSAGE)
        record_thought(
            path_state,
            GRAPH_NODE_NAME,
            "Not answerable from the offered data. Missing: "
            + "; ".join(refusal["missing"])
            + ".",
        )
        # Same keys as a successful answer, so persistence, the chart step and
        # the client read it without special-casing; no SQL, no rows.
        final_response = {
            "response": text,
            "sql_code": None,
            "sql_columns": [],
            "custom_analyses_used": [],
            "sql_response_from_db": None,
            "refusal": refusal,
            "caveats": list(path_state.get("caveats") or []),
        }
        self.logger.info("Refusing: missing %s", refusal["missing"])
        return {
            "messages": list(state.get("messages") or []) + [AIMessage(content=text)],
            "path_state": {**path_state, "final_response": final_response},
            "decision": REFUSE,
        }
