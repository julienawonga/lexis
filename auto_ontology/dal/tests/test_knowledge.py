# SPDX-License-Identifier: Apache-2.0
"""Postgres integration tests for knowledge items.

Each rule that gets a test fails for a different reason:

* **the lifecycle** -- every transition the design allows, and every one it
  refuses, leaves the item and its history exactly as they were;
* **one transaction** -- a failure while writing either row rolls back both;
* **idempotent retry** -- the same request twice appends one event;
* **the scope filter** -- a personal item is private to its owner, admins
  included, unless the audit setting is on;
* **replay** -- folding the events alone gives back the stored projection,
  after a seeded random run of transitions.

They need the real schema (``alembic upgrade head``) and skip without it.
"""

import os
import random
import uuid
from typing import Any

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import delete, select  # noqa: E402

from auto_ontology.dal import knowledge  # noqa: E402
from auto_ontology.dal import schema as s  # noqa: E402
from auto_ontology.dal.knowledge_rules import LIFECYCLE, Actor  # noqa: E402
from auto_ontology.dal.session import store  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema() -> None:
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read(select(s.knowledge_item.c.id).limit(1))
        store().query_read(select(s.knowledge_event.c.seq).limit(1))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"knowledge schema unavailable (alembic upgrade head): {exc}")


OWNER = Actor("user", "u-owner", role="viewer")
DOMAIN_OWNER = Actor("user", "u-dom", role="viewer")
ADMIN = Actor("user", "u-admin", role="admin")
OTHER = Actor("user", "u-other", role="viewer")
AGENT = Actor("agent", "agent-1", role="admin")
JOB = Actor("job", "consolidation")
ACTORS = [OWNER, DOMAIN_OWNER, ADMIN, OTHER, AGENT, JOB]

PROVENANCE = {
    "activity": "manual",
    "evidence": [{"type": "note", "ref": "test", "excerpt": "typed by hand"}],
}


@pytest.fixture
def world():
    """A database owned by ``u-dom``, and the ids to clean up afterwards."""
    token = uuid.uuid4().hex
    database_id = store().query_write(
        s.catalog_database.insert()
        .values(name=f"knowledge-{token}", owner_id=DOMAIN_OWNER.actor_id)
        .returning(s.catalog_database.c.id)
    )[0]["id"]
    created: list[str] = []
    yield {"database_id": database_id, "created": created, "token": token}
    if created:
        store().query_write(
            delete(s.knowledge_event).where(s.knowledge_event.c.item_id.in_(created))
        )
        store().query_write(
            delete(s.knowledge_item).where(s.knowledge_item.c.id.in_(created))
        )
    store().query_write(
        delete(s.catalog_database).where(s.catalog_database.c.id == database_id)
    )


def _draft(world: dict[str, Any], actor: Actor = OWNER, **overrides: Any) -> dict:
    args: dict[str, Any] = {
        "kind": "term",
        "owner_id": OWNER.actor_id,
        "content": {"name": "VIP", "definition": f"spends a lot {uuid.uuid4().hex}"},
        "provenance": PROVENANCE,
        "database_id": world["database_id"],
    }
    args.update(overrides)
    result = knowledge.create_draft(actor, **args)
    world["created"].append(result["item"]["id"])
    return result


def _in_state(world: dict[str, Any], state: str) -> str:
    """A fresh item walked to *state* through legitimate transitions."""
    item_id = _draft(world)["item"]["id"]
    path = {
        "draft": [],
        "in_review": [("submit", OWNER)],
        "shared_review": [("submit", OWNER), ("promote_scope", DOMAIN_OWNER)],
        "certified": [
            ("submit", OWNER),
            ("promote_scope", DOMAIN_OWNER),
            ("approve", ADMIN),
        ],
        "needs_revalidation": [
            ("submit", OWNER),
            ("promote_scope", DOMAIN_OWNER),
            ("approve", ADMIN),
            ("mark_revalidation", JOB),
        ],
        "conflicted": [
            ("submit", OWNER),
            ("promote_scope", DOMAIN_OWNER),
            ("approve", ADMIN),
            ("mark_conflict", JOB),
        ],
        "rejected": [
            ("submit", OWNER),
            ("promote_scope", DOMAIN_OWNER),
            ("reject", ADMIN),
        ],
        "deprecated": [("deprecate", OWNER)],
    }[state]
    for action, actor in path:
        knowledge.transition(item_id, action, actor)
    return item_id


