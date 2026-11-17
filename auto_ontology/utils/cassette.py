# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Record and replay the model HTTP calls ("cassettes").

Every chat, embedding and rerank request goes through ``shared_http_client()``
(``auto_ontology/utils/http_limits.py``). When ``LLM_CASSETTE_MODE`` is set, that
client's transport is wrapped so the calls can be stored once against a real
model and replayed later with no model, no network and no secret. With the
variable unset (the default) nothing is wrapped and nothing changes.

``LLM_CASSETTE_MODE``
    ``record``: forward each request to the real endpoint and store request and
    response. ``replay``: never touch the network; answer from the stored files
    and fail loudly on a request that was not recorded.
``LLM_CASSETTE_DIR``
    The directory holding the cassette files (required with a mode).

A cassette is one JSON file per request hash, ``<hash>.json``, holding the
normalized request and the list of responses recorded for it (the same request
made twice, for instance a retry, is replayed in the order it was recorded; the
last response then repeats).

What is stored, and what is not
-------------------------------
Request headers are **not stored at all** (so neither ``Authorization`` nor any
``x-api-key`` can leak), and only ``content-type`` is kept from the response. As
a second line of defence the serialized cassette is scanned for every secret the
process knows (the bearer token of the request and the value of any environment
variable whose name contains KEY, TOKEN or SECRET) and each occurrence is
replaced by ``<redacted>``.

How a request is identified (normalization)
-------------------------------------------
The hash covers the method, the URL path (not the host, so a different gateway
URL still replays) and the JSON body normalized as follows, so that a request is
the same request on another day or after another ingestion:

* top-level keys that identify the call instead of describing it are dropped:
  ``user``, ``request_id``, ``trace_id``, ``session_id``;
* inside every string, a date-time (``2026-11-17 10:23:45.123456``,
  ``2026-11-17T10:23:45Z``) becomes ``<DATETIME>``. ``datetime.now()`` is
  formatted into the main system prompt (``retrieval/text_to_sql/main.py``), and
  the catalog writes ``pulled`` / ``last_seen`` timestamps that can reach a
  prompt; a bare date (``2022-05-24``) is left alone because it is usually
  data;
* inside every string, a UUID becomes ``<UUID>`` (ids minted at ingestion);
* keys are sorted, so field order never matters.

Everything else is part of the identity: a changed prompt, retrieved table,
model name or parameter is a different hash, which is the point. A miss raises
:class:`CassetteMiss` with the hash and a diff against the nearest stored body;
the maintainer re-records on purpose, like a golden file.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ENV_MODE = "LLM_CASSETTE_MODE"
ENV_DIR = "LLM_CASSETTE_DIR"
RECORD = "record"
REPLAY = "replay"

REDACTED = "<redacted>"
DROPPED_KEYS = frozenset({"user", "request_id", "trace_id", "session_id"})
KEPT_RESPONSE_HEADERS = ("content-type",)
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET", re.IGNORECASE)
_MIN_SECRET_LEN = 8

_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class CassetteError(RuntimeError):
    """Misconfiguration of the cassette layer."""


class CassetteMiss(RuntimeError):
    """Replay found no recorded response for a request."""


def _normalize_text(text: str) -> str:
    return _UUID.sub("<UUID>", _DATETIME.sub("<DATETIME>", text))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    return value


def normalize_body(body: bytes) -> Any:
    """The normalized form of a request body (parsed JSON, or text for non-JSON)."""
    try:
        parsed = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        return _normalize_text(body.decode("utf-8", errors="replace"))
    if isinstance(parsed, dict):
        parsed = {k: v for k, v in parsed.items() if k not in DROPPED_KEYS}
    return _normalize_value(parsed)


