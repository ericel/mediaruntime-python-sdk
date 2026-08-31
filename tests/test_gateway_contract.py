from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest

from mediaruntime import (
    AuthenticationError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    MediaRuntime,
    MediaRuntimeAPIError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
)
from mediaruntime.jobs import TERMINAL_STATUSES, OutputAlias

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts" / "v1"


def _contract() -> dict[str, Any]:
    return json.loads((CONTRACT_DIR / "conformance.json").read_text(encoding="utf-8"))


def _response(
    status: int, payload: object, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def _path(value: dict[str, Any], dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        current = current[part]
    return current


def test_openapi_and_conformance_freeze_canonical_source_fields() -> None:
    contract = _contract()
    openapi = json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))
    schemas = openapi["components"]["schemas"]

    canonical = contract["compatibility"]["canonical_source_field"]
    legacy = contract["compatibility"]["accepted_legacy_source_field"]
    assert not any(path.startswith("/v1/internal/") for path in openapi["paths"])
    assert not any(name.startswith("Internal") for name in schemas)
    assert canonical == "source"
    assert canonical in schemas["CreateJobRequest"]["properties"]
    assert "contact_sheet" in schemas["TranscodeOutput"]["properties"]
    assert schemas["ContactSheetFormat"]["enum"] == ["jpg", "png", "webp"]
    assert schemas["ContactSheetConfig"]["properties"]["max_sheets"]["maximum"] == 20
    rendition = schemas["ImageRendition"]["properties"]
    assert rendition["max_bytes"]["anyOf"][0]["minimum"] == 256
    assert rendition["max_bytes"]["anyOf"][0]["maximum"] == 100_000_000
    assert rendition["min_quality"]["minimum"] == 1
    assert rendition["min_quality"]["maximum"] == 100
    assert "privacy_redaction" in schemas["TranscodeOutput"]["properties"]
    assert schemas["PrivacyDetector"]["enum"] == ["face", "license_plate", "text"]
    assert schemas["PrivacyRedactionConfig"]["properties"]["max_frames"]["maximum"] == 18000
    assert canonical in schemas["JobInput"]["properties"]
    assert legacy in schemas["CreateJobRequest"]["properties"]
    assert legacy in schemas["JobInput"]["properties"]
    assert set(schemas["OutputType"]["enum"]) == {
        "mp4",
        "webm",
        "hls",
        "dash",
        "audio",
        "image",
        "social",
        "gif",
        "frames",
    }


