# SPDX-License-Identifier: Apache-2.0

"""Tags for the knowledge SQL generation is offered, and what the model declares.

Two independent signals describe how an answer used its knowledge, and they are
never merged:

* ``declared``: when ``knowledge_applied_record_enabled`` is on, each offered
  item gets a short tag in the generation prompt (``T1`` Term, ``A1`` SQL
  attribute, ``C1`` custom analysis, ``V1`` column attribute) and the model
  lists the tags it says it applied, in the same structured output as the SQL.
  This is the model's own account, not proof.
* ``found_in_sql``: the deterministic text match of ``knowledge_trace`` (its
  ``used``). It is a text match, not a cause.

This module only builds the tag section, verifies the declared tags and
classifies agreement. It calls no model. Tags are assigned in the order the
trace lists each kind, so a tag is stable for a given prepared state.
"""

from __future__ import annotations

import re

from typing import Any

PREFIX = {
    "term": "T",
    "sql_attribute": "A",
    "custom_analysis": "C",
    "column_attribute": "V",
}

_KIND_LABEL = {
    "term": "business definition",
    "sql_attribute": "SQL attribute",
    "custom_analysis": "custom analysis",
    "column_attribute": "column attribute",
}

_TAG = re.compile(r"^\[?\s*([A-Za-z]\d{1,4})\s*\]?$")

INSTRUCTION = (
    "In applied_knowledge, list the tags of the items below whose definition, "
    "expression or column you actually applied in sql_code ([] if none)."
)


def _items(path_state: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """``(tag, kind, id, label)`` for every offered item, in tag order."""
    rows: list[tuple[str, str, str, str]] = []
    contexts = path_state.get("column_attribute_contexts") or {}

    def add(kind: str, items: Any, label_fn: Any) -> None:
        n = 0
        for item in items or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            n += 1
            rows.append((f"{PREFIX[kind]}{n}", kind, str(item["id"]), label_fn(item)))

    add("term", path_state.get("offered_terms"), lambda t: str(t.get("name") or ""))
    add(
        "sql_attribute",
        path_state.get("sql_attributes"),
        lambda a: str(a.get("name") or ""),
    )
    add(
        "custom_analysis",
        path_state.get("custom_analyses"),
        lambda c: str(c.get("name") or ""),
    )

    def column_label(h: dict) -> str:
        name = str(h.get("name") or "")
        col = str((contexts.get(str(h["id"])) or {}).get("col_name") or "").strip()
        return f"{name} (column {col})" if col else name

    add("column_attribute", path_state.get("retrieved_column_attributes"), column_label)
    return rows


def tag_map(path_state: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Offered tag -> ``(kind, id)``."""
    return {tag: (kind, kid) for tag, kind, kid, _ in _items(path_state)}


def render_tag_section(path_state: dict[str, Any]) -> str:
    """The prompt section listing the tags; ``""`` when nothing was offered."""
    rows = _items(path_state)
    if not rows:
        return ""
    lines = [f"[{tag}] {_KIND_LABEL[kind]}: {label}" for tag, kind, _, label in rows]
    return "OFFERED KNOWLEDGE (tags)\n" + INSTRUCTION + "\n" + "\n".join(lines)


def normalize_tag(raw: Any) -> str | None:
    match = _TAG.match(str(raw or "").strip())
    return match.group(1).upper() if match else None


def verify_declared(raw: Any, offered: dict[str, Any]) -> tuple[list[str], int]:
    """Keep only tags that were actually offered; count the rest.

    Returns ``(verified tags without duplicates, number dropped)``. A tag the
    model invented, repeated or wrote in a form that does not parse is dropped
    (a repeat of a valid tag is not counted as dropped).
    """
    kept: list[str] = []
    dropped = 0
    for item in raw if isinstance(raw, (list, tuple)) else []:
        tag = normalize_tag(item)
        if tag is None or tag not in offered:
            dropped += 1
        elif tag not in kept:
            kept.append(tag)
    return kept, dropped


def declared_record(raw: Any, path_state: dict[str, Any]) -> dict[str, Any]:
    """What to store in ``path_state["knowledge_declared"]``."""
    tags, dropped = verify_declared(raw, tag_map(path_state))
    return {"tags": tags, "dropped": dropped}


def declared_for(
    record: Any, tags: dict[str, tuple[str, str]], kind: str, item_id: str
) -> bool | None:
    """``declared`` for one trace entry; ``None`` without a declaration."""
    if not isinstance(record, dict) or not isinstance(record.get("tags"), list):
        return None
    applied = {tags[t] for t in record["tags"] if t in tags}
    return (kind, item_id) in applied


def agreement(declared: bool | None, found: bool | None) -> str | None:
    """How the two signals relate; ``None`` when either is undecided.

    ``agree`` (both true or both false), ``declared_only`` (the model said it
    applied the item, nothing in the SQL matches), ``found_only`` (matched in
    the SQL but not declared).
    """
    if declared is None or found is None:
        return None
    if declared == found:
        return "agree"
    return "declared_only" if declared else "found_only"
