from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from mediaruntime import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    MediaRuntime,
    MediaRuntimeAPIError,
    ValidationError,
    __version__,
)


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
    assert __version__ == "1.2.0"
    assert seen == {
        "url": "https://mediaruntime.com/v1/jobs",
        "api_key": "sdk_key",
        "idempotency": "video:123:v1",
        "body": {
            "source": "https://cdn.example.com/video.mp4",
            "outputs": [{"type": "mp4", "preset": "mp4_720p_h264_aac"}],
            "metadata": {"keep_Snake_Case": {"nested-key": 7}},
        },
    }


def test_create_sends_canonical_source_for_every_batch_input() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return response(
            200,
            {"job_id": "job_batch", "status": "QUEUED", "tier": "standard", "msg": "ok"},
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(
        inputs=[
            {
                "source": "https://cdn.example.com/a.mp4",
                "input_id": "asset-a",
                "metadata": {"position": 0},
            },
            {
                "source": "https://cdn.example.com/b.mp4",
                "input_id": "asset-b",
            },
        ],
        outputs=["video.web"],
    )

    assert job.id == "job_batch"
    assert seen["body"] == {
        "inputs": [
            {
                "source": "https://cdn.example.com/a.mp4",
                "input_id": "asset-a",
                "metadata": {"position": 0},
            },
            {
                "source": "https://cdn.example.com/b.mp4",
                "input_id": "asset-b",
            },
        ],
        "outputs": ["video.web"],
    }


def test_create_forwards_output_aliases_for_gateway_resolution() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return response(
            200,
            {
                "job_id": "job_alias",
                "status": "QUEUED",
                "required_tier": "standard",
                "outputs": [
                    {"alias": "video.web", "type": "mp4", "preset": "mp4_720p_h264_aac"},
                    {
                        "alias": "audio.transcription",
                        "type": "audio",
                        "preset": "audio_aac_128k",
                    },
                ],
            },
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=["video.web", "audio.transcription"],
    )

    assert job.id == "job_alias"
    assert job.required_tier == "standard"
    assert job.outputs[0]["preset"] == "mp4_720p_h264_aac"
    assert seen["body"] == {
        "source": "https://cdn.example.com/video.mp4",
        "outputs": ["video.web", "audio.transcription"],
    }


def test_create_with_recipe_sends_only_the_reference_and_projects_acknowledgement() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return response(
            200,
            {
                "job_id": "job_recipe",
                "status": "QUEUED",
                "recipe": {
                    "name": "web-video",
                    "version": 1,
                    "reference": "web-video@1",
                    "built_in": True,
                    "sha256": "a" * 64,
                },
            },
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        recipe="web-video",
    )

    assert seen["body"] == {
        "source": "https://cdn.example.com/video.mp4",
        "recipe": "web-video",
    }
    assert job.recipe is not None
    assert job.recipe.reference == "web-video@1"


def test_recipe_rejects_inline_processing_overrides() -> None:
    media = MediaRuntime(api_key="sdk_key")
    with pytest.raises(ValidationError, match="cannot be combined"):
        media.jobs.create(
            source="https://cdn.example.com/video.mp4",
            recipe="web-video",
            outputs=["video.web"],
        )


def test_hosted_recipe_crud_uses_versioned_gateway_routes() -> None:
    calls: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path == "/v1/recipes":
            return response(
                200,
                {
                    "recipes": [
                        {
                            "name": "web-video",
                            "version": 1,
                            "reference": "web-video@1",
                            "description": "Web-ready video",
                            "built_in": True,
                            "status": "active",
                            "sha256": "a" * 64,
                        }
                    ]
                },
            )
        if request.method == "DELETE":
            return response(200, {"name": "team-video", "status": "archived", "latest_version": 2})
        version = 2 if request.url.path.endswith("/versions") else 1
        return response(
            201 if request.method == "POST" else 200,
            {
                "name": "team-video",
                "version": version,
                "reference": f"team-video@{version}",
                "description": "Team default",
                "built_in": False,
                "status": "active",
                "sha256": "b" * 64,
                "template": {"outputs": ["video.web"]},
            },
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert media.recipes.list()[0].reference == "web-video@1"
    created = media.recipes.create(
        name="team-video",
        description="Team default",
        template={"outputs": ["video.web"]},
    )
    second = media.recipes.create_version(
        "team-video",
        expected_latest_version=1,
        template={"outputs": ["video.streaming"]},
    )
    fetched = media.recipes.get("team-video", version=2)
    archived = media.recipes.archive("team-video")

    assert created.version == 1
    assert second.version == 2
    assert fetched.template == {"outputs": ["video.web"]}
    assert archived["status"] == "archived"
    assert calls == [
        ("GET", "/v1/recipes", None),
        (
            "POST",
            "/v1/recipes",
            {
                "name": "team-video",
                "description": "Team default",
                "template": {"outputs": ["video.web"]},
            },
        ),
        (
            "POST",
            "/v1/recipes/team-video/versions",
            {
                "expected_latest_version": 1,
                "template": {"outputs": ["video.streaming"]},
            },
        ),
        ("GET", "/v1/recipes/team-video/versions/2", None),
        ("DELETE", "/v1/recipes/team-video", None),
    ]


def test_generated_key_survives_lost_response_and_in_progress_replay() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["Idempotency-Key"])
        if len(keys) == 1:
            # The gateway accepted this request, but its response was lost in transit.
            raise httpx.ReadTimeout("response lost", request=request)
        if len(keys) == 2:
            return response(
                409,
                {"detail": "A request with this Idempotency-Key is still in progress"},
                headers={"Retry-After": "0"},
            )
        return response(200, {"job_id": "job_accepted", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4"}],
    )

    assert job.id == "job_accepted"
    assert len(keys) == 3
    assert len(set(keys)) == 1
    assert len(keys[0]) == 36
    assert UUID(keys[0]).version == 4


def test_generated_key_is_reused_across_5xx_and_429_backoff() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["Idempotency-Key"])
        if len(keys) == 1:
            return response(503, {"detail": "unavailable"}, headers={"Retry-After": "0"})
        if len(keys) == 2:
            return response(429, {"detail": "busy"}, headers={"Retry-After": "0"})
        return response(200, {"job_id": "job_retry", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    job = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4"}],
    )

    assert job.id == "job_retry"
    assert len(keys) == 3
    assert len(set(keys)) == 1


def test_generated_key_is_fresh_for_each_create_invocation_and_not_exposed() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["Idempotency-Key"])
        return response(200, {"job_id": f"job_{len(keys)}", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4"}],
    )
    second = media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4"}],
    )

    assert len(keys) == 2
    assert keys[0] != keys[1]
    assert all(UUID(key).version == 4 for key in keys)
    assert not hasattr(first, "idempotency_key")
    assert keys[0] not in repr(first)
    assert keys[1] not in repr(second)


def test_explicit_key_wins_and_is_reused_for_retry() -> None:
    attempts = 0
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        keys.append(request.headers["Idempotency-Key"])
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
    assert keys == ["retry-safe", "retry-safe"]


def test_explicit_key_does_not_generate_an_invocation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_uuid() -> None:
        raise AssertionError("explicit idempotency key attempted UUID generation")

    monkeypatch.setattr("mediaruntime.jobs.uuid4", unexpected_uuid)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["Idempotency-Key"]
        return response(200, {"job_id": "job_explicit", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    media.jobs.create(
        source="https://cdn.example.com/video.mp4",
        outputs=[{"type": "mp4"}],
        idempotency_key="business:asset-42:v3",
    )
    assert seen["key"] == "business:asset-42:v3"


def test_generated_key_keeps_idempotency_conflict_terminal() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(
            422,
            {"detail": "Idempotency-Key was already used with a different request body"},
        )

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(IdempotencyConflictError):
        media.jobs.create(
            source="https://cdn.example.com/video.mp4",
            outputs=[{"type": "mp4"}],
        )
    assert attempts == 1


def test_generated_key_does_not_retry_an_unrelated_normalized_409() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(
            409,
            {
                "error": {
                    "code": "resource_conflict",
                    "message": "A different resource conflicts",
                    "retryable": False,
                    "request_id": "req_conflict_other",
                    "details": None,
                }
            },
        )

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(MediaRuntimeAPIError, match="A different resource conflicts"):
        media.jobs.create(
            source="https://cdn.example.com/video.mp4",
            outputs=[{"type": "mp4"}],
        )
    assert attempts == 1


def test_generated_key_does_not_retry_an_unrelated_legacy_409() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(409, {"detail": "A sandbox job is already active for this session"})

    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(MediaRuntimeAPIError, match="sandbox job is already active") as raised:
        media.jobs.create(
            source="https://cdn.example.com/video.mp4",
            outputs=[{"type": "mp4"}],
        )
    assert not isinstance(raised.value, IdempotencyInProgressError)
    assert attempts == 1


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
    assert submitted["source"] == "gs://opaque/input.mp4"
    assert "file_url" not in submitted


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
                "public_presets": ["webm_vp9_1080p"],
                "presets": {
                    "webm_vp9_1080p": {
                        "output_type": "webm",
                        "base_tier": "premium",
                        "codec": "vp9",
                    }
                },
                "features": {"moderation": {"rejection_status": "REJECTED"}},
                "output_aliases": {
                    "video.web": {
                        "type": "mp4",
                        "preset": "mp4_720p_h264_aac",
                        "tier": "standard",
                    }
                },
                "notes": ["runtime source of truth"],
            },
        )

    media = MediaRuntime(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = media.capabilities.retrieve()
    assert result.output_types["mp4"] == ["mp4_720p_h264_aac"]
    assert result.public_presets == ["webm_vp9_1080p"]
    assert result.output_aliases["video.web"]["preset"] == "mp4_720p_h264_aac"
    assert result.presets["webm_vp9_1080p"]["codec"] == "vp9"
    assert result.features["moderation"]["rejection_status"] == "REJECTED"


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
