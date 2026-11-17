# SPDX-License-Identifier: Apache-2.0
"""Routes for learned knowledge items: ``/api/knowledge-items``.

Everything here is behind the ``knowledge_items_enabled`` flag. With it off a
route answers 404 with a plain message, so nothing is exposed by default. The
one exception is ``GET /knowledge-items/status``, which only says whether the
flag is on, so the web app can hide its page.

The routes decide nothing about who may do what. They resolve the caller,
hand the action to ``dal.knowledge.transition`` (the only place a status
changes, and where the permission rules of ``dal/knowledge_rules.py`` live) and
translate its refusals: 404 not found or not visible to the caller, 403 not
allowed, 409 the state does not allow it or the item changed since it was
loaded, 422 the request is malformed.

A person's edit is never overwritten: ``expected_version`` is an optimistic
lock, checked by the DAL under the row lock.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from auto_ontology.dal import groups as groups_dal
from auto_ontology.dal import knowledge as knowledge_dal
from auto_ontology.dal import terms as terms_dal
from auto_ontology.dal.knowledge_rules import Actor
from auto_ontology.infra.feature_flags import (
    is_knowledge_admin_audit_enabled,
    is_knowledge_items_enabled,
)
from auto_ontology.server.audit import audit
from auto_ontology.server.identity import resolve_internal_user
from auto_ontology.server.knowledge.content import InvalidContent, validate_content

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_PAGE = 50
MAX_PAGE = 100
#: How many rows one pass over the store reads while a route-level filter
#: (``mine``, ``reviewable``) is looking for a full page.
_SCAN_CHUNK = 200

DISABLED_MESSAGE = "Knowledge items are not enabled on this server."


def _require_enabled() -> None:
    if not is_knowledge_items_enabled():
        raise HTTPException(status_code=404, detail=DISABLED_MESSAGE)


gated = APIRouter(dependencies=[Depends(_require_enabled)])


# -- models ----------------------------------------------------------------


class KnowledgeStatus(BaseModel):
    enabled: bool


class KnowledgeEventOut(BaseModel):
    at: datetime
    action: str
    actor_type: str
    actor_id: str
    actor_email: str | None = None
    from_status: str | None
    to_status: str
    from_scope: str | None
    to_scope: str
    version: int
    comment: str | None


class KnowledgeItemOut(BaseModel):
    id: str
    kind: str
    status: str
    scope: str
    owner_id: str
    owner_email: str | None = None
    database_id: str | None
    content: dict[str, Any]
    provenance: dict[str, Any]
    current_version: int = Field(
        description="Send it back as `expected_version`: the optimistic lock."
    )
    created_by: str
    created: datetime
    modified: datetime
    allowed_actions: list[str] = Field(
        description="What the caller may do with this item right now."
    )


class KnowledgeItemResponse(BaseModel):
    data: KnowledgeItemOut
    events: list[KnowledgeEventOut]


class KnowledgeItemListResponse(BaseModel):
    data: list[KnowledgeItemOut]
    next_cursor: str | None = None


class KnowledgeItemCreate(BaseModel):
    kind: Literal["term", "synonym"]
    content: dict[str, Any]
    database: str | None = Field(
        default=None, description="Catalog database name or id; omit for a glossary."
    )


class KnowledgeItemEdit(BaseModel):
    content: dict[str, Any]
    expected_version: int = Field(ge=1, description="`current_version` you loaded.")


class KnowledgeTransitionBody(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
    expected_version: int | None = Field(
        default=None, ge=1, description="`current_version` you loaded."
    )


# -- helpers ---------------------------------------------------------------


class _Directory:
    """Account emails for one response, looked up once each."""

    def __init__(self) -> None:
        self._emails: dict[str, str | None] = {}

    def email(self, user_id: str) -> str | None:
        if user_id not in self._emails:
            try:
                account = groups_dal.get_account(user_id)
            except Exception:  # noqa: BLE001 - a name is a nicety, not a need
                account = None
            self._emails[user_id] = account.get("email") if account else None
        return self._emails[user_id]


def _caller(request: Request) -> Actor:
    user_id = resolve_internal_user(request, required=True)
    assert user_id is not None  # required=True raises 401 otherwise
    return knowledge_dal.resolve_actor(user_id)


def _audit_on(actor: Actor) -> bool:
    return actor.role == "admin" and is_knowledge_admin_audit_enabled()


def _not_found(item_id: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=f"Knowledge item {item_id!r} not found"
    )


def _visible_item(actor: Actor, item_id: str) -> dict[str, Any]:
    """The item, or 404: an item the caller may not see does not exist for them."""
    item = knowledge_dal.get_item(item_id)
    if item is None or not knowledge_dal.can_view(actor, item, audit=_audit_on(actor)):
        raise _not_found(item_id)
    return item


def _item_out(
    actor: Actor, item: dict[str, Any], directory: _Directory
) -> dict[str, Any]:
    return {
        **{k: item[k] for k in KnowledgeItemOut.model_fields if k in item},
        "owner_email": directory.email(item["owner_id"]),
        "allowed_actions": knowledge_dal.allowed_actions(actor, item),
    }


def _event_out(event: dict[str, Any], directory: _Directory) -> dict[str, Any]:
    return {
        **{k: event[k] for k in KnowledgeEventOut.model_fields if k in event},
        "actor_email": directory.email(event["actor_id"]),
    }


def _response(actor: Actor, item_id: str) -> dict[str, Any]:
    directory = _Directory()
    item = knowledge_dal.get_item(item_id)
    if item is None:
        raise _not_found(item_id)
    return {
        "data": _item_out(actor, item, directory),
        "events": [
            _event_out(e, directory) for e in knowledge_dal.list_events(item_id)
        ],
    }


def _raise_for(exc: knowledge_dal.KnowledgeError) -> None:
    """Translate a DAL refusal into the HTTP status that names it."""
    if isinstance(exc, knowledge_dal.ItemNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, knowledge_dal.PermissionDenied):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, knowledge_dal.VersionConflict | knowledge_dal.InvalidTransition):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def _encode_cursor(created: datetime, item_id: str) -> str:
    raw = f"{created.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created, item_id = raw.split("|", 1)
        return datetime.fromisoformat(created), item_id
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


def _resolve_database(database: str | None) -> dict[str, Any] | None:
    if database is None or not database.strip():
        return None
    row = terms_dal.resolve_database(database.strip())
    if row is None:
        raise HTTPException(
            status_code=422, detail=f"Database {database!r} is not in the catalog"
        )
    return row


def _validated(kind: str, content: Any) -> dict[str, Any]:
    try:
        return validate_content(kind, content)
    except InvalidContent as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _comment(body: KnowledgeTransitionBody) -> str | None:
    return (body.comment or "").strip() or None


def _need_comment(body: KnowledgeTransitionBody, what: str) -> None:
    if _comment(body) is None:
        raise HTTPException(status_code=422, detail=f"A comment is required to {what}")


def _audit_transition(
    request: Request, action: str, before: dict[str, Any], after: dict[str, Any]
) -> None:
    audit(
        request,
        action,
        target_kind="knowledge_item",
        target_id=after["id"],
        details={
            "kind": after["kind"],
            "from_status": before["status"],
            "to_status": after["status"],
            "from_scope": before["scope"],
            "to_scope": after["scope"],
        },
    )


def _act(
    request: Request,
    item_id: str,
    action: str,
    body: KnowledgeTransitionBody | None,
    *,
    audit_action: str,
) -> dict[str, Any]:
    body = body or KnowledgeTransitionBody()
    actor = _caller(request)
    before = _visible_item(actor, item_id)
    try:
        result = knowledge_dal.transition(
            item_id,
            action,
            actor,
            comment=_comment(body),
            expected_version=body.expected_version,
        )
    except knowledge_dal.KnowledgeError as exc:
        _raise_for(exc)
    if result["applied"]:
        _audit_transition(request, audit_action, before, result["item"])
    return _response(actor, item_id)


# -- routes ----------------------------------------------------------------


@router.get("/knowledge-items/status", response_model=KnowledgeStatus)
def knowledge_status() -> dict[str, bool]:
    """Whether knowledge items are switched on. Never 404s: the page asks this."""
    return {"enabled": is_knowledge_items_enabled()}


@gated.get("/knowledge-items", response_model=KnowledgeItemListResponse)
def list_knowledge_items(
    request: Request,
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    database: str | None = Query(default=None, description="Database name or id."),
    mine: bool = Query(default=False, description="Only items you own."),
    reviewable: bool = Query(
        default=False, description="Only items you may approve right now."
    ),
    limit: int = Query(default=DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    cursor: str | None = Query(
        default=None, description="`next_cursor` of the page before."
    ),
) -> dict[str, Any]:
    """List the knowledge items the caller may see, newest first.

    The caller's own personal items and shared items. Another person's personal
    draft never appears, administrators included, unless the audit setting is
    on; a reviewer also sees a personal item once its owner submitted it.
    Keyset pagination: pass `next_cursor` back as `cursor`.
    """
    actor = _caller(request)
    database_id: str | None = None
    if database is not None:
        row = terms_dal.resolve_database(database)
        if row is None:
            return {"data": [], "next_cursor": None}
        database_id = row["id"]
    after = _decode_cursor(cursor) if cursor else None

    directory = _Directory()
    page: list[dict[str, Any]] = []
    more = False
    exhausted = False
    while not exhausted and not more:
        chunk = knowledge_dal.list_items(
            actor,
            database_id=database_id,
            status=status,
            kind=kind,
            limit=_SCAN_CHUNK,
            after=after,
        )
        exhausted = len(chunk) < _SCAN_CHUNK
        for item in chunk:
            if mine and item["owner_id"] != actor.actor_id:
                after = (item["created"], item["id"])
                continue
            out = _item_out(actor, item, directory)
            if reviewable and "approve" not in out["allowed_actions"]:
                after = (item["created"], item["id"])
                continue
            if len(page) == limit:
                more = True
                break
            page.append(out)
            after = (item["created"], item["id"])
    next_cursor = _encode_cursor(*after) if more and after else None
    return {"data": page, "next_cursor": next_cursor}


@gated.get("/knowledge-items/{item_id}", response_model=KnowledgeItemResponse)
def get_knowledge_item(
    request: Request, item_id: str = Path(min_length=1)
) -> dict[str, Any]:
    """One knowledge item with its event history (404 if the caller may not see it)."""
    actor = _caller(request)
    _visible_item(actor, item_id)
    return _response(actor, item_id)


@gated.post("/knowledge-items", status_code=201, response_model=KnowledgeItemResponse)
def create_knowledge_item(
    request: Request, body: KnowledgeItemCreate
) -> dict[str, Any]:
    """Create a personal draft (`term` or `synonym`) owned by the caller."""
    actor = _caller(request)
    database = _resolve_database(body.database)
    content = _validated(
        body.kind,
        {**body.content, "database": database["name"] if database else None},
    )
    try:
        created = knowledge_dal.create_draft(
            actor,
            kind=body.kind,
            owner_id=actor.actor_id,
            content=content,
            database_id=database["id"] if database else None,
            provenance={
                "source": "manual",
                "activity": "manual",
                "evidence": [
                    {"type": "note", "ref": "manual", "excerpt": "typed by hand"}
                ],
            },
        )
    except knowledge_dal.KnowledgeError as exc:
        _raise_for(exc)
    item = created["item"]
    audit(
        request,
        "knowledge.propose",
        target_kind="knowledge_item",
        target_id=item["id"],
        details={"kind": item["kind"], "to_status": item["status"], "source": "manual"},
    )
    return _response(actor, item["id"])


@gated.patch("/knowledge-items/{item_id}", response_model=KnowledgeItemResponse)
def edit_knowledge_item(
    request: Request,
    body: KnowledgeItemEdit,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Edit a draft's content. Owner only, draft only, and never over a newer edit.

    Send the `current_version` you loaded as `expected_version`; if the item
    changed meanwhile the answer is 409 and nothing is written. The database an
    item is about cannot change.
    """
    actor = _caller(request)
    item = _visible_item(actor, item_id)
    content = _validated(
        item["kind"], {**body.content, "database": item["content"].get("database")}
    )
    try:
        knowledge_dal.transition(
            item_id,
            "edit",
            actor,
            content=content,
            expected_version=body.expected_version,
        )
    except knowledge_dal.KnowledgeError as exc:
        _raise_for(exc)
    return _response(actor, item_id)


