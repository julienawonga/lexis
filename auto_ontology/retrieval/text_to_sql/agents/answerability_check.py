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

from typing import Any, Callable, Dict

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
from auto_ontology.retrieval.text_to_sql.answerability_escalation import (
    ESCALATION_SYSTEM_PROMPT,
    ESCALATION_USER_PROMPT,
    EscalationModel,
    EscalationResult,
    Outline,
    build_outline,
    verify_escalation,
)
from auto_ontology.retrieval.text_to_sql.catalog_outline import load_catalog_tables
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

    def __init__(self, catalog_loader: Callable[[str], list[dict]] | None = None):
        super().__init__("answerability_check", failure_decision=PROCEED)
        # Every table and column of one database; replaceable in tests.
        self.catalog_loader = catalog_loader or load_catalog_tables

    def _escalate(
        self,
        state: AgentState,
        columns: list,
        absent: list,
        question_block: str,
    ) -> tuple[EscalationResult, Outline] | None:
        """Re-check the absent items against the whole catalog, or ``None``.

        ``None`` means "could not check": no database to read, a failed read or
        call, an empty catalog, or a verdict missing for some item. The caller
        then fails open.
        """
        path_state = state.get("path_state", {})
        database = path_state.get("target_db") or next(
            (
                t.get("database_name")
                for t in path_state.get("relevant_tables") or []
                if isinstance(t, dict) and t.get("database_name")
            ),
            None,
        )
        llm = state.get("llm")
        if not database or llm is None:
            self.logger.warning("Escalation skipped: no database or no model client")
            return None
        try:
            catalog = self.catalog_loader(str(database))
        except Exception:  # noqa: BLE001 - fail open
            self.logger.warning("Escalation: reading the catalog failed", exc_info=True)
            return None
        asked = [item.what for item in absent]
        outline = build_outline(catalog, asked)
        if not outline.tables:
            self.logger.warning("Escalation: no catalog tables for %r", database)
            return None
        if outline.truncated:
            self.logger.warning(
                "Escalation outline truncated to %d of %d tables; it can rescue "
                "an item but will not refuse on partial evidence",
                len(outline.tables),
                outline.total_tables,
            )
        messages = [
            SystemMessage(content=ESCALATION_SYSTEM_PROMPT),
            HumanMessage(
                content=ESCALATION_USER_PROMPT.format(
                    question_block=question_block,
                    items=chr(10).join(f"- {what}" for what in asked),
                    outline=outline.text,
                )
            ),
        ]
        reply = invoke_with_structured_output(llm, messages, EscalationModel)
        if not isinstance(reply, EscalationModel) or not reply.items:
            self.logger.warning("Escalation returned no usable items")
            return None
        result = verify_escalation(asked, reply, offered_columns(outline.tables))
        if not result.complete:
            self.logger.warning("Escalation did not cover every item")
            return None
        return result, outline

    @staticmethod
    def _add_cited_tables(
        path_state: dict[str, Any], outline: Outline, cited: list[str]
    ) -> list[str]:
        """Append the catalog tables the second pass cited to the offered tables.

        Same dict shape as ``relevant_tables`` entries (name, schema_name,
        database_name, columns), so generation prints them like any other. Only
        the cited tables are added, not the intermediate tables a join between
        them may need; generation's own discovery handles those.
        """
        have = {
            str(t.get("name") or "").casefold()
            for t in path_state.get("relevant_tables") or []
            if isinstance(t, dict)
        }
        wanted = {c.split(".")[0].casefold() for c in cited}
        added = [
            t
            for t in outline.tables
            if str(t.get("name")).casefold() in wanted
            and str(t.get("name")).casefold() not in have
        ]
        if added:
            path_state["relevant_tables"] = [
                *(path_state.get("relevant_tables") or []),
                *added,
            ]
        return [str(t["name"]) for t in added]

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
        if refusal_required(checked):
            absent = [c for c in checked if c.status == "absent"]
            escalation = self._escalate(state, columns, absent, question_block)
            if escalation is None:
                return self._unchecked(state)
            second, outline = escalation
            if second.still_absent and outline.truncated:
                # Partial evidence can rescue an item but not condemn one.
                return self._unchecked(state)
            cited: list[str] = []
            for item in absent:
                if item.what in second.found:
                    item.status = "in_schema"
                    item.valid_columns = second.found[item.what]
                    cited += second.found[item.what]
                else:
                    item.why_absent += (
                        "; still not found in the outline of the whole catalog "
                        f"({outline.total_tables} tables)"
                    )
            if not refusal_required(checked):
                added = self._add_cited_tables(path_state, outline, cited)
                record_thought(
                    path_state,
                    GRAPH_NODE_NAME,
                    "Not in the first tables, found elsewhere in the catalog: "
                    + "; ".join(
                        f"{w} ({', '.join(c)})" for w, c in second.found.items()
                    )
                    + (f". Added tables: {', '.join(added)}." if added else "."),
                )
                return {"path_state": path_state, "decision": PROCEED}
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
