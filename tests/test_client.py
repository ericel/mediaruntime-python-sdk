from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mediaruntime import MediaRuntime, MediaRuntimeAPIError, ValidationError, __version__


def response(
    status: int, payload: object, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def test_create_maps_source_and_preserves_metadata() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("X-API-Key")
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        seen["body"] = json.loads(request.content)
        return response(
            200,
            {"job_id": "job_123", "status": "QUEUED", "tier": "standard", "msg": "ok"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    media = MediaRuntime(api_key="sdk_key", http_client=client)
    job = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4", "preset": "mp4_720p_h264_aac"}],
        metadata={"keep_Snake_Case": {"nested-key": 7}},
        idempotency_key="video:123:v1",
    )

    assert job.id == "job_123"
    assert job.message == "ok"
    assert __version__ == "0.1.1"
    assert seen == {
        "url": "https://mediaruntime.com/v1/jobs",
        "api_key": "sdk_key",
        "idempotency": "video:123:v1",
        "body": {
            "file_url": "https://cdn.example.com/video.mp4",
            "outputs": [{"type": "mp4", "preset": "mp4_720p_h264_aac"}],
            "metadata": {"keep_Snake_Case": {"nested-key": 7}},
        },
    }


def test_unkeyed_submit_is_not_retried() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(503, {"detail": "unavailable"}, headers={"Retry-After": "0"})

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(MediaRuntimeAPIError):
        media.jobs.create(
            source="https://cdn.example.com/video.mp4",
            outputs=[{"type": "mp4"}],
        )
    assert attempts == 1


def test_keyed_submit_retries_a_retryable_response() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return response(503, {"detail": "unavailable"}, headers={"Retry-After": "0"})
        return response(200, {"job_id": "job_retry", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4"}],
        idempotency_key="retry-safe",
    )
    assert job.id == "job_retry"
    assert attempts == 2


def test_local_source_uses_signed_upload_without_api_key_leak(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video-bytes")
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "api_key": request.headers.get("X-API-Key"),
                "upload_token": request.headers.get("X-Upload-Token"),
                "body": body,
            }
        )
        if request.url.path == "/v1/upload-url":
            return response(
                200,
                {
                    "upload_url": "https://storage.example/upload",
                    "file_uri": "gs://opaque/input.mp4",
                    "upload_headers": {"X-Upload-Token": "signed"},
                },
            )
        if request.url.host == "storage.example":
            return httpx.Response(200)
        return response(200, {"job_id": "job_local", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(source=source, outputs=[{"type": "mp4"}])

    assert job.id == "job_local"
    assert calls[1]["api_key"] is None
    assert calls[1]["upload_token"] == "signed"
    assert calls[1]["body"] == b"video-bytes"
    submitted = json.loads(calls[2]["body"])
    assert submitted["file_url"] == "gs://opaque/input.mp4"


def test_wait_and_moderation_projection() -> None:
    status_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_reads
        if request.url.path.endswith("/moderation"):
            return response(
                200,
                {
                    "verdict": "review",
                    "flagged_checks": ["violence"],
                    "requested_checks": ["violence"],
                },
            )
        status_reads += 1
        return response(
            200,
            {
                "job_id": "job_wait",
                "status": "PROCESSING" if status_reads == 1 else "COMPLETED",
                "bundle": {"download_url": "https://cdn.example/bundle"},
            },
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    completed = media.jobs.wait("job_wait", timeout=1, initial_delay=0, max_delay=0)
    moderation = media.jobs.get_moderation("job_wait")

    assert completed.status == "COMPLETED"
    assert completed.bundle["download_url"] == "https://cdn.example/bundle"
    assert moderation.flagged_checks == ["violence"]


def test_capabilities_do_not_require_an_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") is None
        return response(
            200,
            {
                "capabilities": {"jobs": "enabled"},
                "output_types": {"mp4": ["mp4_720p_h264_aac"]},
                "preset_overrides": {},
                "notes": ["runtime source of truth"],
            },
        )

    media = MediaRuntime(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = media.capabilities.retrieve()
    assert result.output_types["mp4"] == ["mp4_720p_h264_aac"]


def test_job_id_is_encoded_as_one_path_segment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path == b"/v1/jobs/job%2Fsegment"
        return response(200, {"job_id": "job/segment", "status": "COMPLETED"})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert media.jobs.get("job/segment").id == "job/segment"


def test_validation_error_reads_fastapi_detail_list() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response(
            422,
            {"detail": [{"loc": ["body", "outputs"], "msg": "Field required"}]},
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValidationError, match="Field required") as raised:
        media.jobs.get("job_123")
    assert raised.value.field == "outputs"
