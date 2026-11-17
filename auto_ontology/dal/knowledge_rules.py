# SPDX-License-Identifier: Apache-2.0
"""The lifecycle and the permissions of knowledge items, as pure functions.

Nothing here touches the store. ``dal/knowledge.py`` loads the facts (the item,
who owns the database or the term it is about, who the actor is) and asks this
module two questions: *may this action start from this status?* and *may this
actor do it?* Keeping both free of I/O is what lets the permission table be
tested exhaustively, in microseconds, without a database.

The rules come from ``docs/design/self-improving-ontology.md``:

* 3.2, the lifecycle: the transition table below;
* 7.2 and 10.3, who may certify: decision 1 (certification is human only,
  forever), decision 2 (in shared scope the owner of the database or Term and
  the admins certify), decision 3 (a personal draft is private), decision 5
  (two scopes, ``personal`` and ``shared``).

Two things the design left open, decided here and listed in the pull request:

* ``approve`` needs the item to be **shared already**. Widening the scope is
  its own explicit action (``promote_scope``) taken by someone allowed to
  certify, so a personal draft never becomes visible to everyone as a side
  effect of another action.
* Only a ``draft`` can be edited. Editing a certified item (which the design
  sends back to review as a new version) is not built.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The two roles an account has, as stored on the account.
ROLE_ADMIN = "admin"

#: Who is acting. ``agent`` writes drafts for a person; ``job`` is the future
#: consolidation job. Neither can ever certify.
ACTOR_USER = "user"
ACTOR_AGENT = "agent"
ACTOR_JOB = "job"


@dataclass(frozen=True)
class Actor:
    """The identity behind one action.

    ``group_ids`` are the groups the account belongs to *whose own role lets
    them edit the catalog* (the admin groups): that is the rule an owner group
    already follows in ``server/owners.py``, so a viewer group that owns a
    Term does not gain the right to certify it. :func:`auto_ontology.dal.knowledge.resolve_actor`
    builds it from the store.
    """

    actor_type: str
    actor_id: str
    role: str | None = None
    group_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ItemFacts:
    """What the rules need to know about an item, and nothing more."""

    status: str
    scope: str
    owner_id: str
    created_by: str


@dataclass(frozen=True)
class Transition:
    """Where an action may start from and where it leads.

    ``to_status`` is ``None`` when the action leaves the status alone
    (``edit`` and ``promote_scope``). ``to_scope`` is ``None`` when it leaves
    the scope alone.
    """

    from_statuses: frozenset[str]
    to_status: str | None
    to_scope: str | None = None


#: The transition table of design section 3.2. ``propose`` is not in it: it
#: creates the item rather than moving it.
LIFECYCLE: dict[str, Transition] = {
    "edit": Transition(frozenset({"draft"}), None),
    "submit": Transition(frozenset({"draft"}), "in_review"),
    "approve": Transition(frozenset({"in_review"}), "certified"),
    "reject": Transition(frozenset({"in_review"}), "rejected"),
    "request_changes": Transition(frozenset({"in_review"}), "draft"),
    "deprecate": Transition(
        frozenset(
            {
                "draft",
                "in_review",
                "certified",
                "needs_revalidation",
                "conflicted",
                "rejected",
            }
        ),
        "deprecated",
    ),
    "promote_scope": Transition(frozenset({"in_review"}), None, to_scope="shared"),
    "mark_conflict": Transition(frozenset({"certified"}), "conflicted"),
    "mark_revalidation": Transition(frozenset({"certified"}), "needs_revalidation"),
    "revalidate_ok": Transition(
        frozenset({"needs_revalidation", "conflicted"}), "certified"
    ),
}

#: Actions only the consolidation job may take. A human cannot declare a
#: conflict by hand in this slice; a reviewer resolves one by deprecating or
#: by ``revalidate_ok``.
JOB_ONLY_ACTIONS = frozenset({"mark_conflict", "mark_revalidation"})


def can_certify(actor: Actor, owner_ids: frozenset[str]) -> bool:
    """Whether *actor* may certify items whose database and Term have *owner_ids*.

    A human, and either an admin or an owner of the database or Term the item
    concerns (an owner id names an account, or a group the actor belongs to).
    An agent and a job never can, whatever role they carry: decision 1. An
    empty set means nobody owns the row, so only an admin may.
    """
    if actor.actor_type != ACTOR_USER:
        return False
    if actor.role == ROLE_ADMIN:
        return True
    return actor.actor_id in owner_ids or not owner_ids.isdisjoint(actor.group_ids)


def _is_owner(actor: Actor, item: ItemFacts) -> bool:
    return actor.actor_type == ACTOR_USER and actor.actor_id == item.owner_id


def _acts_for_owner(actor: Actor, item: ItemFacts) -> bool:
    """The owner, or the agent working for the owner of a draft."""
    return _is_owner(actor, item) or actor.actor_type == ACTOR_AGENT


def refusal_reason(
    actor: Actor,
    action: str,
    item: ItemFacts,
    certifier_owner_ids: frozenset[str],
) -> str | None:
    """Why *actor* may not take *action* on *item*, or ``None`` when allowed.

    Does not check the lifecycle (see :func:`lifecycle_refusal`): the two are
    separate questions and the tests ask each on its own.
    """
    certifier = can_certify(actor, certifier_owner_ids)
    if action in JOB_ONLY_ACTIONS:
        if actor.actor_type != ACTOR_JOB:
            return f"only the consolidation job may {action}"
        return None
    if actor.actor_type == ACTOR_JOB:
        return "the consolidation job may not take this action"

    if action == "edit":
        # A draft belongs to the person it was learned for (an agent writes it
        # for them); a shared draft is edited by those who may certify it.
        if item.scope == "personal":
            if _acts_for_owner(actor, item):
                return None
            return "only the owner can edit a personal draft"
        if certifier:
            return None
        return "only someone who may certify can edit a shared draft"

    if action == "submit":
        if actor.actor_type != ACTOR_USER:
            return "an agent cannot submit: a person decides to ask for review"
        if _is_owner(actor, item) or certifier:
            return None
        return "only the owner, or someone who may certify, can submit a draft"

    if action == "deprecate":
        # An owner withdraws their own personal item; everything else is a
        # reviewer's call.
        if certifier:
            return None
        if item.scope == "personal" and _is_owner(actor, item):
            return None
        return "only someone who may certify can deprecate this"

    if action in ("approve", "reject", "request_changes", "revalidate_ok"):
        if actor.actor_type != ACTOR_USER:
            return "certification is human only: an agent cannot do this"
        if not certifier:
            return "only the owner of the database or Term, or an admin, can do this"
        if action == "approve" and actor.actor_id in (item.owner_id, item.created_by):
            return "nobody may certify what they proposed"
        return None

    if action == "promote_scope":
        # Widening a personal item to everyone is a certifier's explicit act,
        # never the owner's alone and never an agent's.
        if actor.actor_type != ACTOR_USER:
            return "an agent cannot widen the scope"
        if not certifier:
            return "only someone who may certify can promote a draft to shared"
        return None

    return f"unknown action {action!r}"


def lifecycle_refusal(action: str, item: ItemFacts) -> str | None:
    """Why *action* cannot start from the item's state, or ``None`` when it can."""
    transition = LIFECYCLE.get(action)
    if transition is None:
        return f"unknown action {action!r}"
    if item.status not in transition.from_statuses:
        return f"cannot {action} an item that is {item.status}"
    if action == "promote_scope" and item.scope != "personal":
        return "the item is already shared"
    if action == "approve" and item.scope != "shared":
        return "a personal item cannot be certified: promote it to shared first"
    if action == "revalidate_ok" and item.scope != "shared":
        return "only a shared item can be revalidated"
    return None


