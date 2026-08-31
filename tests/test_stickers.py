from __future__ import annotations

import json

import httpx
import pytest

from mediaruntime import MediaRuntime, ValidationError

COLLECTION_ID = "stc_11111111111111111111111111111111"
ACTIVATION_ID = "rpa_22222222222222222222222222222222"
PACK_ID = "sage-summer-v1"
STICKER_ID = "sage-summer-v1-beach-day"


def _response(payload: object, status: int = 200) -> httpx.Response:
    """Build JSON responses with the same shape used by the gateway tests."""

    return httpx.Response(status, json=payload)


def _binding_payload(*, status: str = "enabled") -> dict[str, object]:
    """Return one complete retained pack-binding projection."""

    return {
        "binding_id": "spb_33333333333333333333333333333333",
        "collection_id": COLLECTION_ID,
        "activation_id": ACTIVATION_ID,
        "pack_id": PACK_ID,
        "pack_slug": "sage-summer",
        "pack_name": "Sage Summer",
        "pack_version": "1.0.0",
        "status": status,
        "historical_access": "preserve",
        "first_enabled_at": "2026-08-01T00:00:00Z",
        "enabled_at": "2026-08-01T00:00:00Z",
        "disabled_at": None,
        "updated_at": "2026-08-01T00:00:00Z",
    }


def _collection_payload() -> dict[str, object]:
    """Return a collection with one enabled pack for typed projection checks."""

    return {
        "collection_id": COLLECTION_ID,
        "workspace_id": "account_1",
        "name": "Chat app",
        "description": "Production stickers",
        "status": "active",
        "packs": [_binding_payload()],
        "created_at": "2026-08-01T00:00:00Z",
        "archived_at": None,
        "updated_at": "2026-08-01T00:00:00Z",
        "future_field": "preserved",
    }


def _sticker_payload(*, score: int | None = 900) -> dict[str, object]:
    """Return stable sticker metadata with one approved private variant."""

    payload: dict[str, object] = {
        "sticker_id": STICKER_ID,
        "semantic_id": "sage.beach-day",
        "pack_id": PACK_ID,
        "pack_slug": "sage-summer",
        "pack_version": "1.0.0",
        "label": "Beach Day",
        "emoji": "🏖️",
        "category": "summer",
        "keywords": ["beach", "vacation"],
        "animated": True,
        "variants": [
            {
                "name": "small_160",
                "state": "small-160",
                "media_type": "image/webp",
                "bytes": 1234,
            }
        ],
    }
    if score is not None:
        payload["score"] = score
    return payload


def test_collection_management_uses_api_key_and_projects_typed_models() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {
                "name": "Chat app",
                "description": "Production stickers",
            }
            return _response(_collection_payload())
        if request.method == "PUT":
            return _response(_binding_payload())
        return _response({"items": [_collection_payload()], "total": 1})

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    created = media.stickers.create_collection(
        name="Chat app",
        description="Production stickers",
    )
    binding = media.stickers.enable_pack(COLLECTION_ID, PACK_ID)
    page = media.stickers.list_collections(include_archived=True)

    assert created.raw["future_field"] == "preserved"
    assert created.packs[0].pack_id == PACK_ID
    assert binding.activation_id == ACTIVATION_ID
    assert page.total == 1
    assert [request.headers.get("X-API-Key") for request in requests] == [
        "sdk_key",
        "sdk_key",
        "sdk_key",
    ]
    assert requests[1].url.path.endswith(f"/sticker-collections/{COLLECTION_ID}/packs/{PACK_ID}")
    assert requests[2].url.params["include_archived"] == "true"


def test_collection_management_covers_metadata_binding_and_archive_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/packs") and request.method == "GET":
            return _response({"items": [_binding_payload()], "total": 1})
        if request.url.path.endswith("/packs") and request.method == "POST":
            assert json.loads(request.content) == {"activation_id": ACTIVATION_ID}
            return _response(_binding_payload())
        if request.url.path.endswith(f"/packs/{PACK_ID}"):
            return _response(_binding_payload(status="disabled"))
        if request.method == "PATCH":
            assert json.loads(request.content) == {
                "name": "Renamed chat",
                "description": None,
                "status": "archived",
            }
        return _response(_collection_payload())

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert media.stickers.get_collection(COLLECTION_ID).collection_id == COLLECTION_ID
    updated = media.stickers.update_collection(
        COLLECTION_ID,
        name="Renamed chat",
        description=None,
        status="archived",
    )
    assert updated.workspace_id == "account_1"
    assert media.stickers.list_pack_bindings(COLLECTION_ID).total == 1
    assert (
        media.stickers.add_activation(COLLECTION_ID, activation_id=ACTIVATION_ID).pack_id == PACK_ID
    )
    assert media.stickers.disable_pack(COLLECTION_ID, PACK_ID).status == "disabled"
    assert media.stickers.archive_collection(COLLECTION_ID).collection_id == COLLECTION_ID

    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", f"/v1/sticker-collections/{COLLECTION_ID}"),
        ("PATCH", f"/v1/sticker-collections/{COLLECTION_ID}"),
        ("GET", f"/v1/sticker-collections/{COLLECTION_ID}/packs"),
        ("POST", f"/v1/sticker-collections/{COLLECTION_ID}/packs"),
        ("DELETE", f"/v1/sticker-collections/{COLLECTION_ID}/packs/{PACK_ID}"),
        ("DELETE", f"/v1/sticker-collections/{COLLECTION_ID}"),
    ]


