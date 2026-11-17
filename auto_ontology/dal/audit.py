# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0
"""The audit log: who did which administrative action, and to what.

``audit_event`` is append-only by convention, like ``knowledge_event``: this
module only inserts and reads. Nothing updates or deletes a row, and nothing
prunes the table yet.

Two rules shape it.

**The audit never takes a user action down.** :func:`record` is called after
the action it describes has already succeeded. If the audit write fails (the
database is briefly unreachable, a constraint rejects the row), that is logged
as an error and swallowed: the person who just renamed a Term must not see a
500 because the log could not be written. The cost is a missing line, which the
error log makes visible.

**``details`` never holds a secret or a question.** Each action has an
allowlist of fields in :data:`ALLOWED_DETAILS`; anything else is dropped, and an
action with no entry keeps no details at all. Values are cut down to short
scalars, so a nested object (a whole ``connection`` body, with its password)
cannot ride along under an allowed key either. The client IP is not stored.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store

logger = logging.getLogger(__name__)

ACTOR_USER = "user"
ACTOR_API_TOKEN = "api_token"
ACTOR_SYSTEM = "system"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_ACTION_RE = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")
_MAX_TEXT = 200
_MAX_LIST = 20

#: Fields that may appear in ``details``, per action. Every value is a
#: counter, a flag, a field NAME or an identifier: never free text a user typed
#: about their data, and never a credential. Edit this table, with a test, to
#: record more.
ALLOWED_DETAILS: dict[str, frozenset[str]] = {
    "term.create": frozenset({"database", "table_count", "owner_id"}),
    "term.update": frozenset({"fields"}),
    "term.delete": frozenset({"column_attributes", "vector_rows"}),
    # Connection events name the engine and the language, never a host, a user
    # name, a password or even the names of the fields that were sent.
    "connection.create": frozenset({"type", "ontology_language"}),
    "connection.update": frozenset({"type", "ontology_language"}),
    "connection.delete": frozenset(),
    "semantic_compilation.reset": frozenset(),
    "semantic_compilation.reindex": frozenset({"database"}),
    "group.create": frozenset({"role", "member_count"}),
    "group.update": frozenset({"fields", "member_count"}),
    "group.delete": frozenset(),
    "zone.create": frozenset({"item_count"}),
    "zone.update": frozenset({"fields", "item_count"}),
    "zone.delete": frozenset(),
    "zone.set_status": frozenset({"enabled"}),
    "sql_attribute.create": frozenset({"term_id"}),
    "sql_attribute.update": frozenset({"fields"}),
    "sql_attribute.delete": frozenset(),
    "custom_analysis.create": frozenset(),
    "custom_analysis.update": frozenset(),
    "custom_analysis.delete": frozenset(),
    "semantic_domain.generate": frozenset({"database", "domains"}),
    "semantic_domain.rename": frozenset(),
    "semantic_domain.move_terms": frozenset({"terms"}),
    # Knowledge items: the item id is the target; the content (a definition that
    # may quote a user's question) is never recorded, only the kind and the
    # status or scope change.
    "knowledge.propose": frozenset({"kind", "to_status", "source"}),
    "knowledge.submit": frozenset({"kind", "from_status", "to_status"}),
    "knowledge.approve": frozenset({"kind", "from_status", "to_status", "to_scope"}),
    "knowledge.reject": frozenset({"kind", "from_status", "to_status"}),
    "knowledge.request_changes": frozenset({"kind", "from_status", "to_status"}),
    "knowledge.deprecate": frozenset({"kind", "from_status", "to_status"}),
    "knowledge.promote_scope": frozenset({"kind", "from_scope", "to_scope"}),
}


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    return None


def _sanitize_details(action: str, details: dict[str, Any] | None) -> dict[str, Any]:
    """The allowlisted, size-bounded part of *details* for *action*."""
    allowed = ALLOWED_DETAILS.get(action, frozenset())
    clean: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key not in allowed:
            continue
        if isinstance(value, list | tuple | set | frozenset):
            items = [_clean_scalar(item) for item in list(value)[:_MAX_LIST]]
            clean[key] = [item for item in items if item is not None]
        elif isinstance(value, dict):
            continue
        else:
            clean[key] = _clean_scalar(value)
    return clean


def record(
    action: str,
    *,
    actor_id: str | None = None,
    actor_email: str | None = None,
    actor_kind: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> str | None:
    """Append one event and return its id, or ``None`` when it was not written.

    Never raises: see the module docstring. ``actor_kind`` defaults to
    ``user`` when an actor id is given and ``system`` when none is.
    """
    try:
        if not _ACTION_RE.match(action):
            raise ValueError(f"malformed audit action {action!r}")
        kind = actor_kind or (ACTOR_USER if actor_id else ACTOR_SYSTEM)
        rows = store().query_write(
            s.audit_event.insert()
            .values(
                at=datetime.now(UTC),
                actor_id=actor_id,
                actor_email=actor_email,
                actor_kind=kind,
                action=action,
                target_kind=target_kind,
                target_id=target_id,
                target_name=target_name[:_MAX_TEXT] if target_name else None,
                request_id=request_id,
                details=_sanitize_details(action, details),
            )
            .returning(s.audit_event.c.id)
        )
        return rows[0]["id"]
    except Exception:  # noqa: BLE001 - the audit must never fail the caller
        logger.error("audit: could not record %s", action, exc_info=True)
        return None


def list_events(
    *,
    action_prefix: str | None = None,
    actor_id: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_seq: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Events, newest first, as ``{"events": [...], "next_cursor": int | None}``.

    ``action_prefix`` matches the start of the action (``term.`` for every Term
    event). Pass ``next_cursor`` back as ``before_seq`` for the next page:
    keyset pagination on ``seq``, so a page never shifts when new events arrive.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    query = select(s.audit_event).order_by(s.audit_event.c.seq.desc()).limit(limit + 1)
    if action_prefix:
        query = query.where(
            s.audit_event.c.action.startswith(action_prefix, autoescape=True)
        )
    if actor_id:
        query = query.where(s.audit_event.c.actor_id == actor_id)
    if target_kind:
        query = query.where(s.audit_event.c.target_kind == target_kind)
    if target_id:
        query = query.where(s.audit_event.c.target_id == target_id)
    if since is not None:
        query = query.where(s.audit_event.c.at >= since)
    if until is not None:
        query = query.where(s.audit_event.c.at < until)
    if before_seq is not None:
        query = query.where(s.audit_event.c.seq < before_seq)

    rows = store().query_read(query)
    page = rows[:limit]
    next_cursor = page[-1]["seq"] if len(rows) > limit and page else None
    return {"events": page, "next_cursor": next_cursor}
