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
