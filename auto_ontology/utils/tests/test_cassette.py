# SPDX-License-Identifier: Apache-2.0

"""The cassette layer: record, replay, normalization, misses and secrets.

The "model" here is an ``httpx.MockTransport`` answering in the OpenAI shapes,
reached through the real call sites (``ChatOpenAI``, ``embed_texts``, the
rerank request), so a drift in how those build requests shows up as a failure
here and not only in a recorded run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import pytest

from auto_ontology.utils import cassette, embedding, http_limits, rerank
from auto_ontology.utils.cassette import (
    CassetteError,
    CassetteMiss,
    install_cassette,
    normalize_body,
    request_key,
)
from auto_ontology.utils.embedding import EmbedParams, embed_texts
from auto_ontology.utils.llm_invoke import _build_client

FAKE_KEY = "sk-fake-1234567890abcdef"
BASE = "http://fake-model.test/v1"


class FakeModel:
    """A canned OpenAI-shaped server that counts what it receives."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        path = request.url.path
        if path.endswith("/chat/completions"):
            asked = body["messages"][-1]["content"]
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-volatile-id",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": f"echo:{asked}",
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )
        if path.endswith("/embeddings"):
            data = [
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": [float(len(text)), 0.5],
                }
                for i, text in enumerate(body["input"])
            ]
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": data,
                    "model": body["model"],
                    "usage": {},
                },
            )
        if path.endswith("/ranking"):
            return httpx.Response(
                200,
                json={
                    "rankings": [
                        {"index": i, "logit": float(-i)}
                        for i in range(len(body["passages"]))
                    ]
                },
            )
        return httpx.Response(404, json={"error": path})


def _client(model: FakeModel) -> http_limits.GatewayClient:
    return http_limits.GatewayClient(transport=httpx.MockTransport(model))


@pytest.fixture
def fake_model() -> FakeModel:
    return FakeModel()


def _chat(client: httpx.Client, text: str, system: str = "be brief") -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    with mock.patch.object(http_limits, "_client", client):
        llm = _build_client(
            model="test/model",
            api_key=FAKE_KEY,
            base_url=BASE,
            temperature=0.0,
            max_tokens=64,
        )
    reply = llm.invoke([SystemMessage(content=system), HumanMessage(content=text)])
    return str(reply.content)


@pytest.fixture(autouse=True)
def _fresh_shared_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv(cassette.ENV_MODE, raising=False)
    monkeypatch.delenv(cassette.ENV_DIR, raising=False)
    monkeypatch.setattr(http_limits, "_client", None)
    monkeypatch.setattr(embedding, "_clients", {})
    yield


# --- normalization ----------------------------------------------------------


def _key(body: dict[str, Any]) -> str:
    return request_key(
        "POST", "/v1/chat/completions", normalize_body(json.dumps(body).encode())
    )


def test_the_current_datetime_in_a_prompt_does_not_change_the_hash() -> None:
    """``datetime.now()`` is formatted into the main system prompt."""
    monday = {"messages": [{"content": "Today is 2026-11-16 09:01:02.123456."}]}
    tuesday = {"messages": [{"content": "Today is 2026-11-17 23:59:59.000001."}]}
    iso = {"messages": [{"content": "Today is 2026-11-17T08:00:00Z."}]}
    assert _key(monday) == _key(tuesday) == _key(iso)


def test_a_bare_date_is_data_and_still_counts() -> None:
    assert _key({"q": "orders on 2022-05-24"}) != _key({"q": "orders on 2022-05-25"})


def test_ids_minted_at_ingestion_and_call_identifiers_are_ignored() -> None:
    first = {
        "q": "x 123e4567-e89b-12d3-a456-426614174000",
        "user": "a",
        "request_id": "1",
    }
    second = {
        "q": "x 223e4567-e89b-12d3-a456-426614174999",
        "user": "b",
        "request_id": "2",
    }
    assert _key(first) == _key(second)


def test_field_order_is_irrelevant_but_content_is_not() -> None:
    assert _key({"a": 1, "b": 2}) == _key({"b": 2, "a": 1})
    assert _key({"a": 1}) != _key({"a": 2})
    assert request_key("POST", "/a", {"x": 1}) != request_key("POST", "/b", {"x": 1})


