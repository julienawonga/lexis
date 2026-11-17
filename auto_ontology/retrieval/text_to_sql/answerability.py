# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Decide, before any SQL is written, whether the offered data can answer.

Behind the ``answerability_check_enabled`` flag (off by default). The failure it
addresses: retrieval always finds a nearest neighbour and generation must emit
SQL, so a question about something the database does not hold gets a result for
a nearby column, silently.

One structured model call lists every thing the question asks for and says
where each one lives. Everything after that is code:

* each cited ``table.column`` must be one of the offered columns;
* an item that claims to be held or derivable but cites no valid column is
  ``absent``;
* an item claimed as defined by the business definitions must quote them
  verbatim, or cite a valid column;
* the question is refused if and only if at least one item is ``absent``.

There is no score, no distance and no numeric threshold. The model never grades
its own answer: it makes a checkable claim ("this is in ``t.c``") and the code
checks it against the schema it was shown.

Version 2 adds an escalation before any refusal (``answerability_escalation.py``)
and a stricter first-pass rule that computed measures are not absent.

This module is pure (no model or database access); the node is
``agents/answerability_check.py``.
"""

from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

# Routing decisions of the node.
PROCEED = "answerable"
REFUSE = "unanswerable"

# Caveat codes. ``unanswerable`` is the marker the evaluation harness scores
# (``dev_tools/evals/refusal.py``); the other says the check could not run.
UNANSWERABLE_CAVEAT_CODE = "unanswerable"
UNANSWERABLE_CAVEAT_MESSAGE = (
    "The data offered for this question does not hold something it asks for, "
    "so no query was run and no answer is given."
)
UNCHECKED_CAVEAT = (
    "answerability_unchecked",
    "Whether the data can answer this question could not be checked, so the "
    "question was answered without that check. Check the answer before relying "
    "on it.",
)

# Display limits only: how many near columns the refusal names, and how long a
# column description may be in the check's prompt. They never decide whether to
# refuse and are not tuned on any dataset.
MAX_SUGGESTED_COLUMNS = 3
MAX_DESCRIPTION_CHARS = 120

ItemStatus = Literal["in_schema", "derivable", "defined", "absent"]


class AnswerabilityItem(BaseModel):
    """One thing the question asks for, and where the model says it lives."""

    what: str = Field(
        ...,
        description=(
            "A short phrase naming one entity, attribute, measure, filter or "
            "time span the question asks for, in the language of the question."
        ),
    )
    status: ItemStatus = Field(
        ...,
        description=(
            "in_schema: an offered column or table holds it. derivable: it can "
            "be computed from offered columns. defined: the business "
            "definitions define it. absent: nothing offered holds it and it "
            "cannot be computed."
        ),
    )
    columns: list[str] = Field(
        default_factory=list,
        description=(
            "The exact table.column identifiers relied on, copied from the "
            "offered list. Empty only for absent, or for defined when the "
            "definition names no column."
        ),
    )
    formula: str = Field(
        default="",
        description="For derivable: how it is computed from those columns, one line.",
    )
    quote: str = Field(
        default="",
        description=(
            "For defined: a short fragment copied word for word from the "
            "business definitions that defines it."
        ),
    )


class AnswerabilityModel(BaseModel):
    """Structured output of the check."""

    items: list[AnswerabilityItem] = Field(
        default_factory=list,
        description="Every distinct thing the question asks for.",
    )
    user_message: str = Field(
        default="",
        description=(
            "Empty unless at least one item is absent. Then one or two plain "
            "sentences, in the language of the question, saying what the data "
            "does not hold and that no query was run."
        ),
    )


SYSTEM_PROMPT = """You decide whether a database can answer a question, BEFORE any SQL is written. You do not write SQL and you never answer the question.

List EVERY distinct thing the question asks for: each entity, attribute, measure, filter condition and time span. For each one give a `status`:
- in_schema: an offered column or table holds it directly. Put the exact identifiers in `columns`, written table.column as in the list below.
- derivable: it can be computed from offered columns (see the rule on computed measures below). Put EVERY column used in `columns` and the formula, in one line, in `formula`.
- defined: the BUSINESS DEFINITIONS section below defines it (a term, a certified metric or attribute, or something the user stated). Put a short fragment copied WORD FOR WORD from that section in `quote`, and the columns it relies on in `columns` when it names any.
- absent: nothing offered holds it and it cannot be computed from what is offered.

