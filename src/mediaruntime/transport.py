from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx

from ._version import VERSION
from .errors import (
    AuthenticationError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    MediaRuntimeAPIError,
    MediaRuntimeConnectionError,
    MediaRuntimeTimeoutError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
)

RetryMode = Literal["safe", "idempotent-submit", "never"]


def _normalized_error(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    return error if isinstance(error, dict) else None


def _message_and_field(payload: Any, status: int) -> tuple[str, str | None]:
    # Normalize canonical envelopes and common framework validation shapes into one exception API.
    normalized = _normalized_error(payload)
    if normalized is not None and isinstance(normalized.get("message"), str):
        normalized_message = str(normalized["message"])
        detail = normalized.get("details")
    elif isinstance(payload, dict):
        normalized_message = ""
        detail = payload.get("detail")
        if detail is None:
            detail = payload.get("message") or payload.get("msg")
    else:
        normalized_message = ""
        detail = payload
    field: str | None = None
    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            item_message = item.get("msg")
            if isinstance(item_message, str):
                messages.append(item_message)
            location = item.get("loc")
            if field is None and isinstance(location, list) and location:
                field = str(location[-1])
        if messages:
            return normalized_message or "; ".join(messages), field
    if isinstance(detail, dict):
        field_value = detail.get("field")
        field = field_value if isinstance(field_value, str) else None
        detail_message = detail.get("message") or detail.get("detail") or detail.get("error")
        if isinstance(detail_message, str):
            return normalized_message or detail_message, field
    if normalized_message:
        return normalized_message, field
    if isinstance(detail, str) and detail:
        return detail, field
    return f"MediaRuntime API request failed with status {status}", field


def _error_for_response(
    response: httpx.Response, payload: Any, operation: str
) -> MediaRuntimeAPIError:
    message, field = _message_and_field(payload, response.status_code)
    normalized = _normalized_error(payload)
    code = (
        str(normalized.get("code"))
        if normalized is not None and isinstance(normalized.get("code"), str)
        else "api_error"
    )
    retryable = bool(normalized.get("retryable")) if normalized is not None else False
    request_id = None
    if normalized is not None and isinstance(normalized.get("request_id"), str):
        request_id = str(normalized["request_id"])
    if request_id is None:
        request_id = response.headers.get("X-Request-Id")
    details = normalized.get("details") if normalized is not None else payload
    error_type: type[MediaRuntimeAPIError]
    if response.status_code == 401:
        error_type = AuthenticationError
    elif response.status_code == 403:
        error_type = PermissionDeniedError
    elif response.status_code == 404:
        error_type = NotFoundError
    elif response.status_code == 429:
        error_type = RateLimitError
    elif code == "idempotency_in_progress" or (
        normalized is None
        and response.status_code == 409
        and operation == "create-job"
        and "idempotency-key" in message.lower()
        and "progress" in message.lower()
    ):
        error_type = IdempotencyInProgressError
    elif code == "idempotency_conflict" or (
        response.status_code == 422
        and operation == "create-job"
        and "idempotency-key" in message.lower()
        and "different" in message.lower()
    ):
        error_type = IdempotencyConflictError
    elif response.status_code in {400, 413, 422}:
        error_type = ValidationError
    else:
        error_type = MediaRuntimeAPIError
    return error_type(
        message,
        status=response.status_code,
        code=code,
        retryable=retryable,
        request_id=request_id,
        details=details,
        response_body=payload,
        field=field,
        headers=dict(response.headers),
    )


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


class Transport:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout: float,
        max_retries: int,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Accept a legacy trailing /v1 while keeping endpoint construction canonical internally.
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/v1"):
            normalized = normalized[:-3]
        if not normalized.startswith(("http://", "https://")):
            raise TypeError("base_url must be an absolute HTTP(S) URL")
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.base_url = normalized
        self.timeout = timeout
        self.max_retries = max_retries
        # API redirects stay disabled so an API key is never forwarded to another origin.
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> None:
        header_delay = (
            _retry_after_seconds(response.headers.get("Retry-After")) if response else None
        )
        # Prefer server backpressure, otherwise use capped exponential backoff with jitter.
        delay = header_delay if header_delay is not None else min(8.0, 0.25 * (2**attempt))
        self._sleep(delay * random.uniform(0.85, 1.15))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
        bearer_token: str | None = None,
        retry: RetryMode = "safe",
        operation: str = "request",
    ) -> Any:
        # Call sites choose retry safety explicitly; mutation is never inferred from HTTP method.
        request_headers = {
            "Accept": "application/json",
            "User-Agent": f"mediaruntime-python/{VERSION}",
        }
        if bearer_token is not None:
            # A scoped Sticker Runtime token replaces API-key authentication. Keeping
            # this choice in the transport prevents either credential leaking together.
            normalized_token = bearer_token.strip()
            if not normalized_token:
                raise AuthenticationError(
                    "A Sticker Runtime client token is required",
                    status=401,
                    code="authentication_error",
                )
            request_headers["Authorization"] = f"Bearer {normalized_token}"
        elif authenticated:
            if not self.api_key:
                raise AuthenticationError(
                    "A MediaRuntime API key is required",
                    status=401,
                    code="authentication_error",
                )
            request_headers["X-API-Key"] = self.api_key
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        url = f"{self.base_url}/v1/{path.lstrip('/')}"
        attempt = 0
        while True:
            try:
                response = self.client.request(
                    method,
                    url,
                    json=dict(body) if body is not None else None,
                    params={
                        key: value for key, value in (query or {}).items() if value is not None
                    },
                    headers=request_headers,
                    timeout=self.timeout,
                    follow_redirects=False,
                )
            except httpx.TimeoutException as error:
                if retry != "never" and attempt < self.max_retries:
                    self._delay(attempt)
                    attempt += 1
                    continue
                raise MediaRuntimeTimeoutError("MediaRuntime request timed out") from error
            except httpx.RequestError as error:
                if retry != "never" and attempt < self.max_retries:
                    self._delay(attempt)
                    attempt += 1
                    continue
                raise MediaRuntimeConnectionError("Could not reach MediaRuntime") from error

            if (
                (response.status_code == 429 or response.status_code >= 500)
                and retry != "never"
                and attempt < self.max_retries
            ):
                self._delay(attempt, response)
                attempt += 1
                continue
            if response.is_success:
                if response.status_code == 204 or not response.content:
                    return None
                try:
                    return response.json()
                except json.JSONDecodeError as error:
                    raise MediaRuntimeAPIError(
                        "MediaRuntime returned invalid JSON",
                        status=response.status_code,
                        details=response.text,
                        headers=dict(response.headers),
                    ) from error

            try:
                payload: Any = response.json()
            except json.JSONDecodeError:
                payload = response.text
            api_error = _error_for_response(response, payload, operation)
            if (
                retry == "idempotent-submit"
                and isinstance(api_error, IdempotencyInProgressError)
                and attempt < self.max_retries
            ):
                self._delay(attempt, response)
                attempt += 1
                continue
            raise api_error

    def upload(
        self,
        url: str,
        *,
        content: Any,
        headers: Mapping[str, str],
    ) -> None:
        # Signed uploads carry storage headers only—never the MediaRuntime API key.
        try:
            response = self.client.put(
                url,
                content=content,
                headers=dict(headers),
                timeout=self.timeout,
                follow_redirects=True,
            )
        except httpx.TimeoutException as error:
            raise MediaRuntimeTimeoutError("Signed upload timed out") from error
        except httpx.RequestError as error:
            raise MediaRuntimeConnectionError("Could not upload the local source") from error
        if not response.is_success:
            raise MediaRuntimeAPIError(
                response.text or f"Signed upload failed with status {response.status_code}",
                status=response.status_code,
                details=response.text,
                headers=dict(response.headers),
            )
