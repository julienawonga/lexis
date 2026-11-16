# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""One shape for an error nobody planned for.

Routes raise ``HTTPException`` for what they expect, and those already answer
``{"detail": ...}``. Anything else used to leave as Starlette's plain-text
``Internal Server Error``: not JSON, so the web app showed a status code, and
nothing tied what the user saw to the traceback in the logs.

The handler answers in the same ``detail`` shape and adds an ``error_id`` that
is also on the log line, so a screenshot is enough to find the traceback. The
exception's own text stays in the logs: it can quote SQL, a host name or a
value from a customer's data.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

INTERNAL_ERROR_DETAIL = "Internal server error"


def unhandled_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Log *exc* under a fresh id and answer 500 with that id."""
    error_id = uuid.uuid4().hex[:12]
    logger.error(
        "Unhandled error %s on %s %s",
        error_id,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": INTERNAL_ERROR_DETAIL, "error_id": error_id},
    )


def install_error_handler(app: FastAPI) -> None:
    """Register the handler on *app*. Plain ``def``: it does no async I/O."""
    app.add_exception_handler(Exception, unhandled_error_response)
