# SPDX-License-Identifier: Apache-2.0

"""``POST /chat/completions``: asking for, and resuming from, a clarification.

The endpoint is called directly with the conversation store, the pool and the
model replaced by fakes, so what is under test is the routing: when the run may
ask, and what a request that answers is turned into.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from auto_ontology.retrieval.text_to_sql.clarification import (
    Clarification,
    ClarificationOption,
)
from auto_ontology.server.chat import clarification as cl
from auto_ontology.server.chat import router
from auto_ontology.server.chat.conversation_dal import (
    ConversationTurn,
    PreparedConversation,
)
from auto_ontology.server.chat.helpers import ChatRequest

ORIGINAL = "How many VIP customers do we have?"
CONVERSATION = uuid.uuid4()

PENDING = Clarification(
    clarification_id=str(uuid.uuid4()),
    term="VIP customers",
    question="What do you mean by VIP customers?",
    options=[
        ClarificationOption(id="opt-1", label="Above the average payments"),
        ClarificationOption(id="opt-2", label="Top 10% by payments"),
    ],
    original_question=ORIGINAL,
)
EARLIER = ConversationTurn(question="How many films?", response="1000 films.")
CLARIFICATION_TURN = ConversationTurn(question=ORIGINAL, response="What do you mean?")


class _Worker:
    def __init__(self) -> None:
        self.submitted: dict[str, Any] = {}

    def submit(self, question: str, **kwargs: Any) -> None:
        self.submitted = {"question": question, **kwargs}

    def events(self) -> Any:
        return iter(())


class _Harness:
    """Patches everything outside the endpoint and records what reached the worker."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.worker = _Worker()
        self.prepared = PreparedConversation(history=[], analytics_id="a")
        self.prepare_kwargs: dict[str, Any] = {}
        self.prepare_error: Exception | None = None
        self.flag = True
        self.flag_reads = 0
        self.is_answer = True
        self.released: list[str] = []
        self.captured: list[dict[str, Any]] = []
        self.capture_error: Exception | None = None

        pool = SimpleNamespace(
            acquire=lambda cancel=None: self.worker,
            return_alive=lambda w: self.released.append("alive"),
            replace=lambda w: self.released.append("replaced"),
        )
        monkeypatch.setattr(router, "get_pool", lambda: pool)
        monkeypatch.setattr(router, "semantic_layer_calculated", lambda: True)
        monkeypatch.setattr(router, "_subject_token", lambda r: None)
        monkeypatch.setattr(
            router, "resolve_internal_user", lambda r, required=False: "user"
        )
        monkeypatch.setattr(router, "prepare_conversation", self._prepare)
        monkeypatch.setattr(router, "is_clarification_enabled", self._read_flag)
        monkeypatch.setattr(
            router,
            "is_clarification_answer",
            lambda **kw: self.is_answer,
        )
        monkeypatch.setattr(
            router, "create_stateless_analytics", lambda **kw: "stateless"
        )
        monkeypatch.setattr(router, "capture_clarification_answer", self._capture)

    def _prepare(self, **kwargs: Any) -> PreparedConversation:
        self.prepare_kwargs = kwargs
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.prepared

    def _capture(self, **kwargs: Any) -> dict[str, str] | None:
        self.captured.append(kwargs)
        if self.capture_error is not None:
            raise self.capture_error
        return {"id": "k-1", "name": kwargs["term"]}

    def _read_flag(self) -> bool:
        self.flag_reads += 1
        return self.flag

    def post(self, **body: Any) -> dict[str, Any]:
        request = ChatRequest(**body)

        class _Http:
            headers: dict[str, str] = {}

            async def is_disconnected(self) -> bool:
                # Connected: a request whose client vanished between waiting
                # for a slot and submitting is now returned unused (see
                # test_worker_slots.py), which would silently skip the submit.
                return False

        async def run() -> None:
            await router.chat_completions(request, _Http())  # type: ignore[arg-type]
            await asyncio.sleep(0.05)  # let the watchdog and pump settle

        asyncio.run(run())
        return self.worker.submitted


