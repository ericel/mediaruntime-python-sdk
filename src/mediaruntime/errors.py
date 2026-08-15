from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class MediaRuntimeError(Exception):
    """Base class for every SDK error."""


class MediaRuntimeAPIError(MediaRuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int,
        details: Any = None,
        field: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.details = details
        self.field = field
        self.headers = dict(headers or {})


class AuthenticationError(MediaRuntimeAPIError):
    pass


class PermissionDeniedError(MediaRuntimeAPIError):
    pass


class NotFoundError(MediaRuntimeAPIError):
    pass


class RateLimitError(MediaRuntimeAPIError):
    pass


class ValidationError(MediaRuntimeAPIError):
    pass


class IdempotencyInProgressError(MediaRuntimeAPIError):
    pass


class IdempotencyConflictError(ValidationError):
    pass


class MediaRuntimeConnectionError(MediaRuntimeError):
    pass


class MediaRuntimeTimeoutError(MediaRuntimeConnectionError):
    pass


class JobWaitTimeoutError(MediaRuntimeError):
    def __init__(self, timeout: float, last_job: Any = None) -> None:
        super().__init__(f"Job did not reach a terminal state within {timeout:g} seconds")
        self.timeout = timeout
        self.last_job = last_job


class WebhookVerificationError(MediaRuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