Rules:
- A revenue, total, count, average, share, ratio, rate per group, rank or period figure is a MEASURE COMPUTED from columns, not a column. It is `derivable` whenever the columns it needs exist among the offered ones, even when no column carries its name and even when it needs a join: name those columns and give the formula in one line. For instance, "total weight per crate", in an invented schema with items(weight, crate_id), is derivable: SUM(items.weight) grouped by items.crate_id. `absent` is ONLY for a thing that no offered column holds and that cannot be computed from any offered column.
- An item that only describes how to group, order, limit or present the result (per group, top N, sorted by, descending) is not a separate item: the thing being grouped or ranked is the item.
- A nearby but different column is NOT a match. A column that is merely related to what is asked does not hold it. Judge by what a column means (its name and description, in any language), never by how similar its name is to a word in the question. If a column's name or description states the same meaning as the thing asked for, it holds it.
- Anything defined in the BUSINESS DEFINITIONS section is available, even when no column carries its name.
- Wording that only frames the request (show, list, give me, top, sort, how many) is not an item. The counting, grouping or ranking itself is derivable from rows.
- A value the user names as a filter (a person, a title, a place) is an item only for the attribute it filters on. Whether that value exists in the data is not your concern.
- If the question assumes something the schema cannot represent, that thing is an item with status absent.
- Do not judge whether the question is sensible or ambiguous. Judge only whether the offered data holds the things it names.
- Cite only identifiers that appear in the offered list, exactly as written there.
- `user_message`: leave it empty unless at least one item is absent. Otherwise write one or two plain sentences telling the user which things the data does not hold, and that no query was run. Never suggest a substitute, never state a value, never answer the question.
{language_rule}"""

USER_PROMPT = """{question_block}

OFFERED TABLES AND COLUMNS (table.column (type) - description):
{schema}

BUSINESS DEFINITIONS (anything defined here counts as available):
{definitions}"""

NO_DEFINITIONS = "(none)"


def language_rule(language_name: str | None) -> str:
    """Prompt line naming the language of ``what`` and ``user_message``."""
    if language_name:
        return (
            f"- Write `what` and `user_message` in {language_name}, the language "
            "of the user's own request."
        )
    return (
        "- Write `what` and `user_message` in the language of the user's own "
        "request ('Original user request' when two versions are shown)."
    )


# --------------------------------------------------------------------------
# What was offered
# --------------------------------------------------------------------------


def _plain(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_identifier_part(part: str) -> str:
    return part.strip().strip("\"'`[]").strip()


@dataclass(frozen=True)
class OfferedColumn:
    """One offered column, as the check's prompt names it."""

    table: str
    column: str
    data_type: str
    description: str

    @property
    def identifier(self) -> str:
        return f"{self.table}.{self.column}"

    @property
    def key(self) -> tuple[str, str]:
        return (self.table.casefold(), self.column.casefold())


def offered_columns(tables: list[dict] | None) -> list[OfferedColumn]:
    """The columns of the candidate tables, in order, without duplicates."""
    seen: set[tuple[str, str]] = set()
    offered: list[OfferedColumn] = []
    for table in tables or []:
        if not isinstance(table, dict):
            continue
        table_name = _plain(table.get("name"))
        columns = table.get("columns")
        if not table_name or not isinstance(columns, list):
            continue
        for column in columns:
            if not isinstance(column, dict):
                continue
            name = _plain(column.get("name"))
            if not name:
                continue
            item = OfferedColumn(
                table=table_name,
                column=name,
                data_type=_plain(column.get("data_type")) or "unknown",
                description=_plain(column.get("description"))[:MAX_DESCRIPTION_CHARS],
            )
            if item.key not in seen:
                seen.add(item.key)
                offered.append(item)
    return offered


