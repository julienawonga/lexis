# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0
"""The audit route and helper, with fakes (the DAL has its own real-Postgres tests).

* ``GET /api/audit-events`` is admin only: 401 without a named caller, 403 for a
  viewer, 200 for an admin, and the filters reach the DAL;
* ``audit()`` takes the actor from the gateway header, never raises, and a
  mutating route calls it after the action succeeded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from auto_ontology.server import audit as audit_module
from auto_ontology.server.audit import audit, list_audit_events
from auto_ontology.server.zones import router as zones_router

_HEADER = b"x-auto-ontology-user-id"


def _request(user_id: str | None, **extra_headers: str) -> Request:
    headers = [(k.encode(), v.encode()) for k, v in extra_headers.items()]
    if user_id is not None:
        headers.append((_HEADER, user_id.encode()))
    return Request({"type": "http", "headers": headers})


def _list(request: Request, **overrides: Any) -> dict:
    args: dict[str, Any] = {
        "action_prefix": None,
        "actor_id": None,
        "target_kind": None,
        "target_id": None,
        "since": None,
        "until": None,
        "cursor": None,
        "limit": 50,
    }
    args.update(overrides)
    return list_audit_events(request, **args)


class FakeDal:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, dict[str, Any]]] = []
        self.list_kwargs: dict[str, Any] = {}

    def record(self, action: str, **kwargs: Any) -> str:
        self.recorded.append((action, kwargs))
        return "event-1"

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        self.list_kwargs = kwargs
        return {
            "events": [
                {
                    "id": "e1",
                    "at": datetime(2026, 11, 17, tzinfo=UTC),
                    "actor_id": "u1",
                    "actor_email": "a@example.com",
                    "actor_kind": "user",
                    "action": "term.create",
                    "target_kind": "term",
                    "target_id": "t1",
                    "target_name": "Revenue",
                    "request_id": None,
                    "details": {},
                }
            ],
            "next_cursor": 41,
        }


@pytest.fixture
def dal(monkeypatch: pytest.MonkeyPatch) -> FakeDal:
    fake = FakeDal()
    monkeypatch.setattr(audit_module.audit_dal, "record", fake.record)
    monkeypatch.setattr(audit_module.audit_dal, "list_events", fake.list_events)
    monkeypatch.setattr(
        audit_module.groups_dal,
        "get_account",
        lambda user_id: {"id": user_id, "email": f"{user_id}@example.com"},
    )
    return fake


def _as(monkeypatch: pytest.MonkeyPatch, *, admin: bool) -> None:
    monkeypatch.setattr(audit_module.postgres_dal, "is_admin", lambda user_id: admin)


def test_reading_without_a_caller_is_401(dal: FakeDal) -> None:
    with pytest.raises(HTTPException) as refused:
        _list(_request(None))
    assert refused.value.status_code == 401


def test_a_viewer_gets_403(dal: FakeDal, monkeypatch: pytest.MonkeyPatch) -> None:
    _as(monkeypatch, admin=False)
    with pytest.raises(HTTPException) as refused:
        _list(_request("viewer-1"))
    assert refused.value.status_code == 403
    assert dal.list_kwargs == {}


def test_an_admin_reads_and_the_filters_reach_the_dal(
    dal: FakeDal, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(monkeypatch, admin=True)
    since = datetime(2026, 11, 1, tzinfo=UTC)
    page = _list(
        _request("admin-1"),
        action_prefix="term.",
        actor_id="u1",
        target_kind="term",
        target_id="t1",
        since=since,
        cursor=99,
        limit=10,
    )
    assert page["next_cursor"] == 41
    assert page["data"][0]["action"] == "term.create"
    assert dal.list_kwargs == {
        "action_prefix": "term.",
        "actor_id": "u1",
        "target_kind": "term",
        "target_id": "t1",
        "since": since,
        "until": None,
        "before_seq": 99,
        "limit": 10,
    }


def test_audit_names_the_actor_from_the_gateway_header(dal: FakeDal) -> None:
    audit(
        _request("user-7", **{"x-request-id": "req-9"}),
        "zone.delete",
        target_kind="zone",
        target_id="z1",
    )
    [(action, kwargs)] = dal.recorded
    assert action == "zone.delete"
    assert kwargs["actor_id"] == "user-7"
    assert kwargs["actor_email"] == "user-7@example.com"
    assert kwargs["actor_kind"] == "user"
    assert kwargs["request_id"] == "req-9"
    assert "client" not in str(kwargs) and "ip" not in kwargs


def test_audit_without_a_header_is_a_system_event(dal: FakeDal) -> None:
    audit(_request(None), "zone.delete", target_id="z1")
    [(_, kwargs)] = dal.recorded
    assert kwargs["actor_id"] is None
    assert kwargs["actor_kind"] == "system"


def test_audit_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database down")

    monkeypatch.setattr(audit_module.groups_dal, "get_account", boom)
    monkeypatch.setattr(audit_module.audit_dal, "record", boom)
    audit(_request("user-1"), "zone.delete")  # must not raise


def test_a_mutating_route_calls_audit_after_it_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        zones_router, "audit", lambda request, action, **kw: calls.append((action, kw))
    )
    monkeypatch.setattr(zones_router.dal, "delete_zone", lambda zone_id: True)

    zones_router.delete_zone(_request("admin-1"), "z-1")
    assert calls == [("zone.delete", {"target_kind": "zone", "target_id": "z-1"})]


def test_a_refused_route_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        zones_router, "audit", lambda request, action, **kw: calls.append(action)
    )
    monkeypatch.setattr(zones_router.dal, "delete_zone", lambda zone_id: False)

    with pytest.raises(HTTPException) as missing:
        zones_router.delete_zone(_request("admin-1"), "z-404")
    assert missing.value.status_code == 404
    assert calls == []


def test_the_connection_routes_hand_audit_no_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_ontology.server.connections import router as connections_router

    password = "hunter2-not-a-real-password"
    row = {"database": "pagila", "type": "postgres", "password": password}
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        connections_router,
        "audit",
        lambda request, action, **kw: calls.append((action, kw)),
    )
    monkeypatch.setattr(
        connections_router.service, "create_connection", lambda **kw: dict(row)
    )
    monkeypatch.setattr(
        connections_router.service, "update_connection", lambda **kw: dict(row)
    )
    monkeypatch.setattr(
        connections_router.service, "delete_connection", lambda name: {"id": name}
    )
    monkeypatch.setattr(connections_router, "get_ontology_language", lambda name: "en")
    body = connections_router.ConnectionBody(connection=dict(row))

    connections_router.create_connection(_request("admin-1"), body)
    connections_router.update_connection(_request("admin-1"), body, "pagila")
    connections_router.delete_connection(_request("admin-1"), "pagila")

    assert [action for action, _ in calls] == [
        "connection.create",
        "connection.update",
        "connection.delete",
    ]
    assert password not in repr(calls)
