# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""At most one API-triggered ingest per database runs at a time."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import auto_ontology.ingestion_service.ingest as mod


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(
        started=[],
        release=threading.Event(),
        entered=threading.Event(),
        fail=False,
    )

    def fake_run_ingest(connector: SimpleNamespace) -> None:
        state.started.append(connector.database_name)
        state.entered.set()
        state.release.wait(timeout=10)
        if state.fail:
            raise RuntimeError("boom")

    monkeypatch.setattr(mod, "invalidate_connectors_cache", lambda: None)
    monkeypatch.setattr(
        mod,
        "get_connectors",
        lambda: [
            SimpleNamespace(database_name="pagila"),
            SimpleNamespace(database_name="chinook"),
        ],
    )
    monkeypatch.setattr(mod, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(mod, "replay_rules", lambda _origin: None)
    mod._in_flight.clear()
    yield state
    state.release.set()
    _join("pagila")
    _join("chinook")
    mod._in_flight.clear()


def _join(name: str) -> None:
    for thread in threading.enumerate():
        if thread.name == f"ingest-{name}":
            thread.join(timeout=10)


def test_a_second_trigger_for_one_database_starts_nothing(
    runs: SimpleNamespace,
) -> None:
    assert mod.trigger_ingest({"database": "pagila"}) is True
    assert runs.entered.wait(timeout=10)

    assert mod.trigger_ingest({"database": "Pagila "}) is False

    runs.release.set()
    _join("pagila")
    assert runs.started == ["pagila"]


def test_two_databases_both_run(runs: SimpleNamespace) -> None:
    assert mod.trigger_ingest({"database": "pagila"}) is True
    assert mod.trigger_ingest({"database": "chinook"}) is True

    runs.release.set()
    _join("pagila")
    _join("chinook")
    assert sorted(runs.started) == ["chinook", "pagila"]


def test_the_lock_is_released_after_a_failure(runs: SimpleNamespace) -> None:
    runs.fail = True
    runs.release.set()
    assert mod.trigger_ingest({"database": "pagila"}) is True
    _join("pagila")

    assert mod.trigger_ingest({"database": "pagila"}) is True
    _join("pagila")
    assert runs.started == ["pagila", "pagila"]


def test_the_lock_is_released_when_the_thread_cannot_start(
    runs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Broken:
        def __init__(self, **_kwargs: object) -> None: ...

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(mod.threading, "Thread", _Broken)
    with pytest.raises(RuntimeError):
        mod.trigger_ingest({"database": "pagila"})

    assert mod._in_flight == set()