def test_sdk_serializes_scalar_and_batch_sources_from_contract() -> None:
    contract = _contract()
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return _response(200, {"job_id": "job_contract", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    single = contract["canonical_requests"]["single"]["example"]
    media.jobs.create(source=single["source"], outputs=single["outputs"])

    batch = contract["canonical_requests"]["batch"]["example"]
    sdk_inputs = []
    for item in batch["inputs"]:
        source = item["source"]
        sdk_inputs.append(
            {
                **{key: value for key, value in item.items() if key != "source"},
                "source": source["url"] if isinstance(source, dict) else source,
            }
        )
    media.jobs.create(inputs=sdk_inputs, outputs=batch["outputs"])

    canonical = contract["compatibility"]["canonical_source_field"]
    legacy = contract["compatibility"]["accepted_legacy_source_field"]
    assert requests[0] == single
    assert canonical in requests[0] and legacy not in requests[0]
    assert all(canonical in item and legacy not in item for item in requests[1]["inputs"])
    assert [item[canonical] for item in requests[1]["inputs"]] == [
        item[canonical]["url"] if isinstance(item[canonical], dict) else item[canonical]
        for item in batch["inputs"]
    ]


def test_six_typed_aliases_match_the_gateway_contract() -> None:
    contract_aliases = _contract()["output_aliases"]
    sdk_aliases = set(get_args(OutputAlias))
    assert sdk_aliases == set(contract_aliases)
    assert len(sdk_aliases) == 6

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _response(200, {"job_id": "job_aliases", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    media.jobs.create(
        source="https://cdn.example.com/media/source.mp4",
        outputs=list(get_args(OutputAlias)),
    )
    assert seen["outputs"] == list(get_args(OutputAlias))


def test_sticker_runtime_routes_and_authentication_match_the_gateway_contract() -> None:
    """Pin every SDK-backed Sticker Runtime operation and its credential boundary."""

    openapi = json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))
    paths = openapi["paths"]
    api_key_only = {
        ("/v1/sticker-collections", "get"),
        ("/v1/sticker-collections", "post"),
        ("/v1/sticker-collections/{collection_id}", "get"),
        ("/v1/sticker-collections/{collection_id}", "patch"),
        ("/v1/sticker-collections/{collection_id}", "delete"),
        ("/v1/sticker-collections/{collection_id}/packs", "get"),
        ("/v1/sticker-collections/{collection_id}/packs", "post"),
        ("/v1/sticker-collections/{collection_id}/packs/{pack_id}", "put"),
        ("/v1/sticker-collections/{collection_id}/packs/{pack_id}", "delete"),
        ("/v1/sticker-runtime/client-tokens", "post"),
        ("/v1/sticker-runtime/usage/current", "get"),
    }
    runtime_reads = {
        ("/v1/stickers/packs", "get"),
        ("/v1/stickers/search", "get"),
        ("/v1/stickers/typeahead", "get"),
        ("/v1/stickers/{sticker_id}", "get"),
        ("/v1/stickers/{sticker_id}/assets/{variant}", "get"),
    }

    assert all(
        paths[path][method]["security"] == [{"ProductionApiKey": []}]
        for path, method in api_key_only
    )
    assert all(
        paths[path][method]["security"] == [{"ProductionApiKey": []}, {"StickerClientToken": []}]
        for path, method in runtime_reads
    )

    # Keep client scope literals synchronized with both token request and response schemas.
    schemas = openapi["components"]["schemas"]
    expected_scopes = {
        "packs:read",
        "stickers:search",
        "stickers:read",
        "assets:resolve",
    }
    request_scope = schemas["StickerClientTokenRequest"]["properties"]["scopes"]
    response_scope = schemas["StickerClientTokenResponse"]["properties"]["scopes"]
    assert set(request_scope["anyOf"][0]["items"]["enum"]) == expected_scopes
    assert set(response_scope["items"]["enum"]) == expected_scopes


def test_hosted_recipe_reference_and_acknowledgement_match_contract() -> None:
    hosted = _contract()["hosted_recipes"]
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _response(
            200,
            {
                "job_id": "job_recipe_contract",
                "status": "QUEUED",
                "recipe": {
                    "name": "web-video",
                    "version": 1,
                    "reference": hosted["built_ins"][0],
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
        source="https://cdn.example.com/media/source.mp4",
        recipe=hosted["built_ins"][0],
    )

    assert seen == {
        "source": "https://cdn.example.com/media/source.mp4",
        "recipe": hosted["built_ins"][0],
    }
    assert job.recipe is not None
    assert set(job.recipe.__dataclass_fields__) == {
        "name",
        "version",
        "reference",
        "built_in",
        "sha256",
    }


def test_wait_stops_for_every_gateway_terminal_status() -> None:
    statuses = _contract()["terminal_statuses"]
    expected = set(statuses["single"]) | set(statuses["batch"])
    assert expected == TERMINAL_STATUSES

    for status in expected:
        reads = 0

        def handler(_request: httpx.Request, terminal: str = status) -> httpx.Response:
            nonlocal reads
            reads += 1
            return _response(200, {"job_id": "job_terminal", "status": terminal})

        media = MediaRuntime(
            api_key="sdk_key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        assert media.jobs.wait("job_terminal", timeout=0.1).status == status
        assert reads == 1


@pytest.mark.parametrize(
    ("status", "payload", "error_type"),
    [
        (401, {"detail": "Unauthorized"}, AuthenticationError),
        (403, {"detail": "Forbidden"}, PermissionDeniedError),
        (404, {"detail": "Job not found"}, NotFoundError),
        (429, {"detail": "Rate limited"}, RateLimitError),
        (400, {"detail": "Invalid request"}, ValidationError),
        (413, {"detail": "Source too large"}, ValidationError),
    ],
)
def test_existing_read_error_model_is_stable(
    status: int,
    payload: dict[str, Any],
    error_type: type[MediaRuntimeAPIError],
) -> None:
    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: _response(status, payload))
        ),
    )
    with pytest.raises(error_type) as raised:
        media.jobs.get("job_contract")
    assert raised.value.status == status
    assert raised.value.details == payload


@pytest.mark.parametrize(
    ("status", "message", "error_type"),
    [
        (
            409,
            "A request with this Idempotency-Key is still in progress",
            IdempotencyInProgressError,
        ),
        (
            422,
            "Idempotency-Key was already used with a different request",
            IdempotencyConflictError,
        ),
    ],
)
def test_existing_create_error_model_is_stable(
    status: int,
    message: str,
    error_type: type[MediaRuntimeAPIError],
) -> None:
    media = MediaRuntime(
        api_key="sdk_key",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: _response(status, {"detail": message}))
        ),
    )
    with pytest.raises(error_type):
        media.jobs.create(
            source="https://cdn.example.com/media/source.mp4",
            outputs=["video.web"],
            idempotency_key="contract-case",
        )


