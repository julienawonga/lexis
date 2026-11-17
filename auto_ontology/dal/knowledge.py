# SPDX-License-Identifier: Apache-2.0
"""Persistence for knowledge items: drafts, their lifecycle, their history.

One rule shapes this module: **``status`` and ``scope`` change in exactly one
place, :func:`transition`.** It checks the lifecycle and the permissions of
``dal/knowledge_rules.py``, appends the event, and updates the projection, all
in one transaction under a row lock. Every other function reads, or creates the
first event (:func:`create_draft`).

The event table is the truth and ``knowledge_item`` is derived from it:
:func:`replay_item` folds an item's events back into the row it should have,
and the tests assert that this equals the stored row after any sequence of
transitions.

Nothing here is wired into answer-time retrieval. ``server/knowledge`` exposes it
behind the ``knowledge_items_enabled`` flag.
Certifying does not materialise into ``term`` or ``sql_attribute`` yet:
``target_table`` and ``target_id`` stay null.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from auto_ontology.dal import groups as groups_dal
from auto_ontology.dal import schema as s
from auto_ontology.dal.knowledge_rules import (
    ACTOR_USER,
    ROLE_ADMIN,
    Actor,
    ItemFacts,
    can_certify,
    destination,
    lifecycle_refusal,
    propose_refusal,
    refusal_reason,
)
from auto_ontology.dal.session import store, write_transaction
from auto_ontology.infra.feature_flags import is_knowledge_admin_audit_enabled

#: The columns the event log alone determines. ``target_*`` are set by
#: materialisation, which is not built, so replay leaves them out.
PROJECTED_FIELDS = (
    "id",
    "kind",
    "status",
    "scope",
    "owner_id",
    "database_id",
    "content",
    "content_hash",
    "provenance",
    "current_version",
    "created_by",
    "created",
    "modified",
)


class KnowledgeError(ValueError):
    """Base of every refusal this module raises."""


class ItemNotFound(KnowledgeError):
    """No knowledge item has this id."""

    def __init__(self, item_id: str) -> None:
        self.item_id = item_id
        super().__init__(f"Knowledge item {item_id!r} does not exist")


class InvalidTransition(KnowledgeError):
    """The lifecycle does not allow this action from the item's state."""


class PermissionDenied(KnowledgeError):
    """The actor is not allowed to take this action."""


class VersionConflict(KnowledgeError):
    """The item changed since the caller loaded it (optimistic lock)."""

    def __init__(self, item_id: str, expected: int, current: int) -> None:
        self.item_id = item_id
        self.expected = expected
        self.current = current
        super().__init__(
            f"Knowledge item {item_id!r} changed since it was loaded "
            f"(you saw version {expected}, it is now version {current})"
        )


class InvalidDraft(KnowledgeError):
    """The draft is malformed: unknown kind, empty content, no evidence."""


def content_hash(content: dict[str, Any]) -> str:
    """A stable hash of *content*, independent of key order."""
    canonical = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def resolve_actor(user_id: str) -> Actor:
    """The :class:`Actor` for a signed-in account, read from the store.

    Fails closed: an unknown account has no role and no groups, so it can
    certify nothing. Only groups whose own role is ``admin`` count as owners,
    as in ``server/owners.py``.
    """
    account = groups_dal.get_account(user_id)
    role = account["role"] if account else None
    admin_groups = frozenset(
        group["id"]
        for group in groups_dal.groups_for_user(user_id)
        if group["role"] == s.GROUP_ROLE_ADMIN
    )
    return Actor(ACTOR_USER, user_id, role=role, group_ids=admin_groups)