def format_offered_schema(columns: list[OfferedColumn]) -> str:
    """Render the offered columns, one per line, grouped by table."""
    lines: list[str] = []
    for item in columns:
        line = f"{item.identifier} ({item.data_type})"
        if item.description:
            line += f" - {item.description}"
        lines.append(line)
    return "\n".join(lines)


def normalize_identifier(cited: str) -> tuple[str, str] | None:
    """``(table, column)`` casefolded from a cited identifier, or ``None``.

    Accepts ``table.column`` and longer qualified forms (``schema.table.column``,
    ``database.schema.table.column``), keeping the last two parts, and ignores
    identifier quoting.
    """
    parts = [_clean_identifier_part(p) for p in str(cited or "").split(".")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return None
    return (parts[-2].casefold(), parts[-1].casefold())


def _normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


# --------------------------------------------------------------------------
# Deterministic verification
# --------------------------------------------------------------------------


@dataclass
class CheckedItem:
    """An item after verification against the offered schema."""

    what: str
    claimed: str
    status: str  # in_schema | derivable | defined | absent (final)
    valid_columns: list[str] = field(default_factory=list)
    invalid_columns: list[str] = field(default_factory=list)
    why_absent: str = ""


def verify_items(
    items: list[AnswerabilityItem],
    columns: list[OfferedColumn],
    definitions_text: str,
) -> list[CheckedItem]:
    """Check every claim against the schema that was offered; code only.

    * ``absent`` stays absent.
    * ``in_schema`` / ``derivable`` need at least one cited column that exists
      among the offered ones; otherwise the item is absent.
    * ``defined`` holds when its quote appears verbatim in the definitions the
      model was given (whitespace and case aside), or when it cites at least one
      valid column; otherwise it is absent. A trivially short quote therefore
      passes, which errs toward answering, never toward refusing.
    """
    by_key = {item.key: item for item in columns}
    haystack = _normalize_text(definitions_text)
    checked: list[CheckedItem] = []
    for item in items:
        what = _plain(item.what) or "(unnamed)"
        valid: list[str] = []
        invalid: list[str] = []
        for cited in item.columns:
            key = normalize_identifier(cited)
            offered = by_key.get(key) if key else None
            if offered is not None:
                if offered.identifier not in valid:
                    valid.append(offered.identifier)
            else:
                invalid.append(str(cited))
        record = CheckedItem(
            what=what,
            claimed=item.status,
            status=item.status,
            valid_columns=valid,
            invalid_columns=invalid,
        )
        if item.status == "absent":
            record.why_absent = "nothing offered holds it"
        elif item.status in ("in_schema", "derivable"):
            if not valid:
                record.status = "absent"
                record.why_absent = (
                    "no cited column exists among the offered columns"
                    + (f" (cited: {', '.join(invalid)})" if invalid else "")
                )
        elif item.status == "defined":
            quote = _normalize_text(item.quote)
            if not ((quote and quote in haystack) or valid):
                record.status = "absent"
                record.why_absent = (
                    "its quote is not in the business definitions and no valid "
                    "column is cited"
                )
        else:  # a status outside the schema cannot be trusted
            record.status = "absent"
            record.why_absent = f"unrecognised status {item.status!r}"
        checked.append(record)
    return checked


def refusal_required(checked: list[CheckedItem]) -> bool:
    """The refusal decision: at least one item is absent. Nothing else counts."""
    return any(item.status == "absent" for item in checked)


# --------------------------------------------------------------------------
# The refusal answer
# --------------------------------------------------------------------------

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _tokens(text: str) -> set[str]:
    """Lowercase words of at least three letters, with a plural 's' removed."""
    words: set[str] = set()
    for chunk in _WORD.findall(_CAMEL.sub(" ", text or "")):
        word = chunk.casefold()
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        if len(word) >= 3:
            words.add(word)
    return words


def closest_columns(
    missing: list[str],
    columns: list[OfferedColumn],
    hints: list[str] | None = None,
    limit: int = MAX_SUGGESTED_COLUMNS,
) -> list[str]:
    """Offered columns nearest to what is missing, chosen without a model.

    Ranked by the number of words an offered column's table, name and
    description share with the missing phrases (ties keep schema order). When no
    word is shared (the question may be in another language) the columns that
    retrieval already matched to the question, ``hints``, are used if they are
    among the offered ones. A display aid only: it never affects whether the
    question is refused.
    """
    wanted: set[str] = set()
    for phrase in missing:
        wanted |= _tokens(phrase)
    scored: list[tuple[int, int, OfferedColumn]] = []
    for position, item in enumerate(columns):
        overlap = len(
            wanted & _tokens(f"{item.table} {item.column} {item.description}")
        )
        if overlap:
            scored.append((-overlap, position, item))
    scored.sort(key=lambda row: (row[0], row[1]))
    picked = [row[2].identifier for row in scored[:limit]]
    if picked:
        return picked
    by_key = {item.key: item for item in columns}
    for hint in hints or []:
        key = normalize_identifier(hint)
        offered = by_key.get(key) if key else None
        if offered is not None and offered.identifier not in picked:
            picked.append(offered.identifier)
        if len(picked) >= limit:
            break
    return picked


# Fallback wording, used only when the model gave no message of its own. The
# model's `user_message` is written in the user's language; these cover the case
# where it is missing. Unknown languages get English.
_TEMPLATES: dict[str, tuple[str, str]] = {
    "en": (
        "The data available here does not hold what this question asks for: "
        "{missing}. I did not run a query, because any answer would be about "
        "something else.",
        "Closest columns offered: {columns}. You could ask about one of these instead.",
    ),
    "fr": (
        "Les données disponibles ne contiennent pas ce que cette question "
        "demande : {missing}. Je n'ai exécuté aucune requête, car toute réponse "
        "porterait sur autre chose.",
        "Colonnes les plus proches : {columns}. Vous pouvez poser une question "
        "sur l'une d'elles.",
    ),
    "es": (
        "Los datos disponibles no contienen lo que pide esta pregunta: "
        "{missing}. No ejecuté ninguna consulta, porque cualquier respuesta "
        "trataría de otra cosa.",
        "Columnas más cercanas: {columns}. Puede preguntar por una de ellas.",
    ),
    "de": (
        "Die verfügbaren Daten enthalten nicht, wonach diese Frage verlangt: "
        "{missing}. Ich habe keine Abfrage ausgeführt, denn jede Antwort würde "
        "etwas anderes betreffen.",
        "Nächstliegende Spalten: {columns}. Sie können stattdessen nach einer "
        "davon fragen.",
    ),
    "it": (
        "I dati disponibili non contengono ciò che chiede questa domanda: "
        "{missing}. Non ho eseguito alcuna query, perché qualsiasi risposta "
        "riguarderebbe altro.",
        "Colonne più vicine: {columns}. Può chiedere di una di queste.",
    ),
    "pt": (
        "Os dados disponíveis não contêm o que esta pergunta pede: {missing}. "
        "Não executei nenhuma consulta, porque qualquer resposta seria sobre "
        "outra coisa.",
        "Colunas mais próximas: {columns}. Pode perguntar sobre uma delas.",
    ),
}


def _template(language: str | None) -> tuple[str, str]:
    code = (language or "").strip().lower().split("-")[0].split("_")[0]
    return _TEMPLATES.get(code, _TEMPLATES["en"])


def build_refusal_response(
    *,
    missing: list[str],
    suggested: list[str],
    model_message: str,
    language: str | None,
) -> str:
    """The text the user reads: what the data lacks, plus the nearest columns."""
    lead_template, closest_template = _template(language)
    lead = _plain(model_message) or lead_template.format(missing="; ".join(missing))
    if not suggested:
        return lead
    return f"{lead} {closest_template.format(columns=', '.join(suggested))}"


def build_refusal(checked: list[CheckedItem]) -> dict[str, Any]:
    """``answer["refusal"]``: ``{"missing": [...], "reason": "..."}``."""
    absent = [item for item in checked if item.status == "absent"]
    return {
        "missing": [item.what for item in absent],
        "reason": "; ".join(f"{item.what}: {item.why_absent}" for item in absent),
    }
