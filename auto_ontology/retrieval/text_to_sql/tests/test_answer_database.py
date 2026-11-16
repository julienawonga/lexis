# SPDX-License-Identifier: Apache-2.0

"""The answer names the database that produced it (audit E5), through the pump."""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

os.environ.setdefault("REASONING_API_KEY", "test-key")
os.environ.setdefault("REASONING_ENDPOINT", "https://example.test/v1")
os.environ.setdefault("REASONING_MODEL", "openai/test-model")

from auto_ontology.retrieval.text_to_sql import main  # noqa: E402
from auto_ontology.server.chat import router  # noqa: E402


class _App:
    def __init__(self, path_state: dict[str, Any]) -> None:
        self._path_state = path_state

    def stream(
        self, state: dict[str, Any], stream_mode: Any = None, config: Any = None
    ) -> Iterator[tuple[str, Any]]:
        yield (
            "updates",
            {"calculation_response": {"path_state": self._path_state}},
        )


def _answer(monkeypatch: pytest.MonkeyPatch, **extra: Any) -> dict[str, Any]:
    path_state = {
        "final_response": {"response": "ok", "sql_code": "SELECT 1"},
        **extra,
    }
    monkeypatch.setattr(main, "_build_state", lambda payload: {"path_state": {}})
    monkeypatch.setattr(main, "app", _App(path_state))
    events = list(main.stream_agent_response({"question": "q"}))
    assert events[-1]["type"] == "result", events[-1]
    return events[-1]["answer"]


def test_answer_names_the_database_in_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _answer(monkeypatch, target_db="sales")["database"] == "sales"


def test_answer_database_is_null_when_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _answer(monkeypatch)["database"] is None


def test_database_survives_the_pump_to_the_client_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _answer(monkeypatch, target_db="sales")
    monkeypatch.setattr(router, "persist_assistant_result", lambda **_kw: None)
    monkeypatch.setattr(router, "_build_charts_event", lambda *_a: None)
    monkeypatch.setattr(router, "_release", lambda _slot: None)

    class _Worker:
        def events(self) -> Iterator[dict[str, Any]]:
            return iter([{"type": "result", "answer": answer}])

    slot = router._Slot(
        key="user:conv",
        worker=_Worker(),  # type: ignore[arg-type]
        user_id="user",
        conversation_id=uuid.uuid4(),
        analytics_id="analytics",
        question="q",
        client_alive=threading.Event(),
        cancelled=threading.Event(),
        released=threading.Event(),
    )
    router._pump(slot)

    assert slot.buffer[-1]["answer"]["database"] == "sales"
