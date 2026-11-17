# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Audit log: the helper mutating routes call, and the admin-only read route.

The actor is the one every ``audit:`` log line already names: the Lexis user id
the trusted gateway forwards in ``x-auto-ontology-user-id``
(``server/identity.py``). There is no second identity path. A call without that
header, such as a script reaching the private API directly, is recorded with
actor kind ``system``. The gateway does not say whether a person used a session
or an API token, so ``api_token`` is a valid kind that nothing sets yet.

``audit()`` never raises (``dal/audit.record`` swallows a failed write): the
log must not take the action it describes down.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from auto_ontology.dal import audit as audit_dal
from auto_ontology.dal import groups as groups_dal
from auto_ontology.server.identity import resolve_internal_user
from auto_ontology.server.users import postgres_dal

logger = logging.getLogger(__name__)

router = APIRouter()

#: The client may send its own correlation id. The JSON error contract only
#: carries ``error_id`` (``server/errors.py``), so this is usually absent.
REQUEST_ID_HEADER = "x-request-id"


def audit(
    request: Request,
    action: str,
    *,
    target_kind: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record *action* done by the caller of *request*. Never raises."""
    try:
        user_id = resolve_internal_user(request, required=False)
        email = None
        if user_id:
            account = groups_dal.get_account(user_id)
            email = account.get("email") if account else None
        audit_dal.record(
            action,
            actor_id=user_id,
            actor_email=email,
            actor_kind=audit_dal.ACTOR_USER if user_id else audit_dal.ACTOR_SYSTEM,
            target_kind=target_kind,
            target_id=target_id,
            target_name=target_name,
            request_id=(request.headers.get(REQUEST_ID_HEADER) or "").strip()[:128]
            or None,
            details=details,
        )
    except Exception:  # noqa: BLE001 - never fail the caller's action
        logger.error("audit: could not record %s", action, exc_info=True)


class AuditEvent(BaseModel):
    id: str
    at: datetime
    actor_id: str | None
    actor_email: str | None
    actor_kind: str
    action: str
    target_kind: str | None
    target_id: str | None
    target_name: str | None
    request_id: str | None
    details: dict[str, Any]


class AuditEventsResponse(BaseModel):
    data: list[AuditEvent]
    next_cursor: int | None


def _require_admin(request: Request) -> None:
    """401 without a named caller, 403 unless that caller is an admin.

    Stricter than ``enforce_permission``, which lets a headerless call through:
    the log names people, so an unnamed caller does not read it.
    """
    user_id = resolve_internal_user(request, required=True)
    if not postgres_dal.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Administrators only")


@router.get("/audit-events", response_model=AuditEventsResponse)
def list_audit_events(
    request: Request,
    action_prefix: str | None = Query(
        default=None, description="Match the start of the action, e.g. `term.`."
    ),
    actor_id: str | None = Query(default=None),
    target_kind: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    since: datetime | None = Query(default=None, description="At or after."),
    until: datetime | None = Query(default=None, description="Before."),
    cursor: int | None = Query(
        default=None, ge=1, description="`next_cursor` of the previous page."
    ),
    limit: int = Query(default=audit_dal.DEFAULT_LIMIT, ge=1, le=audit_dal.MAX_LIMIT),
) -> dict:
    """List audit events, newest first (administrators only).

    Records administrative and governance actions: who did what to which
    target, and when. Never holds secrets, question text or the client IP.
    Pass ``next_cursor`` back as ``cursor`` for the next page.
    """
    _require_admin(request)
    page = audit_dal.list_events(
        action_prefix=action_prefix,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        since=since,
        until=until,
        before_seq=cursor,
        limit=limit,
    )
    return {"data": page["events"], "next_cursor": page["next_cursor"]}