def _event_count(item_id: str) -> int:
    return len(knowledge.list_events(item_id))


def _assert_replay_matches(item_id: str) -> None:
    stored = knowledge.get_item(item_id)
    assert stored is not None
    replayed = knowledge.replay_item(item_id)
    assert replayed is not None
    assert {k: stored[k] for k in knowledge.PROJECTED_FIELDS} == replayed


# --- creating ---------------------------------------------------------------


def test_a_draft_is_personal_and_has_one_proposal_event(world: dict) -> None:
    result = _draft(world)
    item, event = result["item"], result["event"]
    assert result["applied"] is True
    assert (item["status"], item["scope"]) == ("draft", "personal")
    assert item["owner_id"] == "u-owner"
    assert item["target_table"] is None and item["target_id"] is None
    assert event["action"] == "propose"
    assert (event["from_status"], event["to_status"]) == (None, "draft")
    assert event["actor_id"] == "u-owner" and event["actor_type"] == "user"
    assert event["activity"] == "manual"
    _assert_replay_matches(item["id"])


def test_an_agent_can_draft_for_a_person_and_the_event_says_so(world: dict) -> None:
    result = _draft(world, AGENT)
    assert result["item"]["owner_id"] == "u-owner"
    assert result["item"]["created_by"] == "agent-1"
    assert result["event"]["actor_type"] == "agent"
    _assert_replay_matches(result["item"]["id"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "nonsense"},
        {"content": {}},
        {"provenance": {"activity": "manual", "evidence": []}},
        {"provenance": {"evidence": [{"ref": "x"}]}},
        {"provenance": {}},
        {"scope": "team"},
    ],
)
def test_a_malformed_draft_is_refused_and_writes_nothing(
    world: dict, overrides: dict
) -> None:
    before = len(store().query_read(select(s.knowledge_event.c.seq)))
    with pytest.raises(knowledge.InvalidDraft):
        _draft(world, **overrides)
    assert len(store().query_read(select(s.knowledge_event.c.seq))) == before


@pytest.mark.parametrize(
    ("actor", "owner_id", "scope"),
    [
        (OTHER, "u-owner", "personal"),
        (JOB, "u-owner", "personal"),
        (OWNER, "u-owner", "shared"),
        (AGENT, "u-owner", "shared"),
    ],
)
def test_a_draft_nobody_may_create_is_refused(
    world: dict, actor: Actor, owner_id: str, scope: str
) -> None:
    with pytest.raises(knowledge.PermissionDenied):
        _draft(world, actor, owner_id=owner_id, scope=scope)


def test_the_domain_owner_can_create_a_shared_draft(world: dict) -> None:
    result = _draft(world, DOMAIN_OWNER, owner_id="u-dom", scope="shared")
    assert result["item"]["scope"] == "shared"
    assert result["item"]["status"] == "draft"


def test_the_owner_of_the_term_an_item_names_may_certify_it(world: dict) -> None:
    term_id = store().query_write(
        s.term.insert()
        .values(name=f"T-{world['token']}", source="semantic", owner_id="u-termowner")
        .returning(s.term.c.id)
    )[0]["id"]
    try:
        item_id = _draft(world, content={"term_id": term_id, "name": "alt"})["item"][
            "id"
        ]
        knowledge.transition(item_id, "submit", OWNER)
        term_owner = Actor("user", "u-termowner", role="viewer")
        knowledge.transition(item_id, "promote_scope", term_owner)
        approved = knowledge.transition(item_id, "approve", term_owner)
        assert approved["item"]["status"] == "certified"
        # The database owner may certify it too: both own what it is about.
        other_id = _draft(world, content={"term_id": term_id, "name": "alt2"})["item"][
            "id"
        ]
        knowledge.transition(other_id, "submit", OWNER)
        knowledge.transition(other_id, "promote_scope", DOMAIN_OWNER)
        assert (
            knowledge.transition(other_id, "approve", DOMAIN_OWNER)["item"]["status"]
            == "certified"
        )
    finally:
        store().query_write(delete(s.term).where(s.term.c.id == term_id))


# --- the lifecycle ----------------------------------------------------------