def _canonical(body: Any) -> str:
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_key(method: str, path: str, normalized_body: Any) -> str:
    """The hash that identifies a request."""
    material = f"{method.upper()}\n{path}\n{_canonical(normalized_body)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def known_secrets(request: httpx.Request | None = None) -> list[str]:
    """Every secret the process knows, longest first."""
    found: set[str] = set()
    if request is not None:
        auth = request.headers.get("authorization", "")
        token = auth.split(None, 1)[-1] if auth else ""
        if len(token) >= _MIN_SECRET_LEN:
            found.add(token)
        for header in ("x-api-key", "api-key"):
            value = request.headers.get(header, "")
            if len(value) >= _MIN_SECRET_LEN:
                found.add(value)
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name) and len(value) >= _MIN_SECRET_LEN:
            found.add(value)
    return sorted(found, key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


class CassetteStore:
    """The directory of ``<hash>.json`` files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._written: set[str] = set()
        self._served: dict[str, int] = {}

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def write(self, key: str, entry: dict[str, Any], secrets: list[str]) -> None:
        """Store *entry* for *key*; the first write of a run replaces the file."""
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(key)
            responses: list[Any] = []
            if key in self._written and path.is_file():
                responses = json.loads(path.read_text(encoding="utf-8"))["responses"]
            responses.append(entry["response"])
            document = {"request": entry["request"], "responses": responses}
            text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True)
            path.write_text(
                redact(text, secrets) + "\n", encoding="utf-8", newline="\n"
            )
            self._written.add(key)

    def read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def next_response(self, key: str, document: dict[str, Any]) -> dict[str, Any]:
        responses = document["responses"]
        with self._lock:
            index = self._served.get(key, 0)
            self._served[key] = index + 1
        return responses[min(index, len(responses) - 1)]

    def stored_requests(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        found = []
        for file in sorted(self.directory.glob("*.json")):
            try:
                found.append(json.loads(file.read_text(encoding="utf-8"))["request"])
            except (ValueError, KeyError):
                continue
        return found


def _pretty(body: Any) -> list[str]:
    return json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False).splitlines()


def miss_message(
    store: CassetteStore, method: str, path: str, body: Any, key: str
) -> str:
    """The failure text of a miss: the hash and a diff against the nearest body."""
    mine = _pretty(body)
    best: tuple[float, dict[str, Any]] | None = None
    for stored in store.stored_requests():
        if stored.get("path") != path:
            continue
        ratio = difflib.SequenceMatcher(
            None,
            "\n".join(_pretty(stored.get("body"))),
            "\n".join(mine),
            autojunk=False,
        ).quick_ratio()
        if best is None or ratio > best[0]:
            best = (ratio, stored)
    head = (
        f"No recorded response for {method} {path} (request hash {key}) in "
        f"{store.directory}. The prompt or request changed since the cassettes "
        "were recorded; if that change is intended, re-record them "
        "(see docs/recorded-evaluation.md)."
    )
    if best is None:
        return head + f" No stored request for {path} exists at all."
    diff = list(
        difflib.unified_diff(
            _pretty(best[1].get("body")),
            mine,
            "nearest recorded request",
            "this request",
            lineterm="",
            n=1,
        )
    )
    shown = diff[:60]
    if len(diff) > len(shown):
        shown.append(f"... {len(diff) - len(shown)} more diff lines")
    return head + "\nDiff against the nearest recorded request:\n" + "\n".join(shown)


class CassetteTransport(httpx.BaseTransport):
    """Wraps *inner* to record its exchanges, or replaces it when replaying."""

    def __init__(
        self,
        inner: httpx.BaseTransport | None,
        mode: str,
        store: CassetteStore,
    ) -> None:
        if mode not in (RECORD, REPLAY):
            raise CassetteError(
                f"{ENV_MODE} must be {RECORD!r} or {REPLAY!r}, not {mode!r}"
            )
        if mode == RECORD and inner is None:
            raise CassetteError("record mode needs a transport to forward to")
        self._inner = inner
        self.mode = mode
        self.store = store

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = normalize_body(request.read())
        path = request.url.path
        key = request_key(request.method, path, body)
        if self.mode == REPLAY:
            return self._replay(request, key, path, body)
        return self._record(request, key, path, body)

    def _replay(
        self, request: httpx.Request, key: str, path: str, body: Any
    ) -> httpx.Response:
        document = self.store.read(key)
        if document is None:
            message = miss_message(self.store, request.method, path, body, key)
            logger.error(message)
            raise CassetteMiss(message)
        stored = self.store.next_response(key, document)
        return httpx.Response(
            stored["status"],
            headers=stored.get("headers", {}),
            content=stored["body"].encode("utf-8"),
            request=request,
        )

    def _record(
        self, request: httpx.Request, key: str, path: str, body: Any
    ) -> httpx.Response:
        assert self._inner is not None
        response = self._inner.handle_request(request)
        try:
            raw = b"".join(response.stream)  # type: ignore[arg-type]
        finally:
            response.close()
        text = raw.decode("utf-8", errors="replace")
        headers = {
            name: response.headers[name]
            for name in KEPT_RESPONSE_HEADERS
            if name in response.headers
        }
        self.store.write(
            key,
            {
                "request": {"method": request.method, "path": path, "body": body},
                "response": {
                    "status": response.status_code,
                    "headers": headers,
                    "body": text,
                },
            },
            known_secrets(request),
        )
        return httpx.Response(
            response.status_code, headers=headers, content=raw, request=request
        )

    def close(self) -> None:
        if self._inner is not None:
            self._inner.close()


def config_from_env() -> tuple[str, Path] | None:
    """``(mode, directory)`` from the environment, or ``None`` when off."""
    mode = os.environ.get(ENV_MODE, "").strip().lower()
    if not mode:
        return None
    if mode not in (RECORD, REPLAY):
        raise CassetteError(
            f"{ENV_MODE} must be {RECORD!r} or {REPLAY!r}, not {mode!r}"
        )
    directory = os.environ.get(ENV_DIR, "").strip()
    if not directory:
        raise CassetteError(
            f"{ENV_MODE}={mode} needs {ENV_DIR} (the cassette directory)"
        )
    return mode, Path(directory)


def install_cassette(
    client: httpx.Client, mode: str, directory: Path
) -> CassetteTransport:
    """Route *client*'s requests through a cassette transport."""
    inner = None if mode == REPLAY else client._transport  # noqa: SLF001
    transport = CassetteTransport(inner, mode, CassetteStore(directory))
    client._transport = transport  # noqa: SLF001
    # Proxy mounts (from HTTP(S)_PROXY) would bypass the default transport.
    mounts: dict[Any, Any] = {}
    for pattern, mounted in client._mounts.items():  # noqa: SLF001
        if mounted is None or mode == REPLAY:
            mounts[pattern] = None if mounted is None else transport
        else:
            mounts[pattern] = CassetteTransport(mounted, mode, transport.store)
    client._mounts = mounts  # noqa: SLF001
    logger.warning("Model HTTP calls are in cassette %s mode (%s).", mode, directory)
    return transport


def install_from_env(client: httpx.Client) -> None:
    """Install the cassette transport when the environment asks for it."""
    config = config_from_env()
    if config is not None:
        install_cassette(client, *config)
