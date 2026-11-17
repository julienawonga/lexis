# SPDX-License-Identifier: Apache-2.0
"""The lifecycle and permission rules of knowledge items, with no database.

The permission test is one table: every actor against every action, in both
scopes, with the expected answer written out. A rule changed by accident shows
up as a cell that flipped, not as a vague failure somewhere else.
"""

from __future__ import annotations

import pytest

from auto_ontology.dal.knowledge_rules import (
    LIFECYCLE,
    Actor,
    ItemFacts,
    can_certify,
    destination,
    lifecycle_refusal,
    propose_refusal,
    refusal_reason,
)
from auto_ontology.dal.schema import KNOWLEDGE_ACTIONS, KNOWLEDGE_STATUSES

OWNERS = frozenset({"u-dom", "g1"})

ACTORS = {
    "owner": Actor("user", "u-owner", role="viewer"),
    "domain_owner": Actor("user", "u-dom", role="viewer"),
    "group_member": Actor(
        "user", "u-member", role="viewer", group_ids=frozenset({"g1"})
    ),
    "admin": Actor("user", "u-admin", role="admin"),
    "other": Actor("user", "u-other", role="viewer"),
    "unknown_role": Actor("user", "u-ghost", role=None),
    "agent": Actor("agent", "agent-1", role="admin"),
    "job": Actor("job", "consolidation", role="admin"),
}
CERTIFIERS = {"domain_owner", "group_member", "admin"}


def _item(scope: str, status: str = "draft", created_by: str = "u-owner") -> ItemFacts:
    return ItemFacts(
        status=status, scope=scope, owner_id="u-owner", created_by=created_by
    )


#: action -> scope -> the actors allowed to take it. Everyone else is refused.
ALLOWED: dict[str, dict[str, set[str]]] = {
    "edit": {
        "personal": {"owner", "agent"},
        "shared": CERTIFIERS,
    },
    "submit": {
        "personal": {"owner"} | CERTIFIERS,
        "shared": {"owner"} | CERTIFIERS,
    },
    "approve": {"personal": CERTIFIERS, "shared": CERTIFIERS},
    "reject": {"personal": CERTIFIERS, "shared": CERTIFIERS},
    "request_changes": {"personal": CERTIFIERS, "shared": CERTIFIERS},
    "revalidate_ok": {"personal": CERTIFIERS, "shared": CERTIFIERS},
    "deprecate": {
        "personal": {"owner"} | CERTIFIERS,
        "shared": CERTIFIERS,
    },
    "promote_scope": {"personal": CERTIFIERS, "shared": CERTIFIERS},
    "mark_conflict": {"personal": {"job"}, "shared": {"job"}},
    "mark_revalidation": {"personal": {"job"}, "shared": {"job"}},
}


def test_every_action_has_a_row_in_the_permission_table() -> None:
    assert set(ALLOWED) == set(KNOWLEDGE_ACTIONS) - {"propose"}
    assert set(ALLOWED) == set(LIFECYCLE)


@pytest.mark.parametrize("action", sorted(ALLOWED))
@pytest.mark.parametrize("scope", ["personal", "shared"])
@pytest.mark.parametrize("actor_name", sorted(ACTORS))
def test_permission_table(action: str, scope: str, actor_name: str) -> None:
    reason = refusal_reason(ACTORS[actor_name], action, _item(scope), OWNERS)
    expected = actor_name in ALLOWED[action][scope]
    assert (reason is None) is expected, reason


@pytest.mark.parametrize("actor_name", sorted(ACTORS))
def test_nobody_but_a_human_certifier_can_certify(actor_name: str) -> None:
    allowed = can_certify(ACTORS[actor_name], OWNERS)
    assert allowed is (actor_name in CERTIFIERS)


def test_an_unowned_row_can_be_certified_only_by_an_admin() -> None:
    nobody: frozenset[str] = frozenset()
    assert can_certify(ACTORS["admin"], nobody)
    assert not can_certify(ACTORS["domain_owner"], nobody)
    assert not can_certify(ACTORS["owner"], nobody)


def test_an_admin_role_never_lets_an_agent_or_a_job_certify() -> None:
    assert ACTORS["agent"].role == "admin"
    assert not can_certify(ACTORS["agent"], OWNERS)
    assert not can_certify(ACTORS["job"], frozenset())