@pytest.fixture(name="harness")
def harness_fixture(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    router._active_slots.clear()
    return _Harness(monkeypatch)


# -- asking ----------------------------------------------------------------


def test_the_run_may_ask_only_for_a_client_that_supports_it_and_when_enabled(
    harness: _Harness,
) -> None:
    sent = harness.post(
        question=ORIGINAL, conversation_id=CONVERSATION, supports_clarification=True
    )

    assert sent["detect_clarification"] is True
    assert sent["question"] == ORIGINAL


def test_a_client_that_did_not_opt_in_never_gets_a_question(harness: _Harness) -> None:
    sent = harness.post(question=ORIGINAL, conversation_id=CONVERSATION)

    assert sent["detect_clarification"] is False
    assert harness.flag_reads == 0


def test_flag_off_means_no_question(harness: _Harness) -> None:
    harness.flag = False

    sent = harness.post(
        question=ORIGINAL, conversation_id=CONVERSATION, supports_clarification=True
    )

    assert sent["detect_clarification"] is False


def test_a_stateless_call_never_gets_a_question(harness: _Harness) -> None:
    sent = harness.post(question=ORIGINAL, supports_clarification=True)

    assert sent["detect_clarification"] is False
    assert harness.flag_reads == 0


# -- resuming --------------------------------------------------------------


def _pending_conversation(harness: _Harness) -> None:
    harness.prepared = PreparedConversation(
        history=[EARLIER, CLARIFICATION_TURN],
        analytics_id="a",
        pending_clarification=PENDING,
    )


def test_an_option_answer_reruns_the_original_question_with_the_definition(
    harness: _Harness,
) -> None:
    _pending_conversation(harness)

    sent = harness.post(
        question="Top 10% by payments",
        conversation_id=CONVERSATION,
        supports_clarification=True,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "option_id": "opt-2",
        },
    )

    assert sent["question"] == ORIGINAL
    assert (
        sent["evidence"] == 'The user defined "VIP customers" as: Top 10% by payments'
    )
    # History stops before the clarification turn, as when it was first asked.
    assert [t["question"] for t in sent["conversation_history"]] == [EARLIER.question]
    # Never asked twice for the same question.
    assert sent["detect_clarification"] is False
    assert harness.prepare_kwargs["clarification"].option_id == "opt-2"


def test_existing_evidence_is_kept_next_to_the_definition(harness: _Harness) -> None:
    _pending_conversation(harness)

    sent = harness.post(
        question="over 100",
        evidence="Amounts are in euros",
        conversation_id=CONVERSATION,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "text": "over 100",
        },
    )

    assert sent["evidence"] == (
        'Amounts are in euros\nThe user defined "VIP customers" as: over 100'
    )


def test_a_plain_free_text_message_is_the_answer(harness: _Harness) -> None:
    _pending_conversation(harness)

    sent = harness.post(question="the top ten percent", conversation_id=CONVERSATION)

    assert sent["question"] == ORIGINAL
    assert "the top ten percent" in sent["evidence"]
    assert sent["detect_clarification"] is False


def test_a_free_text_message_that_is_a_new_question_runs_as_one(
    harness: _Harness,
) -> None:
    _pending_conversation(harness)
    harness.is_answer = False

    sent = harness.post(
        question="How many stores are there?",
        conversation_id=CONVERSATION,
        supports_clarification=True,
    )

    assert sent["question"] == "How many stores are there?"
    assert sent["evidence"] is None
    assert len(sent["conversation_history"]) == 2
    assert sent["detect_clarification"] is True


def test_a_resume_still_works_when_the_flag_has_since_been_turned_off(
    harness: _Harness,
) -> None:
    """A question already on screen must not be stranded by switching the flag."""
    _pending_conversation(harness)
    harness.flag = False

    sent = harness.post(
        question="Top 10%",
        conversation_id=CONVERSATION,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "option_id": "opt-1",
        },
    )

    assert sent["question"] == ORIGINAL


# -- refusals --------------------------------------------------------------


