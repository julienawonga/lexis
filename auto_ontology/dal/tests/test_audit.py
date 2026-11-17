# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0
"""Postgres integration tests for the audit log.

Each rule that gets a test fails for a different reason:

* **append and read back** -- an event keeps what it was given, newest first;
* **filters and keyset pagination** -- action prefix, actor, target, time range,
  and pages that neither repeat nor skip a row;
* **the details allowlist** -- an unknown field is dropped, a nested object is
  dropped, and a connection event never carries a password, whether it is sent
  as a field or hidden under an allowed key;
* **the audit never fails the action** -- a write that errors is swallowed.

They need the real schema (``alembic upgrade head``) and skip without it.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import delete, select  # noqa: E402

from auto_ontology.dal import audit  # noqa: E402
from auto_ontology.dal import schema as s  # noqa: E402
from auto_ontology.dal.session import store  # noqa: E402

FAKE_PASSWORD = "hunter2-not-a-real-password"


@pytest.fixture(scope="module", autouse=True)
def require_schema() -> None:
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read(select(s.audit_event.c.seq).limit(1))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"audit schema unavailable (alembic upgrade head): {exc}")


@pytest.fixture
def actor() -> Iterator[str]:
    """A unique actor id, and its rows removed afterwards."""
    actor_id = f"audit-test-{uuid.uuid4().hex}"
    yield actor_id
    store().query_write(
        delete(s.audit_event).where(s.audit_event.c.actor_id == actor_id)
    )


def _mine(actor_id: str, **filters: Any) -> dict[str, Any]:
    return audit.list_events(actor_id=actor_id, **filters)


def test_record_appends_and_reads_back(actor: str) -> None:
    event_id = audit.record(
        "term.create",
        actor_id=actor,
        actor_email="a@example.com",
        target_kind="term",
        target_id="t-1",
        target_name="Revenue",
        request_id="req-1",
        details={"database": "pagila", "table_count": 2},
    )
    assert event_id

    [row] = _mine(actor)["events"]
    assert row["id"] == event_id
    assert row["action"] == "term.create"
    assert row["actor_kind"] == "user"
    assert row["actor_email"] == "a@example.com"
    assert (row["target_kind"], row["target_id"], row["target_name"]) == (
        "term",
        "t-1",
        "Revenue",
    )
    assert row["request_id"] == "req-1"
    assert row["details"] == {"database": "pagila", "table_count": 2}
    assert abs(datetime.now(UTC) - row["at"]) < timedelta(minutes=1)


def test_a_call_without_an_actor_is_a_system_event() -> None:
    event_id = audit.record("zone.delete", target_kind="zone", target_id="z")
    assert event_id
    try:
        row = store().query_read(
            select(s.audit_event).where(s.audit_event.c.id == event_id)
        )[0]
        assert row["actor_kind"] == "system"
        assert row["actor_id"] is None
    finally:
        store().query_write(delete(s.audit_event).where(s.audit_event.c.id == event_id))


def test_events_come_back_newest_first(actor: str) -> None:
    for name in ("one", "two", "three"):
        audit.record("term.update", actor_id=actor, target_name=name)
    names = [e["target_name"] for e in _mine(actor)["events"]]
    assert names == ["three", "two", "one"]


def test_filters(actor: str) -> None:
    audit.record("term.create", actor_id=actor, target_kind="term", target_id="a")
    audit.record("term.delete", actor_id=actor, target_kind="term", target_id="b")
    audit.record("zone.create", actor_id=actor, target_kind="zone", target_id="c")

    assert len(_mine(actor)["events"]) == 3
    terms = _mine(actor, action_prefix="term.")["events"]
    assert {e["action"] for e in terms} == {"term.create", "term.delete"}
    assert [e["target_id"] for e in _mine(actor, target_kind="zone")["events"]] == ["c"]
    assert [e["action"] for e in _mine(actor, target_id="b")["events"]] == [
        "term.delete"
    ]
    # LIKE wildcards in a prefix are matched literally, not as patterns.
    assert _mine(actor, action_prefix="term_")["events"] == []
    assert _mine(actor, action_prefix="%")["events"] == []

    now = datetime.now(UTC)
    assert len(_mine(actor, since=now - timedelta(minutes=5))["events"]) == 3
    assert _mine(actor, since=now + timedelta(minutes=5))["events"] == []
    assert len(_mine(actor, until=now + timedelta(minutes=5))["events"]) == 3
    assert _mine(actor, until=now - timedelta(minutes=5))["events"] == []


def test_keyset_pagination_neither_repeats_nor_skips(actor: str) -> None:
    for index in range(7):
        audit.record("term.update", actor_id=actor, target_id=str(index))

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = _mine(actor, limit=3, before_seq=cursor)
        seen.extend(e["target_id"] for e in page["events"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [str(i) for i in reversed(range(7))]
    assert pages == 3

    # An event appended between two pages does not shift the next one.
    first = _mine(actor, limit=3)
    audit.record("term.update", actor_id=actor, target_id="late")
    second = _mine(actor, limit=3, before_seq=first["next_cursor"])
    assert [e["target_id"] for e in second["events"]] == ["3", "2", "1"]

    # A page that holds everything left has no dangling cursor.
    assert _mine(actor, limit=8)["next_cursor"] is None


def test_unknown_detail_fields_are_dropped(actor: str) -> None:
    audit.record(
        "term.update",
        actor_id=actor,
        details={
            "fields": ["name", "description"],
            "question": "how much did Acme spend?",
            "description": "free text",
            "nested": {"a": 1},
        },
    )
    [row] = _mine(actor)["events"]
    assert row["details"] == {"fields": ["name", "description"]}


def test_an_action_without_an_allowlist_keeps_no_details(actor: str) -> None:
    audit.record("brand_new.action", actor_id=actor, details={"anything": "x"})
    [row] = _mine(actor)["events"]
    assert row["details"] == {}


def test_values_are_cut_down_to_short_scalars(actor: str) -> None:
    audit.record(
        "term.update",
        actor_id=actor,
        details={"fields": [{"password": FAKE_PASSWORD}, "x" * 500, *range(50)]},
    )
    [row] = _mine(actor)["events"]
    assert FAKE_PASSWORD not in str(row)
    assert all(len(str(item)) <= 200 for item in row["details"]["fields"])
    assert len(row["details"]["fields"]) <= 20


def test_a_connection_event_never_contains_the_password(actor: str) -> None:
    connection = {
        "database": "pagila",
        "type": "postgres",
        "host": "db.internal",
        "user": "svc",
        "password": FAKE_PASSWORD,
        "private_key": FAKE_PASSWORD,
    }
    for action in ("connection.create", "connection.update", "connection.delete"):
        audit.record(
            action,
            actor_id=actor,
            target_kind="connection",
            target_id="pagila",
            target_name="pagila",
            details={
                "type": "postgres",
                "ontology_language": "en",
                # What a careless caller might add: all of it must be dropped.
                "connection": connection,
                "password": FAKE_PASSWORD,
                "fields": ["password"],
                "host": "db.internal",
            },
        )
    rows = _mine(actor)["events"]
    assert len(rows) == 3
    for row in rows:
        assert FAKE_PASSWORD not in repr(row)
        assert "db.internal" not in repr(row)
        assert "password" not in row["details"]
        assert "connection" not in row["details"]
        expected = (
            {}
            if row["action"] == "connection.delete"
            else {"type": "postgres", "ontology_language": "en"}
        )
        assert row["details"] == expected


def test_a_failing_write_is_swallowed_and_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        def query_write(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("database went away")

    monkeypatch.setattr(audit, "store", lambda: Broken())
    with caplog.at_level(logging.ERROR, logger=audit.logger.name):
        assert audit.record("term.create", actor_id="whoever") is None
    assert any("could not record term.create" in r.getMessage() for r in caplog.records)


def test_a_rejected_row_is_swallowed_too(caplog: pytest.LogCaptureFixture) -> None:
    # A malformed action and an unknown actor kind never reach the caller.
    with caplog.at_level(logging.ERROR, logger=audit.logger.name):
        assert audit.record("Not An Action") is None
        assert audit.record("term.create", actor_kind="robot") is None
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 2
