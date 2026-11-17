# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""A refusal answer crosses the worker-to-server boundary unchanged.

The worker sends the whole ``result`` event and the router buffers it as is, so
``refusal`` reaches the client the way ``caveats`` and ``database`` do. The only
thing the router reads from it for persistence is the response text; a null
``sql_code`` must not break that.
"""

import threading
import uuid
from typing import Any, Iterator

import pytest

from auto_ontology.server.chat import router

REFUSAL_ANSWER: dict[str, Any] = {
    "response": "The data available here does not hold what this asks for.",
    "sql_code": None,
    "sql_columns": [],
    "custom_analyses_used": [],
    "sql_response_from_db": None,
    "refusal": {"missing": ["salary"], "reason": "salary: nothing offered holds it"},
    "caveats": [{"code": "unanswerable", "message": "No query was run."}],
    "database": "hr",
}


def test_refusal_result_is_buffered_whole_and_persisted_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        router, "persist_assistant_result", lambda **kw: persisted.append(kw)
    )
    charts_calls: list[Any] = []
    monkeypatch.setattr(
        router, "_build_charts_event", lambda *a: charts_calls.append(a) or None
    )
    monkeypatch.setattr(router, "_release", lambda _slot: None)

    event = {"type": "result", "answer": dict(REFUSAL_ANSWER)}

    class _FakeWorker:
        def events(self) -> Iterator[dict[str, Any]]:
            return iter([event])

    slot = router._Slot(
        key="user:conv",
        worker=_FakeWorker(),  # type: ignore[arg-type]
        user_id="user",
        conversation_id=uuid.uuid4(),
        analytics_id="analytics",
        question="what is the salary?",
        client_alive=threading.Event(),
        cancelled=threading.Event(),
        released=threading.Event(),
    )
    router._pump(slot)

    assert slot.buffer == [event]
    assert slot.buffer[0]["answer"]["refusal"] == REFUSAL_ANSWER["refusal"]
    assert slot.buffer[0]["answer"]["caveats"] == REFUSAL_ANSWER["caveats"]
    assert persisted[0]["response"] == REFUSAL_ANSWER["response"]
    assert not persisted[0]["sql_code"]
    assert len(charts_calls) == 1  # asked once, and it returns no chart for no rows
