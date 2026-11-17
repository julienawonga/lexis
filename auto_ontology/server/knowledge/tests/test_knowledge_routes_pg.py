# SPDX-License-Identifier: Apache-2.0
"""The knowledge-item routes and the capture, against a real PostgreSQL.

Only the flag, the account lookup and the audit-setting are replaced; the DAL,
the permission rules, the lock and the audit table are the real ones. They need
the schema (``alembic upgrade head``) and skip without it.

* **permission matrix** -- owner, another user, an admin with and without the
  audit setting, the owner of the database, an agent;
* **a person's edit is never overwritten** -- a stale ``expected_version`` is
  409 and the stored content is the other person's;
* **capture** -- once per (conversation, clarification), the audit rows, and a
  failure that touches nothing.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("sqlalchemy")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from auto_ontology.dal import groups as groups_dal  # noqa: E402
from auto_ontology.dal import knowledge as knowledge_dal  # noqa: E402
from auto_ontology.dal import schema as s  # noqa: E402
from auto_ontology.dal.knowledge_rules import Actor  # noqa: E402
from auto_ontology.dal.session import store  # noqa: E402
from auto_ontology.server import audit as audit_module  # noqa: E402
from auto_ontology.server.knowledge import capture  # noqa: E402
from auto_ontology.server.knowledge import router as router_module  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema() -> None:
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read(select(s.knowledge_item.c.id).limit(1))
        store().query_read(select(s.audit_event.c.seq).limit(1))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"schema unavailable (alembic upgrade head): {exc}")


ACTORS = {
    "u-owner": Actor("user", "u-owner", role="viewer"),
    "u-other": Actor("user", "u-other", role="viewer"),
    "u-dom": Actor("user", "u-dom", role="viewer"),
    "u-admin": Actor("user", "u-admin", role="admin"),
    "u-agent": Actor("agent", "u-agent", role="admin"),
}


def _as(user: str) -> dict[str, str]:
    return {"x-auto-ontology-user-id": user}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """A database owned by ``u-dom``, the routes, and a clean-up of what they made."""
    token = uuid.uuid4().hex[:10]
    database_id = store().query_write(
        s.catalog_database.insert()
        .values(name=f"kn-{token}", owner_id="u-dom")
        .returning(s.catalog_database.c.id)
    )[0]["id"]
    audit_on = {"value": False}
    monkeypatch.setattr(router_module, "is_knowledge_items_enabled", lambda: True)
    monkeypatch.setattr(capture, "is_knowledge_items_enabled", lambda: True)
    monkeypatch.setattr(
        router_module, "is_knowledge_admin_audit_enabled", lambda: audit_on["value"]
    )
    monkeypatch.setattr(
        knowledge_dal, "is_knowledge_admin_audit_enabled", lambda: audit_on["value"]
    )
    monkeypatch.setattr(knowledge_dal, "resolve_actor", lambda uid: ACTORS[uid])
    # No Better Auth schema in a bare test database: nobody has an email.
    monkeypatch.setattr(groups_dal, "get_account", lambda uid: None)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    world = {
        "client": TestClient(app),
        "database": f"kn-{token}",
        "database_id": database_id,
        "audit_on": audit_on,
        "token": token,
    }
    yield world
    ids = [
        row["id"]
        for row in store().query_read(
            select(s.knowledge_item.c.id).where(
                s.knowledge_item.c.database_id == database_id
            )
        )
    ]
    ids += world.get("captured", [])
    if ids:
        store().query_write(
            delete(s.knowledge_event).where(s.knowledge_event.c.item_id.in_(ids))
        )
        store().query_write(
            delete(s.knowledge_item).where(s.knowledge_item.c.id.in_(ids))
        )
        store().query_write(
            delete(s.audit_event).where(s.audit_event.c.target_id.in_(ids))
        )
    store().query_write(
        delete(s.catalog_database).where(s.catalog_database.c.id == database_id)
    )


def _create(world: dict[str, Any], user: str = "u-owner", **extra: Any) -> dict:
    response = world["client"].post(
        "/api/knowledge-items",
        headers=_as(user),
        json={
            "kind": "term",
            "content": {
                "name": "VIP",
                "definition": f"spends a lot {uuid.uuid4().hex}",
            },
            "database": world["database"],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post(world: dict[str, Any], item_id: str, action: str, user: str, **body: Any):
    return world["client"].post(
        f"/api/knowledge-items/{item_id}/{action}", headers=_as(user), json=body
    )


def _audit_rows(item_id: str) -> list[dict[str, Any]]:
    return store().query_read(
        select(s.audit_event)
        .where(s.audit_event.c.target_id == item_id)
        .order_by(s.audit_event.c.seq)
    )


# -- create, read, scope filter ------------------------------------------------


def test_create_makes_a_personal_draft_with_one_event_and_one_audit_row(
    world: dict,
) -> None:
    created = _create(world)
    item = created["data"]
    assert (item["status"], item["scope"], item["owner_id"]) == (
        "draft",
        "personal",
        "u-owner",
    )
    assert item["database_id"] == world["database_id"]
    assert item["content"]["database"] == world["database"]
    assert item["provenance"]["source"] == "manual"
    assert [e["action"] for e in created["events"]] == ["propose"]
    rows = _audit_rows(item["id"])
    assert [r["action"] for r in rows] == ["knowledge.propose"]
    assert rows[0]["details"] == {
        "kind": "term",
        "to_status": "draft",
        "source": "manual",
    }
    assert "definition" not in str(rows[0]["details"])


def test_the_owner_sees_the_draft_and_what_they_may_do(world: dict) -> None:
    item = _create(world)["data"]
    got = world["client"].get(
        f"/api/knowledge-items/{item['id']}", headers=_as("u-owner")
    )
    assert got.status_code == 200
    assert got.json()["data"]["allowed_actions"] == ["edit", "submit", "deprecate"]


@pytest.mark.parametrize("viewer", ["u-other", "u-dom", "u-admin"])
def test_a_personal_draft_is_a_404_for_everyone_else_admins_included(
    viewer: str, world: dict
) -> None:
    item = _create(world)["data"]
    got = world["client"].get(f"/api/knowledge-items/{item['id']}", headers=_as(viewer))
    assert got.status_code == 404
    listed = world["client"].get("/api/knowledge-items", headers=_as(viewer)).json()
    assert item["id"] not in [i["id"] for i in listed["data"]]
    for action in ("submit", "withdraw", "deprecate", "approve"):
        assert _post(world, item["id"], action, viewer).status_code == 404


def test_the_audit_setting_lets_an_admin_read_but_not_change_it(world: dict) -> None:
    item = _create(world)["data"]
    world["audit_on"]["value"] = True
    assert (
        world["client"]
        .get(f"/api/knowledge-items/{item['id']}", headers=_as("u-admin"))
        .status_code
        == 200
    )
    assert (
        world["client"]
        .get(f"/api/knowledge-items/{item['id']}", headers=_as("u-dom"))
        .status_code
        == 404
    )
    edit = world["client"].patch(
        f"/api/knowledge-items/{item['id']}",
        headers=_as("u-admin"),
        json={
            "content": {"name": "VIP", "definition": "hijack"},
            "expected_version": 1,
        },
    )
    assert edit.status_code == 403


# -- edit and the optimistic lock ---------------------------------------------


def test_an_edit_bumps_the_version_and_a_stale_one_is_a_409_that_changes_nothing(
    world: dict,
) -> None:
    client = world["client"]
    item = _create(world)["data"]
    url = f"/api/knowledge-items/{item['id']}"
    first = client.patch(
        url,
        headers=_as("u-owner"),
        json={
            "content": {"name": "VIP", "definition": "mine v2"},
            "expected_version": 1,
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["current_version"] == 2
    stale = client.patch(
        url,
        headers=_as("u-owner"),
        json={
            "content": {"name": "VIP", "definition": "from an old tab"},
            "expected_version": 1,
        },
    )
    assert stale.status_code == 409
    assert "changed since it was loaded" in stale.json()["detail"]
    now = client.get(url, headers=_as("u-owner")).json()["data"]
    assert now["content"]["definition"] == "mine v2"
    assert now["current_version"] == 2


def test_only_the_owner_edits_and_only_a_draft(world: dict) -> None:
    client = world["client"]
    item = _create(world)["data"]
    url = f"/api/knowledge-items/{item['id']}"
    body = {"content": {"name": "VIP", "definition": "x"}, "expected_version": 1}
    assert client.patch(url, headers=_as("u-other"), json=body).status_code == 404
    assert _post(world, item["id"], "submit", "u-owner").status_code == 200
    again = client.patch(url, headers=_as("u-owner"), json=body)
    assert again.status_code == 409


def test_an_edit_cannot_change_the_database(world: dict) -> None:
    item = _create(world)["data"]
    edited = world["client"].patch(
        f"/api/knowledge-items/{item['id']}",
        headers=_as("u-owner"),
        json={
            "content": {"name": "VIP", "definition": "x", "database": "elsewhere"},
            "expected_version": 1,
        },
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["content"]["database"] == world["database"]


# -- the review flow and the permission matrix ---------------------------------


def test_submit_then_the_database_owner_sees_it_in_the_review_queue(
    world: dict,
) -> None:
    client = world["client"]
    item = _create(world)["data"]
    assert _post(world, item["id"], "submit", "u-owner").status_code == 200
    queue = client.get(
        "/api/knowledge-items?reviewable=true&status=in_review", headers=_as("u-dom")
    ).json()
    assert [i["id"] for i in queue["data"]] == [item["id"]]
    assert "approve" in queue["data"][0]["allowed_actions"]
    for user in ("u-owner", "u-other"):
        other = client.get(
            "/api/knowledge-items?reviewable=true", headers=_as(user)
        ).json()
        assert item["id"] not in [i["id"] for i in other["data"]]


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("u-owner", 403),  # nobody certifies what they proposed
        ("u-other", 404),  # cannot even see it
        ("u-agent", 404),
    ],
)
def test_who_may_not_approve(user: str, expected: int, world: dict) -> None:
    item = _create(world)["data"]
    _post(world, item["id"], "submit", "u-owner")
    response = _post(world, item["id"], "approve", user)
    assert response.status_code == expected
    now = world["client"].get(
        f"/api/knowledge-items/{item['id']}", headers=_as("u-owner")
    )
    assert now.json()["data"]["status"] == "in_review"
    assert now.json()["data"]["scope"] == "personal"


@pytest.mark.parametrize("approver", ["u-dom", "u-admin"])
def test_the_database_owner_and_an_admin_approve_for_everyone(
    approver: str, world: dict
) -> None:
    item = _create(world)["data"]
    _post(world, item["id"], "submit", "u-owner")
    approved = _post(world, item["id"], "approve", approver, comment="good")
    assert approved.status_code == 200, approved.text
    data = approved.json()["data"]
    assert (data["status"], data["scope"]) == ("certified", "shared")
    assert [e["action"] for e in approved.json()["events"]] == [
        "propose",
        "submit",
        "promote_scope",
        "approve",
    ]
    # now everyone sees it
    seen = world["client"].get(
        f"/api/knowledge-items/{item['id']}", headers=_as("u-other")
    )
    assert seen.status_code == 200
    assert [r["action"] for r in _audit_rows(item["id"])] == [
        "knowledge.propose",
        "knowledge.submit",
        "knowledge.promote_scope",
        "knowledge.approve",
    ]


def test_an_admin_who_proposed_it_still_cannot_approve_it(world: dict) -> None:
    item = _create(world, user="u-admin")["data"]
    _post(world, item["id"], "submit", "u-admin")
    response = _post(world, item["id"], "approve", "u-admin")
    assert response.status_code == 403
    now = world["client"].get(
        f"/api/knowledge-items/{item['id']}", headers=_as("u-admin")
    )
    assert now.json()["data"]["scope"] == "personal"  # nothing was shared on the way


def test_reject_and_request_changes_need_a_comment_and_a_certifier(
    world: dict,
) -> None:
    client = world["client"]
    first = _create(world)["data"]
    _post(world, first["id"], "submit", "u-owner")
    assert _post(world, first["id"], "reject", "u-dom").status_code == 422
    assert (
        _post(world, first["id"], "reject", "u-owner", comment="x").status_code == 403
    )
    rejected = _post(world, first["id"], "reject", "u-dom", comment="too vague")
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["events"][-1]["comment"] == "too vague"

    second = _create(world)["data"]
    _post(world, second["id"], "submit", "u-owner")
    back = _post(world, second["id"], "request-changes", "u-dom", comment="add the SQL")
    assert back.json()["data"]["status"] == "draft"
    mine = client.get(
        "/api/knowledge-items?mine=true&status=draft", headers=_as("u-owner")
    ).json()
    assert second["id"] in [i["id"] for i in mine["data"]]


def test_the_owner_withdraws_their_own_draft_and_nobody_else_can(
    world: dict,
) -> None:
    item = _create(world)["data"]
    assert _post(world, item["id"], "withdraw", "u-dom").status_code == 404
    done = _post(world, item["id"], "withdraw", "u-owner")
    assert done.status_code == 200
    assert done.json()["data"]["status"] == "deprecated"
    assert [r["action"] for r in _audit_rows(item["id"])][-1] == "knowledge.deprecate"


def test_a_stale_version_on_a_transition_is_a_409(world: dict) -> None:
    item = _create(world)["data"]
    world["client"].patch(
        f"/api/knowledge-items/{item['id']}",
        headers=_as("u-owner"),
        json={"content": {"name": "VIP", "definition": "v2"}, "expected_version": 1},
    )
    response = _post(world, item["id"], "submit", "u-owner", expected_version=1)
    assert response.status_code == 409
    now = world["client"].get(
        f"/api/knowledge-items/{item['id']}", headers=_as("u-owner")
    )
    assert now.json()["data"]["status"] == "draft"


def test_an_unknown_item_is_a_404(world: dict) -> None:
    got = world["client"].get("/api/knowledge-items/nope", headers=_as("u-owner"))
    assert got.status_code == 404


def test_the_listing_pages_with_a_keyset_cursor(world: dict) -> None:
    client = world["client"]
    ids = {_create(world)["data"]["id"] for _ in range(5)}
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"mine": "true", "limit": "2", "database": world["database"]}
        if cursor:
            params["cursor"] = cursor
        page = client.get(
            "/api/knowledge-items", params=params, headers=_as("u-owner")
        ).json()
        seen.extend(i["id"] for i in page["data"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == ids


def test_the_filters_narrow_the_listing(world: dict) -> None:
    client = world["client"]
    item = _create(world)["data"]
    synonym = client.post(
        "/api/knowledge-items",
        headers=_as("u-owner"),
        json={
            "kind": "synonym",
            "content": {"term": "VIP", "synonyms": ["gold customer"]},
            "database": world["database"],
        },
    )
    assert synonym.status_code == 201
    by_kind = client.get(
        "/api/knowledge-items",
        params={"kind": "synonym", "database": world["database"]},
        headers=_as("u-owner"),
    ).json()
    assert [i["kind"] for i in by_kind["data"]] == ["synonym"]
    none = client.get(
        "/api/knowledge-items",
        params={"database": "no-such-db"},
        headers=_as("u-owner"),
    ).json()
    assert none["data"] == []
    assert item["id"]


# -- capture --------------------------------------------------------------------


def _capture(world: dict[str, Any], **overrides: Any) -> dict[str, str] | None:
    args: dict[str, Any] = {
        "user_id": "u-owner",
        "conversation_id": world.setdefault("conversation", uuid.uuid4()),
        "clarification_id": world.setdefault("clarification", str(uuid.uuid4())),
        "term": "VIP customers",
        "definition": "Top 10% by payments",
        "database": world["database"],
        "option_id": "opt-2",
        "asked_at": datetime(2026, 11, 17, 9, 0, tzinfo=UTC),
    }
    args.update(overrides)
    saved = capture.capture_clarification_answer(**args)
    if saved:
        world.setdefault("captured", []).append(saved["id"])
    return saved


def test_an_answer_becomes_a_personal_draft_with_who_and_when(world: dict) -> None:
    saved = _capture(world)
    assert saved is not None and saved["name"] == "VIP customers"
    item = knowledge_dal.get_item(saved["id"])
    assert item is not None
    assert (item["status"], item["scope"], item["owner_id"]) == (
        "draft",
        "personal",
        "u-owner",
    )
    assert item["content"] == {
        "name": "VIP customers",
        "definition": "Top 10% by payments",
        "database": world["database"],
    }
    provenance = item["provenance"]
    assert provenance["source"] == "clarification"
    assert provenance["option_id"] == "opt-2"
    assert provenance["conversation_id"] == str(world["conversation"])
    assert provenance["asked_at"].startswith("2026-11-17T09:00")
    assert provenance["answered_at"]
    event = knowledge_dal.list_events(saved["id"])[0]
    assert (event["actor_type"], event["actor_id"]) == ("user", "u-owner")
    # It is the owner's, in their own space, and the route shows it to them only.
    got = world["client"].get(
        f"/api/knowledge-items/{saved['id']}", headers=_as("u-owner")
    )
    assert got.status_code == 200
    other = world["client"].get(
        f"/api/knowledge-items/{saved['id']}", headers=_as("u-other")
    )
    assert other.status_code == 404
    _cleanup_captured(world)


def test_the_same_answer_twice_makes_one_draft(world: dict) -> None:
    first = _capture(world)
    again = _capture(world, definition="Top 10% by payments")
    # A retry that arrives with a different clock still finds the draft.
    third = _capture(world)
    assert first and again and third
    assert first["id"] == again["id"] == third["id"]
    assert len(knowledge_dal.list_events(first["id"])) == 1
    _cleanup_captured(world)


def test_a_free_text_answer_is_marked_as_such(world: dict) -> None:
    saved = _capture(world, option_id=None, definition="Customers who spend a lot")
    assert saved is not None
    provenance = knowledge_dal.get_item(saved["id"])["provenance"]
    assert provenance["free_text"] is True
    assert "option_id" not in provenance
    _cleanup_captured(world)


def test_an_unknown_database_leaves_a_glossary_draft(world: dict) -> None:
    saved = _capture(world, database="not-in-the-catalog")
    assert saved is not None
    item = knowledge_dal.get_item(saved["id"])
    assert item["database_id"] is None
    assert item["content"]["database"] is None
    _cleanup_captured(world)


def test_with_the_flag_off_nothing_is_captured(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture, "is_knowledge_items_enabled", lambda: False)
    assert _capture(world) is None
    item_id = capture.capture_item_id(world["conversation"], world["clarification"])
    assert knowledge_dal.get_item(item_id) is None


def test_a_failure_to_save_is_swallowed_and_writes_nothing(
    world: dict, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the store is down")

    monkeypatch.setattr(knowledge_dal, "create_draft", boom)
    assert _capture(world) is None
    item_id = capture.capture_item_id(world["conversation"], world["clarification"])
    assert knowledge_dal.get_item(item_id) is None
    assert "Could not save the clarification answer" in caplog.text


def _cleanup_captured(world: dict[str, Any]) -> None:
    ids = world.get("captured", [])
    if ids:
        store().query_write(
            delete(s.knowledge_event).where(s.knowledge_event.c.item_id.in_(ids))
        )
        store().query_write(
            delete(s.knowledge_item).where(s.knowledge_item.c.id.in_(ids))
        )


def test_the_audit_helper_is_the_real_one_here() -> None:
    # Guards the fixtures above: the audit rows asserted in this file come from
    # server.audit.audit, not from a stand-in.
    assert router_module.audit is audit_module.audit
