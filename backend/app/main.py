"""FastAPI application.

Deployed as a Vercel serverless function, so there is no startup work that
assumes a long-lived process: no warm caches, no background tasks, no
connections held open between requests.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import router as v1
from app.core.config import get_settings
from app.core.exceptions import AccountLocked, AppError, RateLimited, ValidationFailed

logger = logging.getLogger("opd")

settings = get_settings()
_docs_visible = settings.environment in {"development", "preview"}

app = FastAPI(
    title="OPD Manager",
    version=settings.version,
    docs_url="/api/v1/docs" if _docs_visible else None,
    redoc_url=None,
    openapi_url="/api/v1/openapi.json" if _docs_visible else None,
)

_PASSTHROUGH = ("/docs", "/openapi.json")


def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": code, "message": message, **extra}},
    )


@app.middleware("http")
async def envelope(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Tag every response with a request id, and wrap successful JSON bodies
    as {"success": true, "data": ...} so the client parses one shape."""
    request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id

    if (
        response.status_code >= 400
        or request.url.path.endswith(_PASSTHROUGH)
        or not response.headers.get("content-type", "").startswith("application/json")
    ):
        return response

    # Starlette hands middleware its own private response class, which carries
    # body_iterator but does not subclass StreamingResponse. Ask for the
    # attribute rather than the type.
    chunks: AsyncIterator[bytes | str] | None = getattr(response, "body_iterator", None)
    if chunks is None:
        return response

    body = b""
    async for chunk in chunks:
        body += chunk if isinstance(chunk, bytes) else str(chunk).encode()

    try:
        payload = json.loads(body)
    except ValueError:
        logger.error("route returned a body that is not valid json: %s", request.url.path)
        return _error(500, "INTERNAL_ERROR", "Something went wrong on our side.")

    already_wrapped = isinstance(payload, dict) and "success" in payload
    wrapped = payload if already_wrapped else {"success": True, "data": payload}

    # Rebuilding the response drops everything the handler set on it, so the
    # original headers are carried across. Set-Cookie lives here, and losing
    # it means a sign-in that reports success without starting a session.
    # Content-Length is deliberately left behind: the body just changed size.
    carried = [
        (key, value)
        for key, value in response.headers.raw
        if key.lower() not in (b"content-length", b"content-type")
    ]

    rebuilt = JSONResponse(status_code=response.status_code, content=wrapped)
    for key, value in carried:
        rebuilt.raw_headers.append((key, value))
    return rebuilt


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    extra: dict[str, Any] = {}
    if isinstance(exc, ValidationFailed):
        extra["fields"] = exc.fields
    if isinstance(exc, AccountLocked | RateLimited):
        extra["retry_after_seconds"] = exc.retry_after_seconds
    # Carried by anything that needs the caller to choose before retrying.
    choices = getattr(exc, "choices", None)
    if choices:
        extra["choices"] = choices

    response = _error(exc.status, exc.code, exc.message, **extra)
    if isinstance(exc, AccountLocked | RateLimited):
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields: dict[str, str] = {}
    for item in exc.errors():
        location = [str(part) for part in item["loc"] if part not in ("body", "query", "path")]
        fields[".".join(location) or "body"] = item["msg"]
    return _error(422, "VALIDATION_ERROR", "Some fields need attention.", fields=fields)


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette raises these for unmatched routes and unsupported methods.
    Without this they escape as {"detail": ...} and break the one-shape rule."""
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "SESSION_EXPIRED"}
    messages = {
        404: "That page could not be found.",
        405: "That action is not allowed here.",
        401: "Your session has ended. Sign in again.",
    }
    return _error(
        exc.status_code,
        codes.get(exc.status_code, "REQUEST_FAILED"),
        messages.get(exc.status_code, "The request could not be completed."),
    )


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return _error(500, "INTERNAL_ERROR", "Something went wrong on our side.")


app.include_router(v1)
