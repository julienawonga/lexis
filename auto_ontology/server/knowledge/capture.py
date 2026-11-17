# SPDX-License-Identifier: Apache-2.0
"""Learn a term from a clarification answer: a personal draft, once.

When a person answers "what do you mean by VIP customers?", the answer is also
a definition worth keeping. This module turns it into a **personal draft** in
their own space, with who said it and when, for them to edit and submit for
review later. It changes nothing the model sees: the draft is not retrieved at
answer time, and the evidence the model receives for the turn is built
elsewhere, before this runs.

Two rules:

* **Best effort.** :func:`capture_clarification_answer` never raises and the
  chat route runs it off the request path, so a failure to save the draft can
  neither fail nor slow the chat turn. It is logged and the turn continues.
* **Once per answer.** The draft id is derived from the conversation and the
  clarification id, so a retry (a resubmitted request, a reconnect) finds the
  draft it already made instead of creating a second one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from auto_ontology.dal import knowledge as knowledge_dal
from auto_ontology.dal import terms as terms_dal
from auto_ontology.dal.knowledge_rules import ACTOR_USER, Actor
from auto_ontology.infra.feature_flags import is_knowledge_items_enabled
from auto_ontology.server.knowledge.content import MAX_DEFINITION, MAX_NAME

logger = logging.getLogger(__name__)

#: Namespace of the draft ids derived from a (conversation, clarification) pair.
_CAPTURE_NAMESPACE = uuid.UUID("5b2d9d3e-6a41-4c57-9a77-0c1a7e0f2b11")


def capture_item_id(conversation_id: Any, clarification_id: str) -> str:
    """The id of the draft an answer produces: the same for the same answer."""
    return str(uuid.uuid5(_CAPTURE_NAMESPACE, f"{conversation_id}:{clarification_id}"))


def capture_clarification_answer(
    *,
    user_id: str,
    conversation_id: Any,
    clarification_id: str,
    term: str,
    definition: str,
    database: str | None,
    option_id: str | None,
    asked_at: datetime | None,
    answered_at: datetime | None = None,
) -> dict[str, str] | None:
    """Save the answer as a personal draft; return ``{"id", "name"}`` or ``None``.

    ``None`` when the feature is off, the answer is empty, or anything failed.
    Never raises.
    """
    try:
        if not is_knowledge_items_enabled():
            return None
        name = (term or "").strip()[:MAX_NAME]
        text = (definition or "").strip()[:MAX_DEFINITION]
        if not name or not text:
            return None
        item_id = capture_item_id(conversation_id, clarification_id)
        existing = knowledge_dal.get_item(item_id)
        if existing is not None:
            return {"id": existing["id"], "name": existing["content"].get("name", name)}

        database_id: str | None = None
        database_name: str | None = None
        if database:
            row = terms_dal.resolve_database(database)
            if row is not None:
                database_id, database_name = row["id"], row["name"]
        answered = answered_at or datetime.now(UTC)
        provenance: dict[str, Any] = {
            "source": "clarification",
            "activity": "clarification_answer",
            "conversation_id": str(conversation_id),
            "clarification_id": clarification_id,
            "asked_at": asked_at.isoformat() if asked_at else None,
            "answered_at": answered.isoformat(),
            "evidence": [
                {
                    "type": "clarification",
                    "ref": f"{conversation_id}:{clarification_id}",
                    "excerpt": "answered a clarification question",
                }
            ],
        }
        if option_id is not None:
            provenance["option_id"] = option_id
        else:
            provenance["free_text"] = True
        try:
            created = knowledge_dal.create_draft(
                Actor(ACTOR_USER, user_id),
                kind="term",
                owner_id=user_id,
                content={"name": name, "definition": text, "database": database_name},
                database_id=database_id,
                provenance=provenance,
                item_id=item_id,
            )
        except knowledge_dal.InvalidDraft:
            # Two requests raced for the same answer; the other one won.
            existing = knowledge_dal.get_item(item_id)
            if existing is None:
                raise
            return {"id": existing["id"], "name": name}
        return {"id": created["item"]["id"], "name": name}
    except Exception:  # noqa: BLE001 - a draft that cannot be saved must not hurt the chat
        logger.exception("Could not save the clarification answer as a draft")
        return None
