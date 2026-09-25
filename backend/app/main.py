"""FastAPI application.

Deployed as a Vercel serverless function, so there is no startup work that
assumes a long-lived process: no warm caches, no background tasks, no
connections held open between requests.
"""

from __future__ import annotations

import json
import logging
import time
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
from app.core.messages import readable

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

# Every request here makes a few round trips to a database in another region,
# so a second or two is ordinary. Past this, something waited on something,
# and the log should say which route it was.
_SLOW_SECONDS = 5.0


def _request_id(request: Request) -> str:
    """One id per request, made once and shared by everything that answers
    it, so what somebody reads off their screen finds the line in the log."""
    found = getattr(request.state, "request_id", None)
    if found is None:
        found = str(uuid.uuid4())
        request.state.request_id = found
    return str(found)


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
    request_id = _request_id(request)
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id

    took = time.perf_counter() - started
    if took > _SLOW_SECONDS:
        logger.warning(
            "slow request: %s %s answered %s after %.1fs",
            request.method,
            request.url.path,
            response.status_code,
            took,
        )

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


_CHANGES = {"POST", "PUT", "PATCH", "DELETE"}

# Called by Razorpay's servers, which send no Origin and are proven by the
# signature on the body instead.
_ORIGINLESS = ("/api/v1/pay/webhook/razorpay",)

_HARDENING = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


@app.middleware("http")
async def guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuses a change sent from another site's page, and sets the headers
    every answer carries.

    A browser always says where a request came from when it sends one that
    changes something. Session cookies are SameSite=Lax, which already keeps
    them off another site's form posts; this closes the rest, including a
    sibling subdomain that Lax would count as the same site. A request with
    no Origin at all is not from a browser page, and has to carry a session
    or a signature on its own merits.
    """
    origin = request.headers.get("origin")
    if (
        origin is not None
        and request.method in _CHANGES
        and not request.url.path.startswith(_ORIGINLESS)
        and origin.lower() not in settings.origins
    ):
        logger.warning("refused a %s from origin %s", request.method, origin[:100])
        response: Response = _error(
            403,
            "ORIGIN_REFUSED",
            "That request came from a page this application does not trust.",
        )
    else:
        response = await call_next(request)

    for header, value in _HARDENING.items():
        response.headers.setdefault(header, value)
    if settings.environment in {"preview", "production"}:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    # Records of real people should not sit in a shared machine's cache, or
    # in anything between the clinic and the API.
    response.headers.setdefault("Cache-Control", "no-store")
    if response.headers.get("content-type", "").startswith("application/json"):
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
    return response


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    extra: dict[str, Any] = {}
    if isinstance(exc, ValidationFailed):
        extra["fields"] = exc.fields
    if isinstance(exc, AccountLocked | RateLimited):
        extra["retry_after_seconds"] = exc.retry_after_seconds
    # Carried by anything that needs the caller to choose before retrying:
    # which clinic they meant, or whether the record they are about to create
    # is the person already on one of these rows.
    for carried in ("choices", "candidates"):
        value = getattr(exc, carried, None)
        if value:
            extra[carried] = value

    response = _error(exc.status, exc.code, exc.message, **extra)
    if isinstance(exc, AccountLocked | RateLimited):
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields: dict[str, str] = {}
    for item in exc.errors():
        location = [str(part) for part in item["loc"] if part not in ("body", "query", "path")]
        # Said the way the form should say it, rather than the way the schema
        # describes itself. A person at a desk is the audience here.
        fields[".".join(location) or "body"] = readable(dict(item))
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
    request_id = _request_id(request)
    logger.exception(
        "unhandled error on %s %s, request %s", request.method, request.url.path, request_id
    )
    response = _error(
        500,
        "INTERNAL_ERROR",
        "Something went wrong on our side.",
        request_id=request_id,
    )
    response.headers["X-Request-Id"] = request_id
    return response


app.include_router(v1)