def _certifier_owner_ids(
    database_id: str | None, content: dict[str, Any]
) -> frozenset[str]:
    """Who owns what the item is about: the Term it names, else its database.

    Both, when both are owned: the owner of the database and the owner of the
    Term may each certify. Ownership is modelled by ``owner_id`` on
    ``catalog_database`` and ``term`` (``dal/owners.py``); the design's "domain
    owner" is read as the owner of the database, because a business domain row
    carries no owner of its own.
    """
    owners: set[str] = set()
    term_id = content.get("term_id")
    if isinstance(term_id, str):
        rows = store().query_read(
            select(s.term.c.owner_id).where(s.term.c.id == term_id).limit(1)
        )
        if rows and rows[0]["owner_id"]:
            owners.add(rows[0]["owner_id"])
    if database_id:
        rows = store().query_read(
            select(s.catalog_database.c.owner_id)
            .where(s.catalog_database.c.id == database_id)
            .limit(1)
        )
        if rows and rows[0]["owner_id"]:
            owners.add(rows[0]["owner_id"])
    return frozenset(owners)


def _validate_draft(
    kind: str, content: dict[str, Any], provenance: dict[str, Any]
) -> None:
    if kind not in s.KNOWLEDGE_KINDS:
        raise InvalidDraft(f"unknown kind {kind!r}")
    if not isinstance(content, dict) or not content:
        raise InvalidDraft("a draft needs non-empty content")
    evidence = provenance.get("evidence") if isinstance(provenance, dict) else None
    activity = provenance.get("activity") if isinstance(provenance, dict) else None
    if not activity or not isinstance(activity, str):
        raise InvalidDraft("provenance needs an 'activity'")
    if not isinstance(evidence, list) or not evidence:
        raise InvalidDraft("a draft without evidence is rejected (provenance.evidence)")