def test_the_full_path_to_certified_writes_one_event_per_step(world: dict) -> None:
    item_id = _in_state(world, "certified")
    events = knowledge.list_events(item_id)
    assert [e["action"] for e in events] == [
        "propose",
        "submit",
        "promote_scope",
        "approve",
    ]
    assert [e["to_status"] for e in events] == [
        "draft",
        "in_review",
        "in_review",
        "certified",
    ]
    assert [e["to_scope"] for e in events] == [
        "personal",
        "personal",
        "shared",
        "shared",
    ]
    assert events[-1]["actor_id"] == "u-admin"
    item = knowledge.get_item(item_id)
    assert (item["status"], item["scope"]) == ("certified", "shared")
    _assert_replay_matches(item_id)


@pytest.mark.parametrize(
    ("start", "action", "actor", "status", "scope"),
    [
        ("draft", "submit", OWNER, "in_review", "personal"),
        ("draft", "deprecate", OWNER, "deprecated", "personal"),
        ("in_review", "promote_scope", DOMAIN_OWNER, "in_review", "shared"),
        ("in_review", "request_changes", ADMIN, "draft", "personal"),
        ("in_review", "reject", DOMAIN_OWNER, "rejected", "personal"),
        ("in_review", "deprecate", OWNER, "deprecated", "personal"),
        ("shared_review", "approve", ADMIN, "certified", "shared"),
        ("shared_review", "reject", ADMIN, "rejected", "shared"),
        ("shared_review", "request_changes", DOMAIN_OWNER, "draft", "shared"),
        ("certified", "mark_conflict", JOB, "conflicted", "shared"),
        ("certified", "mark_revalidation", JOB, "needs_revalidation", "shared"),
        ("certified", "deprecate", ADMIN, "deprecated", "shared"),
        ("needs_revalidation", "revalidate_ok", ADMIN, "certified", "shared"),
        ("needs_revalidation", "deprecate", DOMAIN_OWNER, "deprecated", "shared"),
        ("conflicted", "revalidate_ok", ADMIN, "certified", "shared"),
        ("conflicted", "deprecate", ADMIN, "deprecated", "shared"),
        ("rejected", "deprecate", ADMIN, "deprecated", "shared"),
    ],
)
def test_each_allowed_transition(
    world: dict, start: str, action: str, actor: Actor, status: str, scope: str
) -> None:
    item_id = _in_state(world, start)
    before = _event_count(item_id)
    result = knowledge.transition(item_id, action, actor, comment="because")
    assert result["applied"] is True
    assert (result["item"]["status"], result["item"]["scope"]) == (status, scope)
    event = result["event"]
    assert event["action"] == action and event["comment"] == "because"
    assert event["actor_id"] == actor.actor_id
    assert event["from_status"] != status or action in ("promote_scope", "edit")
    assert _event_count(item_id) == before + 1
    _assert_replay_matches(item_id)


def test_an_edit_changes_the_content_and_bumps_the_version(world: dict) -> None:
    item_id = _in_state(world, "draft")
    new_content = {"name": "VIP", "definition": "changed"}
    result = knowledge.transition(item_id, "edit", OWNER, content=new_content)
    assert result["item"]["content"] == new_content
    assert result["item"]["current_version"] == 2
    assert result["item"]["content_hash"] == knowledge.content_hash(new_content)
    assert result["event"]["version"] == 2
    _assert_replay_matches(item_id)
    with pytest.raises(knowledge.InvalidDraft):
        knowledge.transition(item_id, "edit", OWNER, content={})


def _every_refusal() -> list[tuple[str, str, Actor]]:
    """Every (state, action, actor) the rules refuse, over the states used here."""
    states = [
        "draft",
        "in_review",
        "shared_review",
        "certified",
        "needs_revalidation",
        "conflicted",
        "rejected",
        "deprecated",
    ]
    cases = []
    # Sample, not the full product: one wrong actor for each state and action,
    # plus every action from a state the lifecycle does not allow.
    for state in states:
        for action in LIFECYCLE:
            cases.append((state, action, OTHER))
    cases += [(state, "approve", AGENT) for state in states]
    cases += [(state, "approve", OWNER) for state in states]
    return cases


