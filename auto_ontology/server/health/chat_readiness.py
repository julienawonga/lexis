# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Can the chat answer a question? The checks ``/health`` does not make.

``/health`` proves Postgres and the schema. Chat needs three more things, and
each has failed here while ``/health`` stayed green: model settings that
resolve, a model gateway that accepts them, and a semantic index that is not
empty. With any of them missing the API answers healthy and the first question
fails, or worse, is answered from the raw schema.

Kept out of the polled readiness route on purpose: the two probes call the
model gateway, and a paid call every few seconds per container is not a health
check. They run only when asked for.

No check raises: a readiness answer has to say what is wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from auto_ontology.semantic.index_health import check_semantic_indexes
from auto_ontology.utils.embedding import embed_texts, get_embed_params
from auto_ontology.utils.llm_invoke import get_llm_client
from auto_ontology.utils.model_config import embed_dimensions, require

_MODEL_ROLES = ("REASONING", "NON_REASONING", "EMBED")
_MODEL_FIELDS = ("ENDPOINT", "API_KEY", "MODEL")
_PROBE_TIMEOUT_S = 20.0
_PROBE_TEXT = "health check"
_DETAIL_CHARS = 300

Check = dict[str, Any]


def _error(exc: Exception) -> Check:
    return {
        "status": "error",
        "detail": (str(exc) or type(exc).__name__)[:_DETAIL_CHARS],
    }


def check_model_config() -> Check:
    """Every model role has an endpoint, a key and a model name. No network."""
    problems: list[str] = []
    for role in _MODEL_ROLES:
        for field in _MODEL_FIELDS:
            try:
                require(role, field)
            except Exception as exc:
                problems.append(str(exc))
    if problems:
        return {"status": "error", "detail": "; ".join(problems)[:_DETAIL_CHARS]}
    return {"status": "ok"}


def check_semantic_index() -> Check:
    """The ontology of every database is present in the vector index.

    An empty or partial index does not fail a question: retrieval finds
    nothing and the answer is written from the raw schema, which looks like an
    answer. That is why it is reported here.
    """
    try:
        indexes = check_semantic_indexes()
    except Exception as exc:
        return _error(exc)
    if not indexes:
        return {"status": "error", "detail": "no database is registered"}
    empty = sorted(i.database_name for i in indexes if i.expected == 0)
    partial = sorted(i.database_name for i in indexes if i.expected and i.missing > 0)
    if not empty and not partial:
        return {"status": "ok", "databases": len(indexes)}
    parts = []
    if empty:
        parts.append(f"no ontology compiled for: {', '.join(empty)}")
    if partial:
        parts.append(f"index incomplete for: {', '.join(partial)}")
    return {
        "status": "error",
        "detail": "; ".join(parts)[:_DETAIL_CHARS],
        "databases": len(indexes),
    }


def probe_embedding() -> Check:
    """One embedding call, and its width against the configured width."""
    try:
        vectors = embed_texts(
            [_PROBE_TEXT],
            get_embed_params(),
            "query",
            timeout=_PROBE_TIMEOUT_S,
            retries=0,
        )
        vector = vectors[0]
        if not vector:
            return {"status": "error", "detail": "the endpoint returned no vector"}
        expected = embed_dimensions()
        if len(vector) != expected:
            return {
                "status": "error",
                "detail": (
                    f"the model returned {len(vector)} values, the store expects "
                    f"{expected}: set EMBED_DIMENSIONS and re-ingest"
                ),
            }
        return {"status": "ok", "dimensions": len(vector)}
    except Exception as exc:
        return _error(exc)


def probe_chat_model() -> Check:
    """One short completion on the main model. The reply's text is not judged."""
    try:
        get_llm_client(max_tokens=256).invoke("Reply with the word OK.")
        return {"status": "ok"}
    except Exception as exc:
        return _error(exc)


def chat_readiness(
    *,
    probe: bool,
    checks: dict[str, Callable[[], Check]] | None = None,
    probes: dict[str, Callable[[], Check]] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Run the checks; with *probe*, also the two calls to the model gateway.

    Returns ``(ready, body)``. Without *probe* the model entries say
    ``skipped`` and do not count against readiness: unchecked is not broken,
    and it is not ``ok`` either.
    """
    checks = checks or {
        "model_config": check_model_config,
        "semantic_index": check_semantic_index,
    }
    probes = probes or {
        "embedding": probe_embedding,
        "chat_model": probe_chat_model,
    }
    body: dict[str, Any] = {name: run() for name, run in checks.items()}
    config_ok = body.get("model_config", {}).get("status") == "ok"
    for name, run in probes.items():
        if not probe:
            body[name] = {"status": "skipped", "detail": "pass probe=true to call it"}
        elif not config_ok:
            body[name] = {
                "status": "skipped",
                "detail": "model settings are incomplete",
            }
        else:
            body[name] = run()
    ready = all(entry["status"] != "error" for entry in body.values())
    return ready, {"status": "ok" if ready else "degraded", **body}
