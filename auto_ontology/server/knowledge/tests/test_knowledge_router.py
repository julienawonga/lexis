# SPDX-License-Identifier: Apache-2.0
"""The knowledge-item routes with the DAL replaced by fakes.

What is under test is the contract of the routes: the flag, who the caller is,
which DAL refusal becomes which status, what is audited and what the audit
may hold. The DAL has its own real-Postgres tests and
``test_knowledge_routes_pg.py`` drives the routes against one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_ontology.dal import audit as audit_dal
from auto_ontology.dal import knowledge as knowledge_dal
from auto_ontology.dal.knowledge_rules import Actor
from auto_ontology.server.knowledge import router as router_module

HEADER = {"x-auto-ontology-user-id": "u-1"}
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


def _item(**overrides: Any) -> dict[str, Any]:
    item = {
        "id": "k-1",
        "kind": "term",
        "status": "draft",
        "scope": "personal",
        "owner_id": "u-1",
        "database_id": None,
        "content": {"name": "VIP", "definition": "spends a lot", "database": None},
        "content_hash": "h",
        "provenance": {"source": "manual"},
        "current_version": 1,
        "created_by": "u-1",
        "created": NOW,
        "modified": NOW,
    }
    item.update(overrides)
    return item


class FakeDal:
    def __init__(self) -> None:
        self.item = _item()
        self.transition_error: Exception | None = None
        self.transitions: list[tuple[str, dict[str, Any]]] = []
        self.visible = True
        self.allowed = ["edit", "submit", "deprecate"]

    # the surface the router uses
    def resolve_actor(self, user_id: str) -> Actor:
        return Actor("user", user_id, role="viewer")

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        return self.item if item_id == self.item["id"] else None

    def can_view(
        self, actor: Actor, item: dict[str, Any], *, audit: bool = False
    ) -> bool:
        return self.visible

    def allowed_actions(self, actor: Actor, item: dict[str, Any]) -> list[str]:
        return self.allowed

    def list_events(self, item_id: str) -> list[dict[str, Any]]:
        return []

    def list_items(self, actor: Actor, **kwargs: Any) -> list[dict[str, Any]]:
        return [self.item]

    def transition(
        self, item_id: str, action: str, actor: Actor, **kwargs: Any
    ) -> dict:
        if self.transition_error is not None:
            raise self.transition_error
        self.transitions.append((action, kwargs))
        return {"item": self.item, "event": {}, "applied": True}

    def create_draft(self, actor: Actor, **kwargs: Any) -> dict[str, Any]:
        self.transitions.append(("propose", kwargs))
        return {"item": self.item, "event": {}, "applied": True}


@pytest.fixture
def dal(monkeypatch: pytest.MonkeyPatch) -> FakeDal:
    fake = FakeDal()
    for name in (
        "resolve_actor",
        "get_item",
        "can_view",
        "allowed_actions",
        "list_events",
        "list_items",
        "transition",
        "create_draft",
    ):
        monkeypatch.setattr(knowledge_dal, name, getattr(fake, name))
    monkeypatch.setattr(router_module, "is_knowledge_items_enabled", lambda: True)
    monkeypatch.setattr(
        router_module, "is_knowledge_admin_audit_enabled", lambda: False
    )
    monkeypatch.setattr(router_module.terms_dal, "resolve_database", lambda d: None)
    monkeypatch.setattr(router_module.groups_dal, "get_account", lambda uid: None)
    return fake


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(request: Any, action: str, **kwargs: Any) -> None:
        calls.append((action, kwargs))

    monkeypatch.setattr(router_module, "audit", record)
    return calls


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    return TestClient(app)


ROUTES = [
    ("get", "/api/knowledge-items"),
    ("get", "/api/knowledge-items/k-1"),
    ("post", "/api/knowledge-items"),
    ("patch", "/api/knowledge-items/k-1"),
    ("post", "/api/knowledge-items/k-1/submit"),
    ("post", "/api/knowledge-items/k-1/approve"),
    ("post", "/api/knowledge-items/k-1/reject"),
    ("post", "/api/knowledge-items/k-1/request-changes"),
    ("post", "/api/knowledge-items/k-1/deprecate"),
    ("post", "/api/knowledge-items/k-1/withdraw"),
    ("post", "/api/knowledge-items/k-1/promote-scope"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_with_the_flag_off_every_route_is_a_plain_404(
    method: str, path: str, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_module, "is_knowledge_items_enabled", lambda: False)
    response = client.request(method.upper(), path, headers=HEADER, json={})
    assert response.status_code == 404
    assert response.json()["detail"] == router_module.DISABLED_MESSAGE


def test_the_status_route_reports_the_flag_either_way(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_module, "is_knowledge_items_enabled", lambda: False)
    assert client.get("/api/knowledge-items/status").json() == {"enabled": False}
    monkeypatch.setattr(router_module, "is_knowledge_items_enabled", lambda: True)
    assert client.get("/api/knowledge-items/status").json() == {"enabled": True}


def test_a_call_without_a_named_caller_is_401(client: TestClient, dal: FakeDal) -> None:
    assert client.get("/api/knowledge-items").status_code == 401
    assert client.post("/api/knowledge-items/k-1/submit").status_code == 401


def test_an_item_the_caller_may_not_see_is_a_404_not_a_403(
    client: TestClient, dal: FakeDal
) -> None:
    dal.visible = False
    assert client.get("/api/knowledge-items/k-1", headers=HEADER).status_code == 404
    assert (
        client.post("/api/knowledge-items/k-1/submit", headers=HEADER).status_code
        == 404
    )
    assert dal.transitions == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (knowledge_dal.ItemNotFound("k-1"), 404),
        (knowledge_dal.PermissionDenied("no"), 403),
        (knowledge_dal.InvalidTransition("wrong state"), 409),
        (knowledge_dal.VersionConflict("k-1", 1, 2), 409),
        (knowledge_dal.InvalidDraft("bad"), 422),
    ],
)
def test_each_dal_refusal_maps_to_its_status(
    error: Exception, status: int, client: TestClient, dal: FakeDal
) -> None:
    dal.transition_error = error
    response = client.post("/api/knowledge-items/k-1/submit", headers=HEADER)
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


def test_a_conflict_message_says_the_item_changed(
    client: TestClient, dal: FakeDal
) -> None:
    dal.transition_error = knowledge_dal.VersionConflict("k-1", 1, 2)
    response = client.patch(
        "/api/knowledge-items/k-1",
        headers=HEADER,
        json={"content": {"name": "VIP", "definition": "x"}, "expected_version": 1},
    )
    assert response.status_code == 409
    assert "changed since it was loaded" in response.json()["detail"]


def test_the_expected_version_reaches_the_dal(client: TestClient, dal: FakeDal) -> None:
    client.patch(
        "/api/knowledge-items/k-1",
        headers=HEADER,
        json={"content": {"name": "VIP", "definition": "x"}, "expected_version": 3},
    )
    action, kwargs = dal.transitions[0]
    assert action == "edit"
    assert kwargs["expected_version"] == 3
    assert kwargs["content"]["definition"] == "x"


def test_an_edit_needs_an_expected_version(client: TestClient, dal: FakeDal) -> None:
    response = client.patch(
        "/api/knowledge-items/k-1",
        headers=HEADER,
        json={"content": {"name": "VIP", "definition": "x"}},
    )
    assert response.status_code == 422
    assert dal.transitions == []


@pytest.mark.parametrize("action", ["reject", "request-changes"])
def test_rejecting_or_asking_for_changes_needs_a_comment(
    action: str, client: TestClient, dal: FakeDal
) -> None:
    for body in ({}, {"comment": "   "}):
        response = client.post(
            f"/api/knowledge-items/k-1/{action}", headers=HEADER, json=body
        )
        assert response.status_code == 422
    assert dal.transitions == []


def test_create_validates_the_content_and_only_accepts_two_kinds(
    client: TestClient, dal: FakeDal
) -> None:
    bad = client.post(
        "/api/knowledge-items",
        headers=HEADER,
        json={"kind": "term", "content": {"name": "VIP"}},
    )
    assert bad.status_code == 422
    other = client.post(
        "/api/knowledge-items",
        headers=HEADER,
        json={"kind": "relation", "content": {"a": 1}},
    )
    assert other.status_code == 422
    assert dal.transitions == []


def test_create_records_a_manual_personal_draft_for_the_caller(
    client: TestClient, dal: FakeDal, audited: list
) -> None:
    response = client.post(
        "/api/knowledge-items",
        headers=HEADER,
        json={"kind": "term", "content": {"name": "VIP", "definition": "spends a lot"}},
    )
    assert response.status_code == 201
    action, kwargs = dal.transitions[0]
    assert action == "propose"
    assert kwargs["owner_id"] == "u-1"
    assert kwargs["provenance"]["source"] == "manual"
    assert audited[0][0] == "knowledge.propose"


def test_an_unknown_database_is_a_422(client: TestClient, dal: FakeDal) -> None:
    response = client.post(
        "/api/knowledge-items",
        headers=HEADER,
        json={
            "kind": "term",
            "content": {"name": "VIP", "definition": "x"},
            "database": "nowhere",
        },
    )
    assert response.status_code == 422


def test_withdraw_is_only_for_the_owner(client: TestClient, dal: FakeDal) -> None:
    dal.item = _item(owner_id="someone-else")
    response = client.post("/api/knowledge-items/k-1/withdraw", headers=HEADER)
    assert response.status_code == 403
    assert dal.transitions == []


def test_withdraw_deprecates_and_is_audited_as_such(
    client: TestClient, dal: FakeDal, audited: list
) -> None:
    response = client.post("/api/knowledge-items/k-1/withdraw", headers=HEADER)
    assert response.status_code == 200
    assert dal.transitions[0][0] == "deprecate"
    assert audited[0][0] == "knowledge.deprecate"


@pytest.mark.parametrize(
    ("path", "body", "audit_action"),
    [
        ("submit", {}, "knowledge.submit"),
        ("reject", {"comment": "no"}, "knowledge.reject"),
        ("request-changes", {"comment": "fix"}, "knowledge.request_changes"),
        ("deprecate", {}, "knowledge.deprecate"),
        ("promote-scope", {}, "knowledge.promote_scope"),
    ],
)
def test_each_mutation_is_audited_once_with_scalar_details(
    path: str,
    body: dict,
    audit_action: str,
    client: TestClient,
    dal: FakeDal,
    audited: list,
) -> None:
    client.post(f"/api/knowledge-items/k-1/{path}", headers=HEADER, json=body)
    assert [a for a, _ in audited] == [audit_action]
    details = audited[0][1]["details"]
    assert all(isinstance(v, str) for v in details.values())
    assert audited[0][1]["target_id"] == "k-1"


def test_a_refused_action_is_not_audited(
    client: TestClient, dal: FakeDal, audited: list
) -> None:
    dal.transition_error = knowledge_dal.PermissionDenied("no")
    client.post("/api/knowledge-items/k-1/submit", headers=HEADER)
    assert audited == []


def test_a_retry_that_changed_nothing_is_not_audited_twice(
    client: TestClient, dal: FakeDal, audited: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        knowledge_dal,
        "transition",
        lambda *a, **k: {"item": dal.item, "event": {}, "applied": False},
    )
    client.post("/api/knowledge-items/k-1/submit", headers=HEADER)
    assert audited == []


def test_approving_a_personal_item_shares_it_first_then_certifies(
    client: TestClient, dal: FakeDal, audited: list
) -> None:
    dal.item = _item(status="in_review", scope="personal", owner_id="someone")
    dal.allowed = ["approve", "reject"]
    response = client.post(
        "/api/knowledge-items/k-1/approve", headers=HEADER, json={"expected_version": 1}
    )
    assert response.status_code == 200
    assert [a for a, _ in dal.transitions] == ["promote_scope", "approve"]
    assert [a for a, _ in audited] == ["knowledge.promote_scope", "knowledge.approve"]


def test_approving_without_the_right_changes_nothing(
    client: TestClient, dal: FakeDal, audited: list
) -> None:
    dal.item = _item(status="in_review", scope="personal", owner_id="someone")
    dal.allowed = []
    response = client.post("/api/knowledge-items/k-1/approve", headers=HEADER)
    assert response.status_code == 403
    assert dal.transitions == []
    assert audited == []


def test_approving_a_draft_is_a_409(client: TestClient, dal: FakeDal) -> None:
    response = client.post("/api/knowledge-items/k-1/approve", headers=HEADER)
    assert response.status_code == 409


def test_a_bad_cursor_is_a_422(client: TestClient, dal: FakeDal) -> None:
    response = client.get("/api/knowledge-items?cursor=%25%25", headers=HEADER)
    assert response.status_code == 422


def test_the_listing_carries_what_the_caller_may_do(
    client: TestClient, dal: FakeDal
) -> None:
    response = client.get("/api/knowledge-items?mine=true", headers=HEADER)
    body = response.json()
    assert body["data"][0]["allowed_actions"] == ["edit", "submit", "deprecate"]
    assert body["next_cursor"] is None


def test_mine_leaves_out_the_items_of_others(client: TestClient, dal: FakeDal) -> None:
    dal.item = _item(owner_id="someone-else", scope="shared", status="certified")
    mine = client.get("/api/knowledge-items?mine=true", headers=HEADER).json()
    assert mine["data"] == []
    assert len(client.get("/api/knowledge-items", headers=HEADER).json()["data"]) == 1


def test_reviewable_keeps_only_what_the_caller_may_approve(
    client: TestClient, dal: FakeDal
) -> None:
    url = "/api/knowledge-items?reviewable=true"
    dal.allowed = ["edit"]
    assert client.get(url, headers=HEADER).json()["data"] == []
    dal.allowed = ["approve"]
    assert len(client.get(url, headers=HEADER).json()["data"]) == 1


# -- the audit allowlist ------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        "knowledge.propose",
        "knowledge.submit",
        "knowledge.approve",
        "knowledge.reject",
        "knowledge.request_changes",
        "knowledge.deprecate",
        "knowledge.promote_scope",
    ],
)
def test_the_audit_keeps_only_scalar_non_content_fields(action: str) -> None:
    details = {
        "kind": "term",
        "from_status": "draft",
        "to_status": "in_review",
        "from_scope": "personal",
        "to_scope": "shared",
        "source": "manual",
        # What a careless caller might add: all dropped.
        "content": {"definition": "what is our VIP churn for Acme?"},
        "definition": "text",
        "comment": "text",
        "question": "text",
        "name": "text",
    }
    clean = audit_dal._sanitize_details(action, details)
    assert set(clean) <= audit_dal.ALLOWED_DETAILS[action]
    assert not {"content", "definition", "comment", "question", "name"} & set(clean)
    assert all(isinstance(v, str) for v in clean.values())
