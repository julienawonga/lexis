# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A chat worker that cannot start must produce an error, never a silent end.

No subprocess is spawned: ``PrewarmedWorker`` is replaced by a subclass whose
queues are in-process and whose "process" is a stub, so these tests exercise
the real ``drain_until_ready`` / ``events`` / ``WarmPool.acquire`` / router
code against the exact messages ``_worker_loop`` puts on its queue when init
fails (``error`` then ``done``). A real subprocess failure is not covered.
"""

from __future__ import annotations

import asyncio
import json
import queue
import time
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from pytest import MonkeyPatch

from auto_ontology.server.chat import router
from auto_ontology.server.chat import worker as worker_module
from auto_ontology.server.chat.conversation_dal import PreparedConversation
from auto_ontology.server.chat.helpers import ChatRequest
from auto_ontology.server.chat.worker import PrewarmedWorker


class _Proc:
    def __init__(self, alive: bool) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        pass


class _ScriptedWorker(PrewarmedWorker):
    """A real PrewarmedWorker whose queue content is scripted per spawn."""

    script: list[list[tuple[str, Any]]] = []
    alive_after: bool = False
    spawned: list["_ScriptedWorker"] = []

    def __init__(self) -> None:  # no subprocess
        items = _ScriptedWorker.script.pop(0) if _ScriptedWorker.script else []
        self._out_q = queue.Queue()  # type: ignore[assignment]
        self._in_q = queue.Queue()  # type: ignore[assignment]
        for item in items:
            self._out_q.put(item)
        self._proc = _Proc(_ScriptedWorker.alive_after)  # type: ignore[assignment]
        self.start_error = None
        _ScriptedWorker.spawned.append(self)


_INIT_FAILED = [("error", "Worker init failed: bad model key"), ("done", None)]
_READY = [("ready", None)]


class _Http:
    headers: dict[str, str] = {}

    async def is_disconnected(self) -> bool:
        return False


@pytest.fixture(name="pool")
def pool_fixture(monkeypatch: MonkeyPatch) -> worker_module.WarmPool:
    _ScriptedWorker.script = []
    _ScriptedWorker.spawned = []
    _ScriptedWorker.alive_after = False
    monkeypatch.setattr(worker_module, "PrewarmedWorker", _ScriptedWorker)
    monkeypatch.setattr(worker_module.WarmPool, "_spawn_async", lambda self: None)
    monkeypatch.setattr(worker_module, "_QUEUE_POLL_S", 0.01)
    monkeypatch.setenv("CHAT_MAX_CONCURRENT", "2")
    monkeypatch.delenv("CHAT_WAIT_S", raising=False)
    monkeypatch.delenv("CHAT_WORKER_READY_S", raising=False)
    monkeypatch.setattr(worker_module, "_last_start_error", None, raising=False)
    pool = worker_module.WarmPool()
    router._active_slots.clear()
    monkeypatch.setattr(router, "get_pool", lambda: pool)
    monkeypatch.setattr(router, "semantic_layer_calculated", lambda: True)
    monkeypatch.setattr(router, "_subject_token", lambda _r: None)
    monkeypatch.setattr(
        router, "resolve_internal_user", lambda _r, required=False: "user"
    )
    monkeypatch.setattr(
        router,
        "prepare_conversation",
        lambda **kw: PreparedConversation(history=[], analytics_id="a"),
    )
    monkeypatch.setattr(router, "is_clarification_enabled", lambda: False)
    monkeypatch.setattr(router, "create_stateless_analytics", lambda **kw: "a")
    monkeypatch.setattr(router, "persist_assistant_result", lambda **kw: None)
    monkeypatch.setattr(router, "persist_analytics_result", lambda **kw: None)
    return pool


async def _collect(response: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.startswith("data:") and "[DONE]" not in line:
                events.append(json.loads(line[5:]))
    return events


def test_a_worker_that_failed_init_is_never_handed_out(
    pool: worker_module.WarmPool,
) -> None:
    """Old code: acquire handed out the dead worker; the stream ended silently."""

    async def scenario() -> None:
        _ScriptedWorker.script = [list(_INIT_FAILED), list(_INIT_FAILED)]
        with pytest.raises(HTTPException) as info:
            response = await router.chat_completions(
                ChatRequest(question="q"),
                _Http(),  # type: ignore[arg-type]
            )
            # Old behaviour: a stream is returned and ends with no error event.
            events = await asyncio.wait_for(_collect(response), timeout=5)
            assert [e for e in events if e["type"] == "error"], (
                "stream ended with no error event"
            )
        assert info.value.status_code == 503
        assert "The chat worker could not start" in str(info.value.detail)
        assert "bad model key" in str(info.value.detail)

    asyncio.run(scenario())
    assert pool.slots_in_use() == 0
    assert len(_ScriptedWorker.spawned) == 2  # one retry, no more
    assert "bad model key" in worker_module.chat_worker_stats()["last_start_error"]


def test_done_without_an_answer_surfaces_an_error_event(
    pool: worker_module.WarmPool,
) -> None:
    _ScriptedWorker.alive_after = True
    _ScriptedWorker.script = [list(_READY)]

    async def scenario() -> list[dict[str, Any]]:
        response = await router.chat_completions(
            ChatRequest(question="q", conversation_id=uuid.uuid4()),
            _Http(),  # type: ignore[arg-type]
        )
        worker = _ScriptedWorker.spawned[-1]
        worker._out_q.put(("done", None))  # the run ends with no result
        return await asyncio.wait_for(_collect(response), timeout=5)

    events = asyncio.run(scenario())
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "stopped without an answer" in errors[0]["message"]
    assert pool.slots_in_use() == 0


def test_drain_reports_init_failure_and_keeps_the_reason(
    pool: worker_module.WarmPool,
) -> None:
    _ScriptedWorker.script = [list(_INIT_FAILED)]
    w = _ScriptedWorker()
    assert w.drain_until_ready(timeout=1) is False
    assert "bad model key" in (w.start_error or "")


def test_drain_is_bounded_when_the_worker_hangs(pool: worker_module.WarmPool) -> None:
    _ScriptedWorker.alive_after = True
    _ScriptedWorker.script = [[]]
    w = _ScriptedWorker()
    started = time.monotonic()
    assert w.drain_until_ready(timeout=0.2) is False
    assert time.monotonic() - started < 2
    assert "did not become ready" in (w.start_error or "")


def test_acquire_recovers_when_the_second_start_works(
    pool: worker_module.WarmPool,
) -> None:
    _ScriptedWorker.alive_after = True
    _ScriptedWorker.script = [list(_INIT_FAILED), list(_READY)]
    w = pool.acquire()
    assert w.is_alive()
    assert pool.slots_in_use() == 1
    pool.replace(w)
    assert pool.slots_in_use() == 0


def test_a_hung_start_releases_its_permit(
    pool: worker_module.WarmPool, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("CHAT_WORKER_READY_S", "0.2")
    _ScriptedWorker.alive_after = True
    _ScriptedWorker.script = [[], []]
    with pytest.raises(worker_module.ChatWorkerStartError):
        pool.acquire()
    assert pool.slots_in_use() == 0
    assert all(not w.is_alive() for w in _ScriptedWorker.spawned)