def test_gateway_error_envelopes_map_to_existing_sdk_errors() -> None:
    expected_types: dict[str, type[MediaRuntimeAPIError]] = {
        "unauthorized": AuthenticationError,
        "not_found": NotFoundError,
        "idempotency_conflict": IdempotencyConflictError,
        "idempotency_in_progress": IdempotencyInProgressError,
        "validation": ValidationError,
    }
    examples = _contract()["error_responses"]["examples"]
    assert set(expected_types) == {example["name"] for example in examples}

    for example in examples:
        media = MediaRuntime(
            api_key="sdk_key",
            max_retries=0,
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request, case=example: _response(case["status"], case["body"])
                )
            ),
        )
        with pytest.raises(expected_types[example["name"]]) as raised:
            if example["name"].startswith("idempotency_"):
                media.jobs.create(
                    source="https://cdn.example.com/media/source.mp4",
                    outputs=["video.web"],
                    idempotency_key="contract-case",
                )
            else:
                media.jobs.get("job_contract")
        assert raised.value.status == example["status"]
        assert raised.value.code == example["body"]["error"]["code"]
        assert raised.value.retryable is example["body"]["error"]["retryable"]
        assert raised.value.request_id == example["body"]["error"]["request_id"]
        assert raised.value.details == example["body"]["error"]["details"]
        assert raised.value.response_body == example["body"]


def test_request_correlation_contract_is_constrained_and_normalized() -> None:
    contract = _contract()
    correlation = contract["request_correlation"]
    assert correlation["header"] == "X-Request-Id"
    assert correlation["generated_prefix"] == "req_"
    assert contract["error_responses"]["normalized_fields"] == [
        "code",
        "message",
        "status",
        "retryable",
        "request_id",
        "details",
    ]


def test_polling_and_verified_webhook_preserve_bundle_contract_parity() -> None:
    contract = _contract()
    polling_payload = {
        "job_id": "job_bundle",
        "status": "COMPLETED",
        "metadata": {"asset_id": "asset-42"},
        "bundle": {
            "available": True,
            "download_url": "https://mediaruntime.com/v1/jobs/job_bundle/bundle?token=poll",
            "size_bytes": 1048576,
            "sha256": "a" * 64,
            "retention_days": 7,
            "expires_at": "2026-08-17T00:00:00Z",
        },
    }
    webhook_payload = {
        "event_id": "evt_job_bundle_completed",
        "job_id": "job_bundle",
        "account_id": "acc_contract",
        "status": "COMPLETED",
        "meta": {
            "request_metadata": {"asset_id": "asset-42"},
            "bundle": {"sha256": "a" * 64},
        },
        "delivery": {
            "retentionDays": 7,
            "expiresAt": "2026-08-17T00:00:00Z",
            "bundle": {
                "type": contract["delivery_contract"]["bundle"]["archive_type"],
                "size_bytes": 1048576,
                "download": {
                    "url": "https://mediaruntime.com/v1/jobs/job_bundle/bundle?token=webhook"
                },
            },
        },
    }

    media = MediaRuntime(
        api_key="sdk_key",
        webhook_secret="whsec_contract",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: _response(200, polling_payload))
        ),
    )
    polling = media.jobs.get("job_bundle")

    timestamp = 1_786_766_400
    body = json.dumps(webhook_payload, separators=(",", ":")).encode()
    event_id = webhook_payload["event_id"]
    signed = f"{timestamp}.{event_id}.".encode() + body
    digest = hmac.new(b"whsec_contract", signed, hashlib.sha256).hexdigest()
    event = media.webhooks.verify(
        body,
        {
            "X-Transcoder-Id": event_id,
            "X-Transcoder-Timestamp": str(timestamp),
            "X-Transcoder-Signature": f"t={timestamp},v1={digest}",
        },
        now=timestamp,
    )

    for pair in contract["delivery_contract"]["parity"]:
        assert _path(polling.raw, pair["polling_path"]) == _path(event.data, pair["webhook_path"])
    assert polling.bundle["download_url"] != event.data["delivery"]["bundle"]["download"]["url"]
    assert event.data["delivery"]["bundle"]["type"] == "zip"


def test_contract_pins_scoped_redemption() -> None:
    contract = _contract()
    delivery = contract["delivery_contract"]

    assert contract["schema_version"] == "1.3.0"
    assert delivery["redemption"]["required_token_claims"] == [
        "account_id",
        "job_id",
        "type",
        "exp",
    ]
    assert delivery["redemption"]["scope"] == "bundle"
    assert delivery["redemption"]["cross_account_result"] == 404
    assert delivery["redemption"]["expired_result"] == 410
    assert delivery["retention"]["configuration"] == "DELIVERY_RETENTION_DAYS"
    assert delivery["retention"]["expired_redemption_result"] == 410
    assert (
        delivery["retention"]["storage_cleanup_policy"]
        == "external_infrastructure_not_managed_in_repository"
    )