@gated.post("/knowledge-items/{item_id}/submit", response_model=KnowledgeItemResponse)
def submit_knowledge_item(
    request: Request,
    body: KnowledgeTransitionBody | None = None,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Send a draft for review. Owner (or someone who may certify) only."""
    return _act(request, item_id, "submit", body, audit_action="knowledge.submit")


@gated.post("/knowledge-items/{item_id}/approve", response_model=KnowledgeItemResponse)
def approve_knowledge_item(
    request: Request,
    body: KnowledgeTransitionBody | None = None,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Certify an item in review, for everyone.

    Needs the right to certify (an administrator, or the owner of the database
    or Term it is about) and nobody certifies what they proposed. A personal
    item is shared first, as one explicit step recorded in its history, then
    certified; if the caller may not approve, nothing changes.
    """
    body = body or KnowledgeTransitionBody()
    actor = _caller(request)
    item = _visible_item(actor, item_id)
    if item["scope"] == "personal":
        if item["status"] != "in_review":
            raise HTTPException(
                status_code=409,
                detail=f"cannot approve an item that is {item['status']}",
            )
        if "approve" not in knowledge_dal.allowed_actions(actor, item):
            raise HTTPException(
                status_code=403,
                detail=(
                    "only the owner of the database or Term, or an admin, can approve; "
                    "nobody may certify what they proposed"
                ),
            )
        try:
            promoted = knowledge_dal.transition(
                item_id,
                "promote_scope",
                actor,
                expected_version=body.expected_version,
            )
        except knowledge_dal.KnowledgeError as exc:
            _raise_for(exc)
        if promoted["applied"]:
            _audit_transition(
                request, "knowledge.promote_scope", item, promoted["item"]
            )
        item = promoted["item"]
    try:
        result = knowledge_dal.transition(
            item_id,
            "approve",
            actor,
            comment=_comment(body),
            expected_version=body.expected_version,
        )
    except knowledge_dal.KnowledgeError as exc:
        _raise_for(exc)
    if result["applied"]:
        _audit_transition(request, "knowledge.approve", item, result["item"])
    return _response(actor, item_id)


@gated.post("/knowledge-items/{item_id}/reject", response_model=KnowledgeItemResponse)
def reject_knowledge_item(
    request: Request,
    body: KnowledgeTransitionBody,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Reject an item in review. A comment saying why is required."""
    _need_comment(body, "reject")
    return _act(request, item_id, "reject", body, audit_action="knowledge.reject")


@gated.post(
    "/knowledge-items/{item_id}/request-changes", response_model=KnowledgeItemResponse
)
def request_changes_knowledge_item(
    request: Request,
    body: KnowledgeTransitionBody,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Send an item in review back to its owner as a draft. A comment is required."""
    _need_comment(body, "request changes")
    return _act(
        request,
        item_id,
        "request_changes",
        body,
        audit_action="knowledge.request_changes",
    )


@gated.post(
    "/knowledge-items/{item_id}/deprecate", response_model=KnowledgeItemResponse
)
def deprecate_knowledge_item(
    request: Request,
    body: KnowledgeTransitionBody | None = None,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Retire an item. Someone who may certify, or the owner of a personal item."""
    return _act(request, item_id, "deprecate", body, audit_action="knowledge.deprecate")


@gated.post("/knowledge-items/{item_id}/withdraw", response_model=KnowledgeItemResponse)
def withdraw_knowledge_item(
    request: Request,
    body: KnowledgeTransitionBody | None = None,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Withdraw your own personal item (a draft or one in review).

    The same lifecycle step as `deprecate`, recorded as such, but only for the
    person it belongs to.
    """
    actor = _caller(request)
    item = _visible_item(actor, item_id)
    if item["owner_id"] != actor.actor_id:
        raise HTTPException(
            status_code=403, detail="only the owner can withdraw their own item"
        )
    return _act(request, item_id, "deprecate", body, audit_action="knowledge.deprecate")


@gated.post(
    "/knowledge-items/{item_id}/promote-scope", response_model=KnowledgeItemResponse
)
def promote_knowledge_item_scope(
    request: Request,
    body: KnowledgeTransitionBody | None = None,
    item_id: str = Path(min_length=1),
) -> dict[str, Any]:
    """Make a personal item in review visible to everyone, without approving it.

    Only someone who may certify it can; approving does this for you.
    """
    return _act(
        request,
        item_id,
        "promote_scope",
        body,
        audit_action="knowledge.promote_scope",
    )


router.include_router(gated)