@pytest.mark.parametrize("proposer", ["domain_owner", "admin"])
def test_nobody_certifies_what_they_proposed(proposer: str) -> None:
    actor = ACTORS[proposer]
    mine = ItemFacts(
        "in_review", "shared", owner_id=actor.actor_id, created_by=actor.actor_id
    )
    assert refusal_reason(actor, "approve", mine, OWNERS) is not None
    # The same actor may certify an item somebody else proposed.
    theirs = ItemFacts("in_review", "shared", owner_id="u-owner", created_by="u-owner")
    assert refusal_reason(actor, "approve", theirs, OWNERS) is None


def test_an_agent_drafting_for_an_owner_does_not_block_the_reviewer() -> None:
    item = ItemFacts("in_review", "shared", owner_id="u-owner", created_by="agent-1")
    assert refusal_reason(ACTORS["domain_owner"], "approve", item, OWNERS) is None


def test_the_creator_cannot_approve_even_when_someone_else_owns_the_item() -> None:
    item = ItemFacts("in_review", "shared", owner_id="u-owner", created_by="u-dom")
    assert refusal_reason(ACTORS["domain_owner"], "approve", item, OWNERS) is not None
    assert refusal_reason(ACTORS["admin"], "approve", item, OWNERS) is None


# --- lifecycle -------------------------------------------------------------

#: action -> {from status: to status}. Anything not listed must be refused.
EXPECTED_MOVES = {
    "edit": {"draft": "draft"},
    "submit": {"draft": "in_review"},
    "approve": {"in_review": "certified"},
    "reject": {"in_review": "rejected"},
    "request_changes": {"in_review": "draft"},
    "deprecate": {
        "draft": "deprecated",
        "in_review": "deprecated",
        "certified": "deprecated",
        "needs_revalidation": "deprecated",
        "conflicted": "deprecated",
        "rejected": "deprecated",
    },
    "mark_conflict": {"certified": "conflicted"},
    "mark_revalidation": {"certified": "needs_revalidation"},
    "revalidate_ok": {"needs_revalidation": "certified", "conflicted": "certified"},
    "promote_scope": {"in_review": "in_review"},
}


@pytest.mark.parametrize("action", sorted(EXPECTED_MOVES))
@pytest.mark.parametrize("status", KNOWLEDGE_STATUSES)
def test_lifecycle_table(action: str, status: str) -> None:
    # The scope that makes the move legal: a draft stage is personal, a
    # vetted stage is shared.
    scope = "personal" if action in ("promote_scope", "submit", "edit") else "shared"
    item = _item(scope, status)
    refusal = lifecycle_refusal(action, item)
    target = EXPECTED_MOVES[action].get(status)
    if target is None:
        assert refusal is not None
        return
    assert refusal is None, refusal
    new_status, _ = destination(action, item)
    assert new_status == target


def test_a_personal_item_cannot_be_certified_or_revalidated() -> None:
    assert lifecycle_refusal("approve", _item("personal", "in_review")) is not None
    assert (
        lifecycle_refusal("revalidate_ok", _item("personal", "needs_revalidation"))
        is not None
    )


def test_promotion_widens_the_scope_and_keeps_the_status() -> None:
    item = _item("personal", "in_review")
    assert destination("promote_scope", item) == ("in_review", "shared")
    assert lifecycle_refusal("promote_scope", _item("shared", "in_review")) is not None


def test_a_draft_cannot_be_promoted_without_being_submitted_first() -> None:
    assert lifecycle_refusal("promote_scope", _item("personal", "draft")) is not None


def test_unknown_actions_are_refused_by_both_checks() -> None:
    item = _item("personal")
    assert lifecycle_refusal("auto_approve", item) is not None
    assert refusal_reason(ACTORS["admin"], "auto_approve", item, OWNERS) is not None


# --- creating ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("actor_name", "scope", "owner", "allowed"),
    [
        ("owner", "personal", "u-owner", True),
        ("owner", "personal", "u-other", False),
        ("agent", "personal", "u-owner", True),
        ("job", "personal", "u-owner", False),
        ("owner", "shared", "u-owner", False),
        ("domain_owner", "shared", "u-dom", True),
        ("admin", "shared", "u-admin", True),
        ("admin", "shared", "u-owner", False),
        ("agent", "shared", "u-owner", False),
        ("other", "shared", "u-other", False),
    ],
)
def test_who_may_create_a_draft(
    actor_name: str, scope: str, owner: str, allowed: bool
) -> None:
    reason = propose_refusal(ACTORS[actor_name], scope, owner, OWNERS)
    assert (reason is None) is allowed, reason
