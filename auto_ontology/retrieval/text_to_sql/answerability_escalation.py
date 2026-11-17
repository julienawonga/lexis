# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Escalation before refusing (answerability check, version 2).

The first pass sees only the tables retrieval selected, so a thing that lives in
a table the relevance filter dropped looks absent. Before a refusal, every item
the first pass called ``absent`` is re-checked in ONE more call against an outline
of the WHOLE catalog of the database (table, column names and types; no
descriptions). The question is refused only if an item is still absent there,
verified in code against that outline.

A truncated outline can rescue an item (positive evidence) but never condemn one:
refusing on partial evidence fails open instead. Pure module: no model, no
database. The catalog is fetched by ``catalog_outline.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from auto_ontology.retrieval.text_to_sql.answerability import (
    OfferedColumn,
    _normalize_text,
    _plain,
    _tokens,
    normalize_identifier,
)

# How many characters of outline the escalation call may carry (roughly 15,000
# tokens). A documented size limit, not tuned on any dataset.
OUTLINE_CHAR_BUDGET = 60_000

EscalationStatus = Literal["found", "still_absent"]


class EscalationItem(BaseModel):
    """The second pass's verdict on one item the first pass called absent."""

    what: str = Field(..., description="The item, copied exactly as given.")
    status: EscalationStatus = Field(
        ...,
        description=(
            "found: a catalog column holds it, or it can be computed from "
            "catalog columns. still_absent: nothing in the catalog holds it "
            "and it cannot be computed."
        ),
    )
    columns: list[str] = Field(
        default_factory=list,
        description="For found: every table.column relied on, copied from the outline.",
    )
    formula: str = Field(
        default="", description="For a computed item: the formula, one line."
    )


class EscalationModel(BaseModel):
    """Structured output of the escalation call."""

    items: list[EscalationItem] = Field(default_factory=list)


ESCALATION_SYSTEM_PROMPT = """A first look at a database, limited to the few tables selected for a question, could not find some of the things the question asks for. You now see an outline of ALL the tables of the database. For each listed item decide whether the database holds it anywhere.

Give each item a `status`:
- found: a column in the outline holds it, or it can be computed from columns in the outline (possibly across several tables joined together). Put EVERY table.column relied on in `columns`, copied exactly from the outline, and for a computed item the formula in one line in `formula`.
- still_absent: no column in the outline holds it and it cannot be computed from any of them.

Rules:
- A revenue, total, count, average, share, ratio, rate per group, rank or period figure is a measure computed from columns, not a column: it is `found` when the columns it needs exist.
- A nearby but different column is NOT a match. Judge by what a column means, never by how similar its name is to a word in the question.
- Return one entry per listed item, with `what` copied exactly. Cite only identifiers that appear in the outline."""

ESCALATION_USER_PROMPT = """{question_block}

ITEMS THE FIRST LOOK COULD NOT FIND:
{items}

OUTLINE OF ALL TABLES (table(column type, ...)):
{outline}"""


@dataclass
class Outline:
    """The catalog outline sent to the escalation call."""

    text: str
    tables: list[dict]  # the tables actually included, as catalog dicts
    truncated: bool
    total_tables: int


def _table_line(table: dict) -> str:
    cols = []
    for column in table.get("columns") or []:
        if isinstance(column, dict) and _plain(column.get("name")):
            cols.append(
                f"{_plain(column.get('name'))} "
                f"{_plain(column.get('data_type')) or 'unknown'}"
            )
    return f"{_plain(table.get('name'))}({', '.join(cols)})"


def build_outline(
    tables: list[dict], priority_text: list[str], budget: int = OUTLINE_CHAR_BUDGET
) -> Outline:
    """Compact outline of a whole catalog: names and types only.

    Whole tables stay in catalog order when they all fit. Otherwise tables are
    taken in decreasing order of the words their table and column names share
    with ``priority_text`` (the items being re-checked; ties keep catalog order)
    for as long as they fit ``budget``, and the outline is marked truncated.
    """
    valid = [
        t
        for t in tables
        if isinstance(t, dict) and _plain(t.get("name")) and t.get("columns")
    ]
    lines = [_table_line(t) for t in valid]
    if sum(len(line) + 1 for line in lines) <= budget:
        return Outline("\n".join(lines), valid, False, len(valid))

    wanted: set[str] = set()
    for text in priority_text:
        wanted |= _tokens(text)

    def shared(index: int) -> int:
        table = valid[index]
        names = " ".join(
            [_plain(table.get("name"))]
            + [
                _plain(c.get("name"))
                for c in table.get("columns") or []
                if isinstance(c, dict)
            ]
        )
        return len(wanted & _tokens(names))

    order = sorted(range(len(valid)), key=lambda i: (-shared(i), i))
    used = 0
    kept: list[int] = []
    for index in order:
        cost = len(lines[index]) + 1
        if used + cost <= budget:
            used += cost
            kept.append(index)
    kept.sort()
    return Outline(
        "\n".join(lines[i] for i in kept),
        [valid[i] for i in kept],
        True,
        len(valid),
    )


@dataclass
class EscalationResult:
    """Verified outcome of the second pass for the items it was asked about."""

    complete: bool  # a verdict for every item asked about
    found: dict[str, list[str]] = field(default_factory=dict)
    still_absent: list[str] = field(default_factory=list)
    invalid_citations: dict[str, list[str]] = field(default_factory=dict)


def verify_escalation(
    asked: list[str], result: EscalationModel, outline_columns: list[OfferedColumn]
) -> EscalationResult:
    """Match verdicts to the items asked about and check citations; code only.

    A verdict is matched by its ``what`` (whitespace and case aside), or by
    position when the model returned exactly as many entries as were asked. An
    item with no verdict makes the result incomplete, which the caller treats as
    "could not check", never as absence. ``found`` needs at least one cited column
    that exists in the outline; otherwise the item is ``still_absent``.
    """
    by_key = {item.key: item for item in outline_columns}
    normalized = [_normalize_text(w) for w in asked]
    verdicts: dict[int, EscalationItem] = {}
    for entry in result.items:
        key = _normalize_text(entry.what)
        for index, want in enumerate(normalized):
            if want == key and index not in verdicts:
                verdicts[index] = entry
                break
    if len(verdicts) < len(asked) and len(result.items) == len(asked):
        verdicts = dict(enumerate(result.items))
    outcome = EscalationResult(complete=len(verdicts) == len(asked))
    for index, what in enumerate(asked):
        entry = verdicts.get(index)
        if entry is None:
            continue
        valid: list[str] = []
        invalid: list[str] = []
        for cited in entry.columns:
            key = normalize_identifier(cited)
            offered = by_key.get(key) if key else None
            if offered is not None:
                if offered.identifier not in valid:
                    valid.append(offered.identifier)
            else:
                invalid.append(str(cited))
        if entry.status == "found" and valid:
            outcome.found[what] = valid
        else:
            outcome.still_absent.append(what)
            if invalid:
                outcome.invalid_citations[what] = invalid
    return outcome
