"""Application errors and the codes the frontend maps to copy."""

from __future__ import annotations


class AppError(Exception):
    """Base for anything we raise deliberately."""

    code: str = "INTERNAL_ERROR"
    status: int = 500
    message: str = "Something went wrong."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class NotFound(AppError):
    code = "NOT_FOUND"
    status = 404
    message = "That record could not be found."


class PermissionDenied(AppError):
    code = "INSUFFICIENT_PERMISSIONS"
    status = 403
    message = "You do not have permission to do that."


class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    status = 422
    message = "Some fields need attention."

    def __init__(self, fields: dict[str, str], message: str | None = None) -> None:
        super().__init__(message)
        self.fields = fields


class ServiceUnavailable(AppError):
    code = "SERVICE_UNAVAILABLE"
    status = 503
    message = "A service this depends on is not responding."


class InvalidCredentials(AppError):
    code = "INVALID_CREDENTIALS"
    status = 401
    # Deliberately says nothing about which half was wrong, so the response
    # cannot be used to discover which addresses have accounts.
    message = "That email and password do not match."


class SessionExpired(AppError):
    code = "SESSION_EXPIRED"
    status = 401
    message = "Your session has ended. Sign in again."


class TokenExpired(AppError):
    code = "TOKEN_EXPIRED"
    status = 400
    message = "That link has expired. Ask for a new one."


class TokenInvalid(AppError):
    code = "TOKEN_INVALID"
    status = 400
    message = "That link is not valid. It may already have been used."


class AccountLocked(AppError):
    code = "ACCOUNT_LOCKED"
    status = 423
    message = "Too many failed attempts. Try again in a few minutes."

    def __init__(self, retry_after_seconds: int, message: str | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class EmailNotVerified(AppError):
    code = "EMAIL_NOT_VERIFIED"
    status = 403
    message = "Confirm your email address before signing in."


class RateLimited(AppError):
    code = "RATE_LIMITED"
    status = 429
    message = "Too many requests. Wait a moment and try again."

    def __init__(self, retry_after_seconds: int, message: str | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AlreadyExists(AppError):
    code = "ALREADY_EXISTS"
    status = 409
    message = "That already exists."


class AccountSuspended(AppError):
    code = "ACCOUNT_SUSPENDED"
    status = 403
    message = "This account has been suspended. Ask an administrator to restore it."