# --- record and replay ------------------------------------------------------


def test_off_by_default_changes_nothing() -> None:
    client = http_limits.shared_http_client()
    assert not isinstance(client._transport, cassette.CassetteTransport)


def test_environment_installs_the_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(cassette.ENV_MODE, "replay")
    monkeypatch.setenv(cassette.ENV_DIR, str(tmp_path))
    client = http_limits.shared_http_client()
    assert isinstance(client._transport, cassette.CassetteTransport)


def test_a_mode_without_a_directory_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cassette.ENV_MODE, "replay")
    with pytest.raises(CassetteError, match=cassette.ENV_DIR):
        http_limits.shared_http_client()


def test_an_unknown_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cassette.ENV_MODE, "tape")
    monkeypatch.setenv(cassette.ENV_DIR, "x")
    with pytest.raises(CassetteError, match="record"):
        http_limits.shared_http_client()


def _embed_params() -> EmbedParams:
    return EmbedParams(model_name="test/embed", embed_invoke_url=BASE, api_key=FAKE_KEY)


def _record_everything(tmp_path: Path, model: FakeModel) -> None:
    recorder = _client(model)
    install_cassette(recorder, cassette.RECORD, tmp_path)
    assert _chat(recorder, "hello") == "echo:hello"
    client = embedding._new_client(_embed_params(), http_client=recorder)
    client.embeddings.create(model="test/embed", input=["abc", "de"])
    response = recorder.post(
        f"{BASE}/ranking",
        json={"model": "m", "query": "q", "passages": [{"text": "a"}, {"text": "b"}]},
        headers={"Authorization": f"Bearer {FAKE_KEY}"},
    )
    assert response.json()["rankings"][1]["logit"] == -1.0


def test_chat_embeddings_and_rerank_replay_without_the_network(
    tmp_path: Path, fake_model: FakeModel
) -> None:
    _record_everything(tmp_path, fake_model)
    assert len(fake_model.requests) == 3
    assert len(list(tmp_path.glob("*.json"))) == 3

    offline = FakeModel()
    replayer = http_limits.GatewayClient(transport=httpx.MockTransport(offline))
    install_cassette(replayer, cassette.REPLAY, tmp_path)

    assert _chat(replayer, "hello") == "echo:hello"
    client = embedding._new_client(_embed_params(), http_client=replayer)
    data = client.embeddings.create(model="test/embed", input=["abc", "de"]).data
    assert [d.embedding for d in data] == [[3.0, 0.5], [2.0, 0.5]]
    ranked = replayer.post(
        f"{BASE}/ranking",
        json={"model": "m", "query": "q", "passages": [{"text": "a"}, {"text": "b"}]},
    )
    assert ranked.json()["rankings"][0]["logit"] == 0.0

    assert offline.requests == [], "replay must never reach the inner transport"


def test_the_real_embed_and_rerank_call_sites_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_model: FakeModel
) -> None:
    """Through ``embed_texts`` and ``rerank._scores`` and the shared client."""
    params = EmbedParams(
        model_name="test/embed",
        embed_invoke_url=BASE,
        api_key=FAKE_KEY,
        extra_fields=False,
    )
    url = f"{BASE}/ranking"

    def call_sites() -> tuple[Any, Any]:
        vectors = embed_texts(["abc", "de"], params, "passage")
        scores = rerank._scores(
            "q", ["a", "b"], url=url, model_name="m", api_key=FAKE_KEY
        )
        return vectors, scores

    recorder = _client(fake_model)
    install_cassette(recorder, cassette.RECORD, tmp_path)
    monkeypatch.setattr(http_limits, "_client", recorder)
    recorded = call_sites()
    assert len(fake_model.requests) == 2

    monkeypatch.setattr(embedding, "_clients", {})
    offline = FakeModel()
    replayer = http_limits.GatewayClient(transport=httpx.MockTransport(offline))
    install_cassette(replayer, cassette.REPLAY, tmp_path)
    monkeypatch.setattr(http_limits, "_client", replayer)
    assert call_sites() == recorded
    assert offline.requests == []