def test_collection_bound_runtime_search_typeahead_get_and_resolve() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.headers.get("X-API-Key") == "sdk_key"
        assert request.url.params["collection_id"] == COLLECTION_ID
        if request.url.path.endswith("/packs"):
            return _response(
                {
                    "items": [
                        {
                            "pack_id": PACK_ID,
                            "slug": "sage-summer",
                            "name": "Sage Summer",
                            "version": "1.0.0",
                            "asset_count": 24,
                            "animated": True,
                            "categories": ["summer"],
                            "characters": [{"id": "sage", "name": "Sage"}],
                            "activation_id": ACTIVATION_ID,
                        }
                    ],
                    "total": 1,
                }
            )
        if request.url.path.endswith("/search"):
            assert request.url.params["q"] == "beach"
            assert request.url.params["animated"] == "true"
            return _response({"query": "beach", "items": [_sticker_payload()], "total": 1})
        if request.url.path.endswith("/typeahead"):
            return _response(
                {
                    "query": "bea",
                    "locale": "en",
                    "suggestions": [{"text": "Beach", "asset_count": 2}],
                }
            )
        if request.url.path.endswith("/assets/small_160"):
            return _response(
                {
                    "sticker_id": STICKER_ID,
                    "pack_id": PACK_ID,
                    "pack_version": "1.0.0",
                    "variant": "small_160",
                    "media_type": "image/webp",
                    "bytes": 1234,
                    "sha256": "a" * 64,
                    "url": "https://storage.example.com/signed",
                    "expires_in_seconds": 300,
                    "expires_at": "2026-08-01T00:05:00Z",
                }
            )
        return _response(_sticker_payload(score=None))

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    stickers = media.stickers.collection(COLLECTION_ID)
    packs = stickers.list_packs()
    search = stickers.search("beach", animated=True)
    typeahead = stickers.typeahead("bea")
    sticker = stickers.get(STICKER_ID)
    asset = stickers.resolve(STICKER_ID, "small_160")

    assert packs.items[0].characters[0].name == "Sage"
    assert search.items[0].variants[0].bytes == 1234
    assert typeahead.suggestions[0].asset_count == 2
    assert sticker.score is None
    assert asset.sha256 == "a" * 64
    assert seen_paths == [
        "/v1/stickers/packs",
        "/v1/stickers/search",
        "/v1/stickers/typeahead",
        f"/v1/stickers/{STICKER_ID}",
        f"/v1/stickers/{STICKER_ID}/assets/small_160",
    ]


def test_scoped_token_replaces_api_key_only_for_runtime_reads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/search"):
            return _response({"query": "beach", "items": [], "total": 0})
        return _response(
            {
                "month": "2026-08",
                "operations": 1,
                "included_operations": 1000,
                "remaining_operations": 999,
                "operations_utilization_percent": 0.1,
                "authorized_delivery_bytes": 0,
                "included_delivery_bytes": 1000000,
                "remaining_delivery_bytes": 1000000,
                "delivery_utilization_percent": 0,
                "overage_charged_cents": 0,
                "currency": "USD",
                "status": "healthy",
            }
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    media.stickers.collection(COLLECTION_ID, client_token="mrt_v1_scoped").search("beach")
    usage = media.stickers.usage()

    # Scoped reads carry only Bearer auth; workspace totals deliberately return to API-key auth.
    assert requests[0].headers.get("Authorization") == "Bearer mrt_v1_scoped"
    assert requests[0].headers.get("X-API-Key") is None
    assert requests[1].headers.get("Authorization") is None
    assert requests[1].headers.get("X-API-Key") == "sdk_key"
    assert usage.remaining_operations == 999


def test_create_client_token_is_api_key_only_and_preserves_scopes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "sdk_key"
        assert request.headers.get("Authorization") is None
        assert json.loads(request.content) == {
            "collection_id": COLLECTION_ID,
            "expires_in_seconds": 600,
            "scopes": ["stickers:search", "assets:resolve"],
        }
        return _response(
            {
                "access_token": "mrt_v1_scoped",
                "token_type": "Bearer",
                "expires_in": 600,
                "expires_at": "2026-08-01T00:10:00Z",
                "collection_id": COLLECTION_ID,
                "scopes": ["stickers:search", "assets:resolve"],
            }
        )

    media = MediaRuntime(
        api_key="sdk_key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    token = media.stickers.create_client_token(
        collection_id=COLLECTION_ID,
        expires_in_seconds=600,
        scopes=["stickers:search", "assets:resolve"],
    )

    assert token.access_token == "mrt_v1_scoped"
    assert token.scopes == ["stickers:search", "assets:resolve"]


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda media: media.stickers.collection("wrong"), "collection_id"),
        (
            lambda media: media.stickers.collection(COLLECTION_ID).search(""),
            "query",
        ),
        (
            lambda media: media.stickers.create_client_token(
                collection_id=COLLECTION_ID,
                expires_in_seconds=30,
            ),
            "expires_in_seconds",
        ),
    ],
)
def test_runtime_validation_fails_before_http(operation: object, message: str) -> None:
    """Reject malformed bounds before credentials or metered requests leave the process."""

    media = MediaRuntime(api_key="sdk_key")
    with pytest.raises(ValidationError, match=message):
        operation(media)  # type: ignore[operator]