def test_every_refused_transition_changes_nothing(world: dict) -> None:
    built: dict[str, str] = {}
    refused = 0
    for state, action, actor in _every_refusal():
        item_id = built.setdefault(state, _in_state(world, state))
        before = knowledge.get_item(item_id)
        events = _event_count(item_id)
        try:
            knowledge.transition(
                item_id,
                action,
                actor,
                content={"name": "x"} if action == "edit" else None,
            )
        except (knowledge.PermissionDenied, knowledge.InvalidTransition):
            refused += 1
        else:
            pytest.fail(f"{actor.actor_id} could {action} a {state} item")
        assert knowledge.get_item(item_id) == before
        assert _event_count(item_id) == events
    assert refused == len(_every_refusal())


@pytest.mark.parametrize(
    ("start", "action", "actor"),
    [
        ("in_review", "approve", ADMIN),  # personal: promote first
        ("draft", "approve", ADMIN),
        ("draft", "promote_scope", ADMIN),  # must be submitted first
        ("draft", "reject", ADMIN),
        ("certified", "submit", OWNER),
        ("certified", "edit", ADMIN),
        ("deprecated", "deprecate", ADMIN),
        ("rejected", "approve", ADMIN),
        ("conflicted", "approve", ADMIN),
        ("certified", "mark_conflict", ADMIN),  # job only
        ("certified", "revalidate_ok", ADMIN),  # nothing to revalidate
    ],
)
def test_lifecycle_refusals_even_for_someone_allowed_to_act(
    world: dict, start: str, action: str, actor: Actor
) -> None:
    item_id = _in_state(world, start)
    with pytest.raises((knowledge.InvalidTransition, knowledge.PermissionDenied)):
        knowledge.transition(item_id, action, actor)


def test_nobody_certifies_their_own_proposal(world: dict) -> None:
    item_id = _draft(world, DOMAIN_OWNER, owner_id="u-dom", scope="shared")["item"][
        "id"
    ]
    knowledge.transition(item_id, "submit", DOMAIN_OWNER)
    with pytest.raises(knowledge.PermissionDenied, match="proposed"):
        knowledge.transition(item_id, "approve", DOMAIN_OWNER)
    assert knowledge.transition(item_id, "approve", ADMIN)["item"]["status"] == (
        "certified"
    )


def test_an_agent_cannot_certify_even_with_an_admin_role(world: dict) -> None:
    item_id = _in_state(world, "shared_review")
    with pytest.raises(knowledge.PermissionDenied, match="human"):
        knowledge.transition(item_id, "approve", AGENT)


def test_the_store_itself_refuses_certification_by_an_agent(world: dict) -> None:
    """The CHECK is the last line when the service layer is bypassed."""
    item_id = _in_state(world, "shared_review")
    with pytest.raises(Exception, match="certified_by_user"):
        store().query_write(
            s.knowledge_event.insert().values(
                item_id=item_id,
                at=knowledge._now(),
                action="approve",
                actor_type="agent",
                actor_id="agent-1",
                to_status="certified",
                to_scope="shared",
                version=1,
            )
        )
    with pytest.raises(Exception, match="certified_is_shared"):
        store().query_write(
            s.knowledge_item.update()
            .where(s.knowledge_item.c.id == item_id)
            .values(status="certified", scope="personal")
        )


def test_an_unknown_item_is_reported(world: dict) -> None:
    with pytest.raises(knowledge.ItemNotFound):
        knowledge.transition(str(uuid.uuid4()), "submit", OWNER)


# --- one transaction --------------------------------------------------------


