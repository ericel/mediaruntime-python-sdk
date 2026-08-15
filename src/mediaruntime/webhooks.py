from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeVar, cast

from .errors import WebhookVerificationError
from .models import WebhookEvent

HeaderValue = str | Sequence[str] | None
HandlerResult = TypeVar("HandlerResult")


def _header(headers: Mapping[str, HeaderValue], name: str) -> str:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() != expected:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, Sequence):
            return str(value[0]) if value else ""
    return ""


def _body(value: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode()
    raise WebhookVerificationError(
        "invalid_body",
        "Webhook body must be the original bytes or UTF-8 string",
    )


class WebhooksClient:
    def __init__(self, default_secret: str | None = None) -> None:
        self._default_secret = (
            default_secret.strip() if default_secret and default_secret.strip() else None
        )

    def verify(
        self,
        raw_body: bytes | bytearray | memoryview | str,
        headers: Mapping[str, HeaderValue],
        *,
        secret: str | None = None,
        tolerance: float = 300,
        now: float | None = None,
    ) -> WebhookEvent:
        resolved_secret = secret.strip() if secret and secret.strip() else self._default_secret
        if not resolved_secret:
            raise WebhookVerificationError(
                "missing_secret",
                "A MediaRuntime webhook secret is required for verification",
            )
        event_id = _header(headers, "X-Transcoder-Id").strip()
        timestamp_header = _header(headers, "X-Transcoder-Timestamp").strip()
        signature_header = _header(headers, "X-Transcoder-Signature").strip()
        if not event_id or not timestamp_header or not signature_header:
            raise WebhookVerificationError(
                "missing_headers",
                "Missing one or more X-Transcoder webhook headers",
            )
        if not timestamp_header.isdigit():
            raise WebhookVerificationError(
                "malformed_timestamp",
                "Webhook timestamp must be an integer Unix timestamp",
            )
        timestamp = int(timestamp_header)
        signature_timestamp = ""
        signatures: list[str] = []
        for raw_part in signature_header.split(","):
            key, separator, value = raw_part.strip().partition("=")
            if not separator:
                continue
            if key == "t" and not signature_timestamp:
                signature_timestamp = value
            elif key == "v1" and value:
                signatures.append(value)
        if not signature_timestamp or not signatures:
            raise WebhookVerificationError(
                "malformed_signature",
                "Webhook signature must contain t=<timestamp> and v1=<hex digest>",
            )
        if signature_timestamp != timestamp_header:
            raise WebhookVerificationError(
                "timestamp_mismatch",
                "Webhook signature timestamp does not match X-Transcoder-Timestamp",
            )
        current = time.time() if now is None else now
        if tolerance < 0 or abs(current - timestamp) > tolerance:
            raise WebhookVerificationError(
                "timestamp_outside_tolerance",
                "Webhook timestamp is outside the allowed tolerance",
            )
        body = _body(raw_body)
        signed = timestamp_header.encode() + b"." + event_id.encode() + b"." + body
        expected = hmac.new(resolved_secret.encode(), signed, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, signature.lower()) for signature in signatures):
            raise WebhookVerificationError(
                "invalid_signature",
                "Webhook signature verification failed",
            )
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WebhookVerificationError(
                "invalid_json",
                "Verified webhook body is not valid JSON",
            ) from error
        if not isinstance(parsed, dict):
            raise WebhookVerificationError(
                "invalid_json",
                "Verified webhook JSON must be an object",
            )
        data = cast(dict[str, Any], parsed)
        status = str(data.get("status") or "UNKNOWN").upper()
        return WebhookEvent(
            id=event_id,
            job_id=str(data.get("job_id") or ""),
            account_id=data.get("account_id") if isinstance(data.get("account_id"), str) else None,
            status=status,
            type=f"job.{status.lower()}",
            data=data,
            raw_body=body,
        )

    def flask(
        self,
        handler: Callable[[WebhookEvent, Any], HandlerResult],
        **verify_options: Any,
    ) -> Callable[[], HandlerResult | tuple[str, int]]:
        def route() -> HandlerResult | tuple[str, int]:
            from flask import request  # type: ignore[import-not-found]

            try:
                event = self.verify(
                    request.get_data(cache=True, as_text=False),
                    request.headers,
                    **verify_options,
                )
            except WebhookVerificationError:
                return "", 401
            return handler(event, request)

        return route

    def fastapi(
        self,
        handler: Callable[[WebhookEvent, Any], HandlerResult | Awaitable[HandlerResult]],
        **verify_options: Any,
    ) -> Callable[[Any], Awaitable[HandlerResult]]:
        async def route(request: Any) -> HandlerResult:
            from fastapi import HTTPException  # type: ignore[import-not-found]

            try:
                event = self.verify(await request.body(), request.headers, **verify_options)
            except WebhookVerificationError as error:
                raise HTTPException(
                    status_code=401, detail="Invalid MediaRuntime webhook"
                ) from error
            result = handler(event, request)
            if inspect.isawaitable(result):
                return await result
            return result

        return route

    def django(
        self,
        handler: Callable[[WebhookEvent, Any], HandlerResult],
        **verify_options: Any,
    ) -> Callable[[Any], HandlerResult | Any]:
        def route(request: Any) -> HandlerResult | Any:
            from django.http import HttpResponse  # type: ignore[import-not-found]

            try:
                event = self.verify(request.body, request.headers, **verify_options)
            except WebhookVerificationError:
                return HttpResponse(status=401)
            return handler(event, request)

        return route