def test_a_stale_or_foreign_id_is_a_422_and_frees_the_slot(harness: _Harness) -> None:
    harness.prepare_error = cl.ClarificationStateError("no longer pending")

    with pytest.raises(HTTPException) as caught:
        harness.post(
            question="x",
            conversation_id=CONVERSATION,
            clarification={"clarification_id": str(uuid.uuid4()), "text": "x"},
        )

    assert caught.value.status_code == 422
    assert harness.worker.submitted == {}
    assert router._active_slots == {}


def test_an_answer_without_a_conversation_is_a_422(harness: _Harness) -> None:
    with pytest.raises(HTTPException) as caught:
        harness.post(
            question="x",
            clarification={"clarification_id": str(uuid.uuid4()), "text": "x"},
        )

    assert caught.value.status_code == 422


# -- learning a term from the answer ------------------------------------------


def _wait_for(predicate: Any) -> None:
    import time

    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_an_option_answer_is_captured_once_with_who_and_when(
    harness: _Harness,
) -> None:
    asked = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
    harness.prepared = PreparedConversation(
        history=[EARLIER, CLARIFICATION_TURN],
        analytics_id="a",
        pending_clarification=PENDING,
        pending_asked_at=asked,
    )

    sent = harness.post(
        question="Top 10% by payments",
        conversation_id=CONVERSATION,
        target_db=None,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "option_id": "opt-2",
        },
    )
    _wait_for(lambda: harness.captured)

    assert len(harness.captured) == 1
    captured = harness.captured[0]
    assert captured["user_id"] == "user"
    assert captured["conversation_id"] == CONVERSATION
    assert captured["clarification_id"] == PENDING.clarification_id
    assert captured["term"] == "VIP customers"
    assert captured["definition"] == "Top 10% by payments"
    assert captured["option_id"] == "opt-2"
    assert captured["asked_at"] == asked
    # What the model receives is exactly what it was before this slice.
    assert (
        sent["evidence"] == 'The user defined "VIP customers" as: Top 10% by payments'
    )


def test_a_free_text_answer_is_captured_without_an_option(harness: _Harness) -> None:
    _pending_conversation(harness)

    harness.post(
        question="the top ten percent",
        conversation_id=CONVERSATION,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "text": "the top ten percent",
        },
    )
    _wait_for(lambda: harness.captured)

    assert harness.captured[0]["option_id"] is None
    assert harness.captured[0]["definition"] == "the top ten percent"


def test_a_message_that_is_not_an_answer_captures_nothing(harness: _Harness) -> None:
    _pending_conversation(harness)
    harness.is_answer = False

    harness.post(question="How many stores are there?", conversation_id=CONVERSATION)
    import time

    time.sleep(0.1)

    assert harness.captured == []


def test_a_normal_question_captures_nothing(harness: _Harness) -> None:
    harness.post(question=ORIGINAL, conversation_id=CONVERSATION)
    import time

    time.sleep(0.1)

    assert harness.captured == []


def test_a_capture_that_raises_does_not_fail_the_turn(
    harness: _Harness, caplog: pytest.LogCaptureFixture
) -> None:
    _pending_conversation(harness)
    harness.capture_error = RuntimeError("the knowledge store is down")

    sent = harness.post(
        question="Top 10% by payments",
        conversation_id=CONVERSATION,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "option_id": "opt-2",
        },
    )
    _wait_for(lambda: harness.captured)

    # The question still went to the worker and the slot was handed back.
    assert sent["question"] == ORIGINAL
    assert "Learned-term capture failed" in caplog.text
    assert router._active_slots == {}


def test_a_slow_capture_does_not_delay_the_turn(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    _pending_conversation(harness)
    release = threading.Event()

    def slow(**kwargs: Any) -> None:
        release.wait(5)

    monkeypatch.setattr(router, "capture_clarification_answer", slow)
    started = time.monotonic()
    sent = harness.post(
        question="Top 10% by payments",
        conversation_id=CONVERSATION,
        clarification={
            "clarification_id": PENDING.clarification_id,
            "option_id": "opt-2",
        },
    )
    elapsed = time.monotonic() - started
    release.set()

    assert sent["question"] == ORIGINAL
    assert elapsed < 2