def test_a_failure_writing_the_projection_rolls_back_the_event(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id = _in_state(world, "draft")
    before = knowledge.get_item(item_id)
    events = _event_count(item_id)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the projection write failed")

    monkeypatch.setattr(knowledge, "update", boom)
    with pytest.raises(RuntimeError):
        knowledge.transition(item_id, "submit", OWNER)
    monkeypatch.undo()
    assert knowledge.get_item(item_id) == before
    assert _event_count(item_id) == events
    assert knowledge.transition(item_id, "submit", OWNER)["applied"] is True


def test_a_failure_after_the_event_rolls_back_the_draft_too(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id = str(uuid.uuid4())
    real = knowledge._insert_event

    def insert_then_fail(values: dict[str, Any]) -> dict[str, Any]:
        real(values)
        raise RuntimeError("failed after the event was written")

    monkeypatch.setattr(knowledge, "_insert_event", insert_then_fail)
    with pytest.raises(RuntimeError):
        knowledge.create_draft(
            OWNER,
            kind="term",
            owner_id="u-owner",
            content={"name": "x"},
            provenance=PROVENANCE,
            database_id=world["database_id"],
            item_id=item_id,
        )
    monkeypatch.undo()
    assert knowledge.get_item(item_id) is None
    assert knowledge.list_events(item_id) == []


def test_a_failure_after_the_event_rolls_back_the_transition(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id = _in_state(world, "draft")
    before = knowledge.get_item(item_id)
    events = _event_count(item_id)
    real = knowledge._insert_event

    def insert_then_fail(values: dict[str, Any]) -> dict[str, Any]:
        real(values)
        raise RuntimeError("failed after the event was written")

    monkeypatch.setattr(knowledge, "_insert_event", insert_then_fail)
    with pytest.raises(RuntimeError):
        knowledge.transition(item_id, "submit", OWNER)
    monkeypatch.undo()
    assert knowledge.get_item(item_id) == before
    assert _event_count(item_id) == events


# --- idempotent retry -------------------------------------------------------


def test_a_retry_with_the_same_request_id_appends_one_event(world: dict) -> None:
    item_id = _in_state(world, "draft")
    first = knowledge.transition(item_id, "submit", OWNER, request_id="req-1")
    again = knowledge.transition(item_id, "submit", OWNER, request_id="req-1")
    assert first["applied"] is True and again["applied"] is False
    assert again["event"]["id"] == first["event"]["id"]
    assert _event_count(item_id) == 2


def test_a_request_id_cannot_be_reused_for_another_action(world: dict) -> None:
    item_id = _in_state(world, "draft")
    knowledge.transition(item_id, "submit", OWNER, request_id="req-2")
    with pytest.raises(knowledge.InvalidTransition, match="already used"):
        knowledge.transition(item_id, "deprecate", OWNER, request_id="req-2")


def test_a_retry_without_a_key_is_recognised_by_state(world: dict) -> None:
    item_id = _in_state(world, "draft")
    first = knowledge.transition(item_id, "submit", OWNER)
    again = knowledge.transition(item_id, "submit", OWNER)
    assert again["applied"] is False
    assert again["event"]["id"] == first["event"]["id"]
    assert _event_count(item_id) == 2
    # Another actor taking the same action is not a retry: it is refused.
    with pytest.raises(knowledge.InvalidTransition):
        knowledge.transition(item_id, "submit", ADMIN)


def test_a_repeated_edit_is_a_retry_only_when_the_content_is_the_same(
    world: dict,
) -> None:
    item_id = _in_state(world, "draft")
    knowledge.transition(item_id, "edit", OWNER, content={"name": "a"})
    same = knowledge.transition(item_id, "edit", OWNER, content={"name": "a"})
    assert same["applied"] is False
    different = knowledge.transition(item_id, "edit", OWNER, content={"name": "b"})
    assert different["applied"] is True
    assert different["item"]["current_version"] == 3
    _assert_replay_matches(item_id)


def test_creating_with_the_same_item_id_twice_makes_one_draft(world: dict) -> None:
    item_id = str(uuid.uuid4())
    content = {"name": "once"}
    first = _draft(world, item_id=item_id, content=content)
    again = _draft(world, item_id=item_id, content=content)
    assert first["applied"] is True and again["applied"] is False
    assert again["item"]["id"] == first["item"]["id"]
    assert _event_count(item_id) == 1
    with pytest.raises(knowledge.InvalidDraft, match="different content"):
        _draft(world, item_id=item_id, content={"name": "other"})


# --- the scope filter -------------------------------------------------------


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items}


def test_a_personal_draft_is_visible_to_its_owner_only(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: False)
    item_id = _draft(world)["item"]["id"]
    db = world["database_id"]
    assert item_id in _ids(knowledge.list_items(OWNER, database_id=db))
    for viewer in (OTHER, DOMAIN_OWNER, ADMIN, AGENT):
        assert item_id not in _ids(knowledge.list_items(viewer, database_id=db))


def test_the_audit_setting_lets_admins_and_only_admins_see_it(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id = _draft(world)["item"]["id"]
    db = world["database_id"]
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: True)
    assert item_id in _ids(knowledge.list_items(ADMIN, database_id=db))
    for viewer in (OTHER, DOMAIN_OWNER, AGENT):
        assert item_id not in _ids(knowledge.list_items(viewer, database_id=db))


def test_a_viewer_role_does_not_gain_audit_access_from_the_setting(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: True)
    item_id = _draft(world)["item"]["id"]
    assert item_id not in _ids(
        knowledge.list_items(OTHER, database_id=world["database_id"])
    )


def test_a_shared_item_is_visible_to_everyone(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: False)
    item_id = _in_state(world, "certified")
    db = world["database_id"]
    for viewer in (OWNER, OTHER, DOMAIN_OWNER, ADMIN, AGENT):
        assert item_id in _ids(knowledge.list_items(viewer, database_id=db))


def test_a_submitted_personal_item_is_visible_to_those_who_may_certify_it(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: False)
    draft_id = _in_state(world, "draft")
    review_id = _in_state(world, "in_review")
    db = world["database_id"]
    # The domain owner and the admin see what was submitted, not the draft.
    for reviewer in (DOMAIN_OWNER, ADMIN):
        seen = _ids(knowledge.list_items(reviewer, database_id=db))
        assert review_id in seen and draft_id not in seen
    seen = _ids(knowledge.list_items(OTHER, database_id=db))
    assert review_id not in seen and draft_id not in seen


def test_the_filters_narrow_the_listing(world: dict) -> None:
    db = world["database_id"]
    draft_id = _in_state(world, "draft")
    review_id = _in_state(world, "in_review")
    assert _ids(knowledge.list_items(OWNER, database_id=db, status="draft")) == {
        draft_id
    }
    assert _ids(knowledge.list_items(OWNER, database_id=db, status="in_review")) == {
        review_id
    }
    assert knowledge.list_items(OWNER, database_id=db, kind="synonym") == []
    assert (
        len(knowledge.list_items(OWNER, database_id=db, scope="personal", limit=1)) == 1
    )


def test_an_unknown_account_resolves_to_an_actor_that_certifies_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge.groups_dal, "get_account", lambda user_id: None)
    monkeypatch.setattr(knowledge.groups_dal, "groups_for_user", lambda user_id: [])
    actor = knowledge.resolve_actor("ghost")
    assert (actor.actor_type, actor.role, actor.group_ids) == ("user", None, set())


def test_only_admin_groups_count_as_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        knowledge.groups_dal, "get_account", lambda user_id: {"role": "viewer"}
    )
    monkeypatch.setattr(
        knowledge.groups_dal,
        "groups_for_user",
        lambda user_id: [
            {"id": "g-admin", "role": "admin"},
            {"id": "g-view", "role": "viewer"},
        ],
    )
    assert knowledge.resolve_actor("u").group_ids == {"g-admin"}