def destination(action: str, item: ItemFacts) -> tuple[str, str]:
    """The ``(status, scope)`` the item has after *action*. Assumes it is allowed."""
    transition = LIFECYCLE[action]
    return (
        transition.to_status or item.status,
        transition.to_scope or item.scope,
    )


def propose_refusal(
    actor: Actor,
    scope: str,
    owner_id: str,
    certifier_owner_ids: frozenset[str],
) -> str | None:
    """Why *actor* may not create a draft in *scope* for *owner_id*, or ``None``.

    A draft is born personal. A person creates their own; an agent creates one
    for the person it works for. A shared draft is created only by someone who
    may certify, and never by an agent (the design's "only a human moves it
    outward").
    """
    if actor.actor_type == ACTOR_JOB:
        return "the consolidation job may not propose in this slice"
    if scope == "personal":
        if actor.actor_type == ACTOR_AGENT:
            return None
        if actor.actor_id == owner_id:
            return None
        return "a person can only create a personal draft for themselves"
    if actor.actor_type != ACTOR_USER:
        return "an agent cannot create a shared draft"
    if actor.actor_id != owner_id:
        return "a shared draft is owned by the person who creates it"
    if not can_certify(actor, certifier_owner_ids):
        return "only someone who may certify can create a shared draft"
    return None
