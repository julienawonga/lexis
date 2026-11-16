# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""The chat readiness checks, with the gateway and the stores replaced."""

from __future__ import annotations

import pytest

from auto_ontology.semantic.index_health import SemanticIndexHealth
from auto_ontology.server.health import chat_readiness as cr

OK = {"status": "ok"}


def _fail() -> dict[str, str]:
    raise AssertionError("must not be called")


def test_model_config_names_the_missing_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("API_KEY", "ENDPOINT", "MODEL"):
        for prefix in ("DEFAULT_MODELS", "REASONING", "NON_REASONING", "EMBED"):
            monkeypatch.delenv(f"{prefix}_{name}", raising=False)
    for legacy in ("API_KEY", "BASE_URL", "MODEL_NAME"):
        monkeypatch.delenv(legacy, raising=False)

    result = cr.check_model_config()

    assert result["status"] == "error"
    assert "DEFAULT_MODELS_ENDPOINT" in result["detail"]


def test_model_config_passes_on_the_default_triplet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_MODELS_API_KEY", "k")
    monkeypatch.setenv("DEFAULT_MODELS_ENDPOINT", "http://gateway/v1")
    monkeypatch.setenv("DEFAULT_MODELS_MODEL", "m")

    assert cr.check_model_config() == OK


def test_semantic_index_reports_empty_and_partial_databases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cr,
        "check_semantic_indexes",
        lambda: [
            SemanticIndexHealth("full", expected=10, indexed=10),
            SemanticIndexHealth("partial", expected=10, indexed=4),
            SemanticIndexHealth("empty", expected=0, indexed=0),
        ],
    )

    result = cr.check_semantic_index()

    assert result["status"] == "error"
    assert "no ontology compiled for: empty" in result["detail"]
    assert "index incomplete for: partial" in result["detail"]
    assert "full" not in result["detail"]


def test_semantic_index_passes_when_every_database_is_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cr,
        "check_semantic_indexes",
        lambda: [SemanticIndexHealth("a", expected=3, indexed=3)],
    )

    assert cr.check_semantic_index() == {"status": "ok", "databases": 1}


def test_semantic_index_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> list[SemanticIndexHealth]:
        raise RuntimeError("vector store down")

    monkeypatch.setattr(cr, "check_semantic_indexes", boom)

    assert cr.check_semantic_index() == {
        "status": "error",
        "detail": "vector store down",
    }


def test_no_registered_database_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cr, "check_semantic_indexes", lambda: [])

    assert cr.check_semantic_index()["status"] == "error"


def test_embedding_probe_catches_a_width_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cr, "get_embed_params", lambda: object())
    monkeypatch.setattr(cr, "embed_texts", lambda *a, **k: [[0.0] * 768])
    monkeypatch.setattr(cr, "embed_dimensions", lambda: 2048)

    result = cr.probe_embedding()

    assert result["status"] == "error"
    assert "768" in result["detail"] and "2048" in result["detail"]


def test_embedding_probe_reports_the_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("401 invalid api key")

    monkeypatch.setattr(cr, "get_embed_params", lambda: object())
    monkeypatch.setattr(cr, "embed_texts", refuse)

    assert cr.probe_embedding() == {"status": "error", "detail": "401 invalid api key"}


def test_without_probe_no_gateway_call_is_made_and_skipped_is_not_ok() -> None:
    ready, body = cr.chat_readiness(
        probe=False,
        checks={"model_config": lambda: OK, "semantic_index": lambda: OK},
        probes={"embedding": _fail, "chat_model": _fail},
    )

    assert ready is True
    assert body["status"] == "ok"
    assert body["embedding"]["status"] == "skipped"
    assert body["chat_model"]["status"] == "skipped"


def test_a_failed_probe_makes_chat_not_ready() -> None:
    ready, body = cr.chat_readiness(
        probe=True,
        checks={"model_config": lambda: OK, "semantic_index": lambda: OK},
        probes={
            "embedding": lambda: {"status": "error", "detail": "401"},
            "chat_model": lambda: OK,
        },
    )

    assert ready is False
    assert body["status"] == "degraded"
    assert body["chat_model"] == OK


def test_probes_are_not_attempted_on_incomplete_settings() -> None:
    ready, body = cr.chat_readiness(
        probe=True,
        checks={
            "model_config": lambda: {"status": "error", "detail": "no key"},
            "semantic_index": lambda: OK,
        },
        probes={"embedding": _fail, "chat_model": _fail},
    )

    assert ready is False
    assert body["embedding"]["status"] == "skipped"