# --- replay -----------------------------------------------------------------


def test_replay_reproduces_the_projection_after_a_seeded_random_run(
    world: dict,
) -> None:
    rng = random.Random(20261117)
    actions = sorted(LIFECYCLE)
    applied = 0
    final_statuses: set[str] = set()
    for _ in range(60):
        item_id = _draft(world)["item"]["id"]
        for step in range(rng.randint(3, 20)):
            # Mostly actions the lifecycle allows from here, so the run
            # reaches deep states; sometimes any action, to hit refusals.
            status = knowledge.get_item(item_id)["status"]
            legal = [a for a in actions if status in LIFECYCLE[a].from_statuses]
            action = rng.choice(legal if legal and rng.random() < 0.8 else actions)
            actor = rng.choice(ACTORS)
            content = {"name": f"edit-{step}"} if action == "edit" else None
            try:
                result = knowledge.transition(item_id, action, actor, content=content)
            except (knowledge.PermissionDenied, knowledge.InvalidTransition):
                continue
            applied += int(result["applied"])
            _assert_replay_matches(item_id)
        _assert_replay_matches(item_id)
        final_statuses.add(knowledge.get_item(item_id)["status"])
    # The run must exercise real transitions, not only refusals.
    assert applied > 100
    assert len(final_statuses) >= 4, final_statuses