def test_the_same_request_is_replayed_in_recorded_order(
    tmp_path: Path,
) -> None:
    answers = iter(["first", "second"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"a": next(answers)})

    recorder = http_limits.GatewayClient(transport=httpx.MockTransport(handler))
    install_cassette(recorder, cassette.RECORD, tmp_path)
    for _ in range(2):
        recorder.post(f"{BASE}/x", json={"same": True})
    assert len(list(tmp_path.glob("*.json"))) == 1

    replayer = http_limits.GatewayClient(transport=httpx.MockTransport(handler))
    install_cassette(replayer, cassette.REPLAY, tmp_path)
    seen = [
        replayer.post(f"{BASE}/x", json={"same": True}).json()["a"] for _ in range(3)
    ]
    assert seen == ["first", "second", "second"]


def test_a_changed_prompt_is_a_miss_with_the_hash_and_a_diff(
    tmp_path: Path, fake_model: FakeModel
) -> None:
    recorder = _client(fake_model)
    install_cassette(recorder, cassette.RECORD, tmp_path)
    _chat(
        recorder,
        "How many rentals?",
        system="You write SQL. Today is 2026-11-16 10:00:00.",
    )

    replayer = http_limits.GatewayClient(transport=httpx.MockTransport(FakeModel()))
    install_cassette(replayer, cassette.REPLAY, tmp_path)
    # Only the date moved: still a hit.
    assert (
        _chat(
            replayer,
            "How many rentals?",
            system="You write SQL. Today is 2027-01-01 00:00:00.",
        )
        == "echo:How many rentals?"
    )
    # A prompt edit is a miss.
    with pytest.raises(Exception) as caught:
        _chat(replayer, "How many rentals?", system="You write SQL. Be careful.")
    miss = _find_miss(caught.value)
    text = str(miss)
    assert "request hash" in text
    assert "Be careful" in text and "<DATETIME>" in text, text
    assert any(ln.startswith("-") for ln in text.splitlines()), "no diff lines"
    assert any(ln.startswith("+") for ln in text.splitlines()), "no diff lines"


def _find_miss(error: BaseException | None) -> CassetteMiss:
    while error is not None:
        if isinstance(error, CassetteMiss):
            return error
        error = error.__cause__ or error.__context__
    raise AssertionError("no CassetteMiss in the exception chain")


def test_a_miss_with_nothing_recorded_says_so(tmp_path: Path) -> None:
    replayer = http_limits.GatewayClient(transport=httpx.MockTransport(FakeModel()))
    install_cassette(replayer, cassette.REPLAY, tmp_path / "empty")
    with pytest.raises(CassetteMiss, match="No stored request"):
        replayer.post(f"{BASE}/chat/completions", json={"a": 1})


# --- secrets ----------------------------------------------------------------


def test_no_secret_is_ever_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_secret = "env-secret-value-98765432"
    monkeypatch.setenv("SOME_PROVIDER_API_KEY", env_secret)

    def echoing_server(request: httpx.Request) -> httpx.Response:
        # A hostile or careless gateway that echoes the credentials back.
        return httpx.Response(
            200,
            json={
                "echo": request.headers.get("authorization"),
                "env": env_secret,
                "x": request.headers.get("x-api-key"),
            },
            headers={
                "set-cookie": "session=abcdef123456",
                "content-type": "application/json",
            },
        )

    recorder = http_limits.GatewayClient(transport=httpx.MockTransport(echoing_server))
    install_cassette(recorder, cassette.RECORD, tmp_path)
    recorder.post(
        f"{BASE}/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {FAKE_KEY}", "x-api-key": FAKE_KEY},
    )
    _record_everything(tmp_path, FakeModel())

    files = list(tmp_path.glob("*.json"))
    assert files
    for file in files:
        text = file.read_text(encoding="utf-8")
        for secret in (FAKE_KEY, env_secret, "abcdef123456"):
            assert secret not in text, f"{secret} leaked into {file.name}"
        assert "authorization" not in text.lower()
        assert "set-cookie" not in text.lower()
    echoed = [f for f in files if cassette.REDACTED in f.read_text(encoding="utf-8")]
    assert echoed, "the echoed credentials should have been redacted, not dropped"
