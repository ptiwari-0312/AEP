"""Shared exception hierarchy and HTTP error mapping.

docs/architecture/09-engineering-standards.md §6: a single exception hierarchy, with one
mapping point from exception type to HTTP status/Problem-Details `type` URI — `api/` routers
let `AEPError` subclasses propagate here rather than catching them locally.

docs/architecture/04-api-design.md §0.6: the RFC 7807 Problem Details response shape.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AEPError(Exception):
    """Base class for every domain error raised by a backend module."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or message


class AEPRetryableError(AEPError):
    """A transient failure a caller may reasonably retry."""


class AEPTerminalError(AEPError):
    """A deterministic failure retrying will not resolve."""


class UnauthorizedError(AEPTerminalError):
    """Maps to 401 — missing/invalid/expired credentials. Raised by `core/security.py` rather
    than FastAPI's raw `HTTPException`, so an auth failure's response body stays RFC 7807
    shaped like every other error in the API (docs/architecture/04-api-design.md §0.6)."""


class ForbiddenError(AEPTerminalError):
    """Maps to 403 — valid credentials, insufficient role."""


class NotFoundError(AEPTerminalError):
    """Maps to 404 — the resource doesn't exist or the caller lacks visibility into it."""


class ConflictError(AEPTerminalError):
    """Maps to 409 — e.g. an illegal state transition or a unique-constraint violation."""


class ValidationFailedError(AEPTerminalError):
    """Maps to 422; carries per-field errors for the response body's `errors[]`."""

    def __init__(self, message: str, *, errors: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.errors = errors


_STATUS_BY_ERROR_TYPE: dict[type[AEPError], int] = {
    ValidationFailedError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ConflictError: status.HTTP_409_CONFLICT,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    UnauthorizedError: status.HTTP_401_UNAUTHORIZED,
}


def _status_for(error: AEPError) -> int:
    for error_type, http_status in _STATUS_BY_ERROR_TYPE.items():
        if isinstance(error, error_type):
            return http_status
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _problem_type_uri(error: AEPError) -> str:
    return f"https://aep.dev/errors/{type(error).__name__}"


async def aep_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's handler signature requires `Exception`; this is registered only for `AEPError`
    # via register_exception_handlers(), so the narrowing always holds at runtime.
    assert isinstance(exc, AEPError)
    http_status = _status_for(exc)
    body: dict[str, object] = {
        "type": _problem_type_uri(exc),
        "title": type(exc).__name__,
        "status": http_status,
        "detail": exc.detail,
        "instance": request.url.path,
    }
    if isinstance(exc, ValidationFailedError):
        body["errors"] = exc.errors
    return JSONResponse(status_code=http_status, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AEPError, aep_error_handler)