def _get_row(item_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    statement = select(s.knowledge_item).where(s.knowledge_item.c.id == item_id)
    if lock:
        statement = statement.with_for_update()
    rows = store().query_read(statement)
    return rows[0] if rows else None


def _facts(row: dict[str, Any]) -> ItemFacts:
    return ItemFacts(
        status=row["status"],
        scope=row["scope"],
        owner_id=row["owner_id"],
        created_by=row["created_by"],
    )


def _insert_event(values: dict[str, Any]) -> dict[str, Any]:
    return store().query_write(
        s.knowledge_event.insert().values(**values).returning(s.knowledge_event)
    )[0]


def _last_event(item_id: str) -> dict[str, Any] | None:
    rows = store().query_read(
        select(s.knowledge_event)
        .where(s.knowledge_event.c.item_id == item_id)
        .order_by(s.knowledge_event.c.seq.desc())
        .limit(1)
    )
    return rows[0] if rows else None


def create_draft(
    actor: Actor,
    *,
    kind: str,
    owner_id: str,
    content: dict[str, Any],
    provenance: dict[str, Any],
    database_id: str | None = None,
    scope: str = "personal",
    item_id: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Create a draft item and its ``propose`` event in one transaction.

    Returns ``{"item", "event", "applied"}``. A draft is born ``personal``
    unless a person who may certify creates a ``shared`` one. *provenance*
    must name the ``activity`` (``clarification_answer``, ``manual``...) and
    carry at least one ``evidence`` entry: an unsupported draft is refused.

    Pass a client-chosen *item_id* to make the call idempotent: a retry with
    the same id and the same content returns the existing item with
    ``applied`` false instead of creating a second one.
    """
    _validate_draft(kind, content, provenance)
    if scope not in s.KNOWLEDGE_SCOPES:
        raise InvalidDraft(f"unknown scope {scope!r}")
    digest = content_hash(content)
    with write_transaction():
        if item_id is not None:
            existing = _get_row(item_id, lock=True)
            if existing is not None:
                if (
                    existing["owner_id"] != owner_id
                    or existing["kind"] != kind
                    or existing["database_id"] != database_id
                    or existing["created_by"] != actor.actor_id
                    or existing["provenance"] != provenance
                    or _first_event_hash(item_id) != digest
                ):
                    raise InvalidDraft(
                        f"item {item_id!r} already exists with different content"
                    )
                return {
                    "item": existing,
                    "event": _first_event(item_id),
                    "applied": False,
                }
        reason = propose_refusal(
            actor, scope, owner_id, _certifier_owner_ids(database_id, content)
        )
        if reason is not None:
            raise PermissionDenied(reason)
        new_id = item_id or str(uuid.uuid4())
        at = _now()
        snapshot = {
            "kind": kind,
            "database_id": database_id,
            "scope": scope,
            "owner_id": owner_id,
            "created_by": actor.actor_id,
            "content": content,
            "provenance": provenance,
        }
        event = _insert_event(
            {
                "item_id": new_id,
                "at": at,
                "action": "propose",
                "actor_type": actor.actor_type,
                "actor_id": actor.actor_id,
                "from_status": None,
                "to_status": "draft",
                "from_scope": None,
                "to_scope": scope,
                "version": 1,
                "comment": comment,
                "activity": provenance["activity"],
                "data": snapshot,
            }
        )
        item = store().query_write(
            s.knowledge_item.insert()
            .values(
                id=new_id,
                kind=kind,
                status="draft",
                scope=scope,
                owner_id=owner_id,
                database_id=database_id,
                content=content,
                content_hash=digest,
                provenance=provenance,
                current_version=1,
                created_by=actor.actor_id,
                created=at,
                modified=at,
            )
            .returning(s.knowledge_item)
        )[0]
    return {"item": item, "event": event, "applied": True}


def _first_event(item_id: str) -> dict[str, Any]:
    return store().query_read(
        select(s.knowledge_event)
        .where(s.knowledge_event.c.item_id == item_id)
        .order_by(s.knowledge_event.c.seq)
        .limit(1)
    )[0]


def _first_event_hash(item_id: str) -> str:
    return content_hash(_first_event(item_id)["data"]["content"])


def transition(
    item_id: str,
    action: str,
    actor: Actor,
    *,
    comment: str | None = None,
    content: dict[str, Any] | None = None,
    request_id: str | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Apply *action* to the item: the one place ``status`` and ``scope`` change.

    Checks the lifecycle, then the actor's permission, then appends the event
    and updates the projection, in one transaction holding a lock on the item
    row, so concurrent calls serialise. Raises :class:`ItemNotFound`,
    :class:`PermissionDenied` or :class:`InvalidTransition`; on any failure
    neither row changes.

    Returns ``{"item", "event", "applied"}``. A retry is safe and returns
    ``applied`` false with the event that already happened: by *request_id*
    when the caller sent one, otherwise when the item's latest event is this
    same action by this same actor and the item is already where the action
    leads. ``edit`` takes the new *content*.

    *expected_version* is an optimistic lock: when given and the item's
    ``current_version`` differs, :class:`VersionConflict` is raised under the
    row lock and nothing changes, so a person's edit is never overwritten by a
    caller who had not seen it. It is checked after the permission and
    lifecycle checks, and not for a retry that already happened.
    """
    with write_transaction():
        row = _get_row(item_id, lock=True)
        if row is None:
            raise ItemNotFound(item_id)
        replay = _retry_of(row, action, actor, content, request_id)
        if replay is not None:
            return {"item": row, "event": replay, "applied": False}

        facts = _facts(row)
        owners = _certifier_owner_ids(row["database_id"], row["content"])
        reason = refusal_reason(actor, action, facts, owners)
        if reason is not None:
            raise PermissionDenied(reason)
        reason = lifecycle_refusal(action, facts)
        if reason is not None:
            raise InvalidTransition(reason)

        if expected_version is not None and expected_version != row["current_version"]:
            raise VersionConflict(item_id, expected_version, row["current_version"])

        to_status, to_scope = destination(action, facts)
        values: dict[str, Any] = {
            "status": to_status,
            "scope": to_scope,
            "modified": _now(),
        }
        data: dict[str, Any] = {}
        version = row["current_version"]
        if action == "edit":
            if not isinstance(content, dict) or not content:
                raise InvalidDraft("an edit needs non-empty content")
            version += 1
            values.update(
                content=content,
                content_hash=content_hash(content),
                current_version=version,
            )
            data = {"content": content}
        event = _insert_event(
            {
                "item_id": item_id,
                "at": values["modified"],
                "action": action,
                "actor_type": actor.actor_type,
                "actor_id": actor.actor_id,
                "from_status": row["status"],
                "to_status": to_status,
                "from_scope": row["scope"],
                "to_scope": to_scope,
                "version": version,
                "comment": comment,
                "request_id": request_id,
                "data": data,
            }
        )
        item = store().query_write(
            update(s.knowledge_item)
            .where(s.knowledge_item.c.id == item_id)
            .values(**values)
            .returning(s.knowledge_item)
        )[0]
    return {"item": item, "event": event, "applied": True}


def _retry_of(
    row: dict[str, Any],
    action: str,
    actor: Actor,
    content: dict[str, Any] | None,
    request_id: str | None,
) -> dict[str, Any] | None:
    """The event this call repeats, or ``None`` when it is a new request."""
    if request_id is not None:
        rows = store().query_read(
            select(s.knowledge_event).where(
                s.knowledge_event.c.item_id == row["id"],
                s.knowledge_event.c.request_id == request_id,
            )
        )
        if rows:
            earlier = rows[0]
            if earlier["action"] != action or earlier["actor_id"] != actor.actor_id:
                raise InvalidTransition(
                    f"request {request_id!r} was already used for another action"
                )
            return earlier
        return None
    last = _last_event(row["id"])
    if (
        last is not None
        and last["action"] == action
        and last["actor_id"] == actor.actor_id
        and last["actor_type"] == actor.actor_type
        and last["to_status"] == row["status"]
        and last["to_scope"] == row["scope"]
        and (action != "edit" or content_hash(content or {}) == row["content_hash"])
    ):
        return last
    return None


def get_item(item_id: str) -> dict[str, Any] | None:
    """The stored projection of one item, or ``None``. No visibility check."""
    return _get_row(item_id)


def list_events(item_id: str) -> list[dict[str, Any]]:
    """The item's events, oldest first."""
    return store().query_read(
        select(s.knowledge_event)
        .where(s.knowledge_event.c.item_id == item_id)
        .order_by(s.knowledge_event.c.seq)
    )


def can_view(viewer: Actor, item: dict[str, Any], *, audit: bool = False) -> bool:
    """Whether *viewer* may read *item*.

    Shared items are visible to everyone with access. A personal item is
    visible to its owner only. Two narrow exceptions, both deliberate: an
    admin when the ``knowledge_admin_audit_enabled`` setting is on (*audit*),
    and anyone who may certify it once the owner has *submitted* it for review,
    because a reviewer who cannot see the queue cannot review (a personal item
    in ``in_review`` is the owner's explicit disclosure; a personal ``draft``
    stays private).
    """
    if item["scope"] == "shared":
        return True
    if viewer.actor_type == ACTOR_USER and viewer.actor_id == item["owner_id"]:
        return True
    if audit and viewer.actor_type == ACTOR_USER and viewer.role == ROLE_ADMIN:
        return True
    if item["status"] == "in_review":
        return can_certify(
            viewer, _certifier_owner_ids(item["database_id"], item["content"])
        )
    return False


def list_items(
    viewer: Actor,
    *,
    database_id: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    scope: str | None = None,
    limit: int = 200,
    after: tuple[datetime, str] | None = None,
) -> list[dict[str, Any]]:
    """The items *viewer* may see, newest first, filtered by the arguments.

    The scope filter lives here, not in the caller: see :func:`can_view`. The
    audit setting is read once per call and fails closed.

    *after* is a keyset cursor, the ``(created, id)`` of the last item of the
    previous page: the page starts after it, so it never shifts when items
    arrive.
    """
    statement = select(s.knowledge_item).order_by(
        s.knowledge_item.c.created.desc(), s.knowledge_item.c.id
    )
    for column, value in (
        (s.knowledge_item.c.database_id, database_id),
        (s.knowledge_item.c.status, status),
        (s.knowledge_item.c.kind, kind),
        (s.knowledge_item.c.scope, scope),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if after is not None:
        created, last_id = after
        statement = statement.where(
            or_(
                s.knowledge_item.c.created < created,
                and_(
                    s.knowledge_item.c.created == created,
                    s.knowledge_item.c.id > last_id,
                ),
            )
        )
    audit = (
        viewer.actor_type == ACTOR_USER
        and viewer.role == ROLE_ADMIN
        and is_knowledge_admin_audit_enabled()
    )
    visible: list[dict[str, Any]] = []
    for row in store().query_read(statement):
        if can_view(viewer, row, audit=audit):
            visible.append(row)
            if len(visible) >= limit:
                break
    return visible


#: The actions a person can take from the review page, in display order.
HUMAN_ACTIONS = (
    "edit",
    "submit",
    "approve",
    "reject",
    "request_changes",
    "deprecate",
    "promote_scope",
)


def allowed_actions(actor: Actor, item: dict[str, Any]) -> list[str]:
    """The :data:`HUMAN_ACTIONS` *actor* may take on *item* right now.

    Asks the same two pure questions :func:`transition` asks (permission, then
    lifecycle), so the page never offers a button the store would refuse. One
    exception is deliberate: ``approve`` on a personal item in review is
    offered, because approving it shares it first (the route promotes the
    scope, then approves).
    """
    facts = _facts(item)
    owners = _certifier_owner_ids(item["database_id"], item["content"])
    allowed: list[str] = []
    for action in HUMAN_ACTIONS:
        if refusal_reason(actor, action, facts, owners) is not None:
            continue
        lifecycle = lifecycle_refusal(action, facts)
        if (
            lifecycle is not None
            and action == "approve"
            and facts.status == "in_review"
            and facts.scope == "personal"
        ):
            lifecycle = None
        if lifecycle is None:
            allowed.append(action)
    return allowed


def replay_events(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fold events (oldest first) into the projection they imply, with no I/O.

    Returns the :data:`PROJECTED_FIELDS` of the item, or ``None`` for no
    events. Raises :class:`KnowledgeError` when the log is not a valid history
    (it does not start with ``propose``).
    """
    if not events:
        return None
    first = events[0]
    if first["action"] != "propose":
        raise KnowledgeError(
            f"the history of {first['item_id']!r} does not start with a proposal"
        )
    snapshot = first["data"]
    state: dict[str, Any] = {
        "id": first["item_id"],
        "kind": snapshot["kind"],
        "status": first["to_status"],
        "scope": first["to_scope"],
        "owner_id": snapshot["owner_id"],
        "database_id": snapshot["database_id"],
        "content": snapshot["content"],
        "content_hash": content_hash(snapshot["content"]),
        "provenance": snapshot["provenance"],
        "current_version": first["version"],
        "created_by": snapshot["created_by"],
        "created": first["at"],
        "modified": first["at"],
    }
    for event in events[1:]:
        state["status"] = event["to_status"]
        state["scope"] = event["to_scope"]
        state["current_version"] = event["version"]
        state["modified"] = event["at"]
        if event["action"] == "edit":
            state["content"] = event["data"]["content"]
            state["content_hash"] = content_hash(state["content"])
    return state


def replay_item(item_id: str) -> dict[str, Any] | None:
    """The projection of one item rebuilt from its events alone."""
    return replay_events(list_events(item_id))


def rebuild_projection(item_id: str | None = None) -> int:
    """Rewrite ``knowledge_item`` from the event log; return the rows written.

    For one item, or for every item that has events. Creates a row that is
    missing and overwrites one that drifted; ``target_table`` and
    ``target_id`` are left as they are.
    """
    with write_transaction():
        if item_id is not None:
            ids = [item_id]
        else:
            ids = [
                row["item_id"]
                for row in store().query_read(
                    select(s.knowledge_event.c.item_id).distinct()
                )
            ]
        written = 0
        for current in ids:
            state = replay_item(current)
            if state is None:
                continue
            insert = pg_insert(s.knowledge_item).values(**state)
            store().query_write(
                insert.on_conflict_do_update(
                    index_elements=[s.knowledge_item.c.id],
                    set_={k: v for k, v in state.items() if k != "id"},
                )
            )
            written += 1
    return written