def test_rebuilding_the_projection_repairs_a_drifted_or_missing_row(
    world: dict,
) -> None:
    drifted = _in_state(world, "certified")
    missing = _in_state(world, "in_review")
    store().query_write(
        s.knowledge_item.update()
        .where(s.knowledge_item.c.id == drifted)
        .values(status="deprecated", current_version=9)
    )
    store().query_write(
        delete(s.knowledge_item).where(s.knowledge_item.c.id == missing)
    )
    assert knowledge.rebuild_projection(drifted) == 1
    assert knowledge.rebuild_projection(missing) == 1
    _assert_replay_matches(drifted)
    _assert_replay_matches(missing)
    assert knowledge.get_item(drifted)["status"] == "certified"
    assert knowledge.get_item(missing)["status"] == "in_review"


def test_a_history_that_does_not_start_with_a_proposal_cannot_be_replayed() -> None:
    event = {"item_id": "x", "action": "submit"}
    with pytest.raises(knowledge.KnowledgeError):
        knowledge.replay_events([event])
    assert knowledge.replay_events([]) is None


def test_the_content_hash_ignores_key_order() -> None:
    assert knowledge.content_hash({"a": 1, "b": 2}) == knowledge.content_hash(
        {"b": 2, "a": 1}
    )
    assert knowledge.content_hash({"a": 1}) != knowledge.content_hash({"a": 2})


# --- slice 2: optimistic lock, keyset cursor, allowed actions ----------------


def test_a_stale_expected_version_is_refused_and_nothing_changes(world: dict) -> None:
    item = _draft(world)["item"]
    knowledge.transition(
        item["id"], "edit", OWNER, content={"name": "VIP", "definition": "v2"}
    )
    before = knowledge.get_item(item["id"])
    events = _event_count(item["id"])
    with pytest.raises(knowledge.VersionConflict) as caught:
        knowledge.transition(
            item["id"],
            "edit",
            OWNER,
            content={"name": "VIP", "definition": "overwrites v2"},
            expected_version=1,
        )
    assert caught.value.current == 2
    assert knowledge.get_item(item["id"]) == before
    assert _event_count(item["id"]) == events


def test_the_current_expected_version_lets_the_edit_through(world: dict) -> None:
    item = _draft(world)["item"]
    done = knowledge.transition(
        item["id"],
        "edit",
        OWNER,
        content={"name": "VIP", "definition": "v2"},
        expected_version=1,
    )
    assert done["item"]["current_version"] == 2


def test_a_retry_is_recognised_before_the_version_check(world: dict) -> None:
    item = _draft(world)["item"]
    content = {"name": "VIP", "definition": "v2"}
    knowledge.transition(
        item["id"], "edit", OWNER, content=content, request_id="r-1", expected_version=1
    )
    again = knowledge.transition(
        item["id"], "edit", OWNER, content=content, request_id="r-1", expected_version=1
    )
    assert again["applied"] is False


def test_a_refusal_wins_over_a_version_conflict(world: dict) -> None:
    item = _draft(world)["item"]
    with pytest.raises(knowledge.PermissionDenied):
        knowledge.transition(
            item["id"],
            "edit",
            OTHER,
            content={"name": "x", "definition": "y"},
            expected_version=99,
        )


def test_the_keyset_cursor_walks_the_listing_without_repeats(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: False)
    ids = {_draft(world)["item"]["id"] for _ in range(5)}
    seen: list[str] = []
    after = None
    while True:
        page = knowledge.list_items(
            OWNER, database_id=world["database_id"], limit=2, after=after
        )
        if not page:
            break
        seen.extend(item["id"] for item in page)
        after = (page[-1]["created"], page[-1]["id"])
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == ids


def test_allowed_actions_follow_the_rules(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge, "is_knowledge_admin_audit_enabled", lambda: False)
    item_id = _draft(world)["item"]["id"]
    draft = knowledge.get_item(item_id)
    assert knowledge.allowed_actions(OWNER, draft) == [
        "edit",
        "submit",
        "deprecate",
    ]
    assert knowledge.allowed_actions(OTHER, draft) == []
    knowledge.transition(item_id, "submit", OWNER)
    review = knowledge.get_item(item_id)
    # The owner proposed it: no approve for them, and the admin may share-and-approve.
    assert "approve" not in knowledge.allowed_actions(OWNER, review)
    assert knowledge.allowed_actions(DOMAIN_OWNER, review) == [
        "approve",
        "reject",
        "request_changes",
        "deprecate",
        "promote_scope",
    ]
    assert knowledge.allowed_actions(AGENT, review) == []
