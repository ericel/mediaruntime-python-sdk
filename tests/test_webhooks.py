from __future__ import annotations

import hashlib
import hmac
import json
import sys
import types
from typing import Any

import pytest

from mediaruntime import MediaRuntime, WebhookVerificationError


def fixture() -> tuple[bytes, dict[str, str], str, int]:
    secret = "whsec_test_secret"
    timestamp = 1_786_766_400
    event_id = "webhook_evt_job_123"
    body = json.dumps(
        {"job_id": "job_123", "account_id": "acc_123", "status": "COMPLETED"},
        separators=(",", ":"),
    ).encode()
    digest = hmac.new(
        secret.encode(),
        f"{timestamp}.{event_id}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-Transcoder-Id": event_id,
        "X-Transcoder-Timestamp": str(timestamp),
        "X-Transcoder-Signature": f"t={timestamp},v1={digest}",
    }
    return body, headers, secret, timestamp


def test_verifies_exact_bytes_and_projects_event() -> None:
    body, headers, secret, timestamp = fixture()
    media = MediaRuntime(webhook_secret=secret)
    event = media.webhooks.verify(body, headers, now=timestamp)
    assert event.id == "webhook_evt_job_123"
    assert event.job_id == "job_123"
    assert event.type == "job.completed"
    assert event.raw_body == body


def test_rejects_changed_or_stale_body() -> None:
    body, headers, secret, timestamp = fixture()
    media = MediaRuntime(webhook_secret=secret)
    with pytest.raises(WebhookVerificationError, match="verification failed"):
        media.webhooks.verify(body + b" ", headers, now=timestamp)
    with pytest.raises(WebhookVerificationError) as raised:
        media.webhooks.verify(body, headers, now=timestamp + 301)
    assert raised.value.reason == "timestamp_outside_tolerance"


def test_flask_adapter_uses_raw_request_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    body, headers, secret, timestamp = fixture()

    class Request:
        def __init__(self) -> None:
            self.headers = headers

        def get_data(self, *, cache: bool, as_text: bool) -> bytes:
            assert cache is True
            assert as_text is False
            return body

    flask = types.ModuleType("flask")
    flask.request = Request()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "flask", flask)
    media = MediaRuntime(webhook_secret=secret)
    route = media.webhooks.flask(lambda event, _request: (event.id, 204), now=timestamp)
    assert route() == ("webhook_evt_job_123", 204)


@pytest.mark.asyncio
async def test_fastapi_adapter_uses_awaited_raw_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body, headers, secret, timestamp = fixture()

    class HTTPException(Exception):
        def __init__(self, *, status_code: int, detail: str) -> None:
            self.status_code = status_code
            self.detail = detail

    fastapi = types.ModuleType("fastapi")
    fastapi.HTTPException = HTTPException  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)

    class Request:
        def __init__(self) -> None:
            self.headers = headers

        async def body(self) -> bytes:
            return body

    media = MediaRuntime(webhook_secret=secret)
    route = media.webhooks.fastapi(lambda event, _request: event.id, now=timestamp)
    assert await route(Request()) == "webhook_evt_job_123"


def test_django_adapter_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    body, headers, secret, timestamp = fixture()

    class HttpResponse:
        def __init__(self, *, status: int) -> None:
            self.status_code = status

    django = types.ModuleType("django")
    django_http = types.ModuleType("django.http")
    django_http.HttpResponse = HttpResponse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "django", django)
    monkeypatch.setitem(sys.modules, "django.http", django_http)

    class Request:
        def __init__(self) -> None:
            self.body = body + b" "
            self.headers = headers

    media = MediaRuntime(webhook_secret=secret)
    route = media.webhooks.django(lambda event, _request: event.id, now=timestamp)
    result: Any = route(Request())
    assert result.status_code == 401
