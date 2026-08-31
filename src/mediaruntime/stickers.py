"""Typed reads and scoped-token helpers for the Hosted Sticker Runtime."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal, cast
from urllib.parse import quote

from ._utils import object_dict, string_list, string_or_none
from .errors import ValidationError
from .models import (
    StickerCollection,
    StickerCollectionPackBinding,
    StickerCollectionPackBindingPage,
    StickerCollectionPage,
    StickerCollectionStatus,
    StickerRuntimeAsset,
    StickerRuntimeCharacter,
    StickerRuntimeClientToken,
    StickerRuntimePack,
    StickerRuntimePackPage,
    StickerRuntimeScope,
    StickerRuntimeSearchResult,
    StickerRuntimeSticker,
    StickerRuntimeTypeaheadResult,
    StickerRuntimeTypeaheadSuggestion,
    StickerRuntimeUsage,
    StickerRuntimeVariant,
    StickerVariantName,
)
from .sticker_collections import _UNSET, StickerCollectionsClient, _collection_id
from .transport import Transport

STICKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,159}$")
VARIANT_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
SUPPORTED_SCOPES = {
    "packs:read",
    "stickers:search",
    "stickers:read",
    "assets:resolve",
}


def _sticker_id(value: str) -> str:
    """Validate a stable sticker reference before treating it as one path segment."""

    normalized = value.strip()
    if not STICKER_ID_RE.fullmatch(normalized):
        raise ValidationError(
            "sticker_id must be a valid MediaRuntime sticker ID",
            status=400,
            field="sticker_id",
        )
    return quote(normalized, safe="")


def _variant_name(value: str) -> str:
    """Validate the gateway's bounded variant path grammar."""

    normalized = value.strip()
    if not VARIANT_RE.fullmatch(normalized):
        raise ValidationError(
            "variant must use lowercase letters, numbers, and underscores",
            status=400,
            field="variant",
        )
    return quote(normalized, safe="")


def _variant(value: Any) -> StickerRuntimeVariant:
    """Project approved variant metadata without exposing storage coordinates."""

    data = object_dict(value)
    return StickerRuntimeVariant(
        name=cast(StickerVariantName, str(data.get("name") or "thumbnail")),
        state=str(data.get("state") or ""),
        media_type=cast(Literal["image/webp"], str(data.get("media_type") or "image/webp")),
        bytes=int(data.get("bytes") or 0),
        raw=data,
    )


def _sticker(value: Any) -> StickerRuntimeSticker:
    """Project stable metadata and retain additive response fields in ``raw``."""

    data = object_dict(value)
    raw_variants = data.get("variants")
    variants = [_variant(item) for item in raw_variants] if isinstance(raw_variants, list) else []
    score_value = data.get("score")
    return StickerRuntimeSticker(
        sticker_id=str(data.get("sticker_id") or ""),
        semantic_id=str(data.get("semantic_id") or ""),
        pack_id=str(data.get("pack_id") or ""),
        pack_slug=str(data.get("pack_slug") or ""),
        pack_version=str(data.get("pack_version") or ""),
        label=str(data.get("label") or ""),
        emoji=string_or_none(data.get("emoji")),
        category=string_or_none(data.get("category")),
        keywords=string_list(data.get("keywords")),
        animated=bool(data.get("animated")),
        variants=variants,
        score=int(score_value) if isinstance(score_value, (int, float)) else None,
        raw=data,
    )


def _pack(value: Any) -> StickerRuntimePack:
    """Project one collection-enabled published pack."""

    data = object_dict(value)
    raw_characters = data.get("characters")
    characters: list[StickerRuntimeCharacter] = []
    if isinstance(raw_characters, list):
        for item in raw_characters:
            character = object_dict(item)
            characters.append(
                StickerRuntimeCharacter(
                    id=str(character.get("id") or ""),
                    name=str(character.get("name") or ""),
                    raw=character,
                )
            )
    return StickerRuntimePack(
        pack_id=str(data.get("pack_id") or ""),
        slug=str(data.get("slug") or ""),
        name=str(data.get("name") or ""),
        version=str(data.get("version") or ""),
        asset_count=int(data.get("asset_count") or 0),
        animated=bool(data.get("animated")),
        categories=string_list(data.get("categories")),
        characters=characters,
        activation_id=str(data.get("activation_id") or ""),
        raw=data,
    )


class StickersClient:
    """Manage collections and read collection-scoped Hosted Sticker Runtime assets."""

    def __init__(self, transport: Transport, *, client_token: str | None = None) -> None:
        self._transport = transport
        self._client_token = client_token
        self._collections = StickerCollectionsClient(transport)

    def collection(
        self,
        collection_id: str,
        *,
        client_token: str | None = None,
    ) -> StickerCollectionRuntimeClient:
        """Bind runtime reads to one collection and optional scoped credential."""

        # Collection binding removes a repeated security-critical ID from every
        # search/resolve call while still leaving it visible at construction time.
        runtime = self if client_token is None else self.with_client_token(client_token)
        return StickerCollectionRuntimeClient(runtime, collection_id)

    def list_collections(self, *, include_archived: bool = False) -> StickerCollectionPage:
        """List workspace collections through the API-key management surface."""

        return self._collections.list(include_archived=include_archived)

    def create_collection(
        self,
        *,
        name: str,
        description: str | None = None,
    ) -> StickerCollection:
        """Create an empty application collection without activating a pack."""

        return self._collections.create(name=name, description=description)

    def get_collection(self, collection_id: str) -> StickerCollection:
        """Retrieve one workspace-owned collection."""

        return self._collections.get(collection_id)

    def update_collection(
        self,
        collection_id: str,
        *,
        name: str | object = _UNSET,
        description: str | None | object = _UNSET,
        status: StickerCollectionStatus | object = _UNSET,
    ) -> StickerCollection:
        """Update explicitly supplied collection metadata or lifecycle state."""

        return self._collections.update(
            collection_id,
            name=name,
            description=description,
            status=status,
        )

    def archive_collection(self, collection_id: str) -> StickerCollection:
        """Recoverably archive a collection and retain binding history."""

        return self._collections.archive(collection_id)

    def list_pack_bindings(
        self,
        collection_id: str,
    ) -> StickerCollectionPackBindingPage:
        """List enabled and disabled bindings for one collection."""

        return self._collections.list_pack_bindings(collection_id)

    def add_activation(
        self,
        collection_id: str,
        *,
        activation_id: str,
    ) -> StickerCollectionPackBinding:
        """Enable one already-paid activation by its opaque activation ID."""

        return self._collections.add_activation(
            collection_id,
            activation_id=activation_id,
        )

    def enable_pack(
        self,
        collection_id: str,
        pack_id: str,
    ) -> StickerCollectionPackBinding:
        """Enable one already-activated stable pack ID for new use."""

        return self._collections.enable_pack(collection_id, pack_id)

    def disable_pack(
        self,
        collection_id: str,
        pack_id: str,
    ) -> StickerCollectionPackBinding:
        """Disable new use while retaining historical resolution rights."""

        return self._collections.disable_pack(collection_id, pack_id)

    def with_client_token(self, access_token: str) -> StickersClient:
        """Return runtime reads bound to a short-lived browser/mobile credential."""

        normalized = access_token.strip()
        if not normalized:
            raise ValidationError(
                "access_token must not be empty",
                status=400,
                field="access_token",
            )
        # The new resource shares the connection pool but replaces auth only for
        # metered runtime reads; token issuance and usage remain API-key requests.
        return StickersClient(self._transport, client_token=normalized)

    def _runtime_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any],
    ) -> Any:
        """Apply the selected API-key or scoped-token policy to one runtime read."""

        return self._transport.request(
            method,
            path,
            query=query,
            bearer_token=self._client_token,
            retry="safe",
        )

    def create_client_token(
        self,
        *,
        collection_id: str,
        expires_in_seconds: int = 900,
        scopes: Sequence[StickerRuntimeScope] | None = None,
    ) -> StickerRuntimeClientToken:
        """Exchange the server API key for a short-lived collection credential."""

        if not 60 <= expires_in_seconds <= 3600:
            raise ValidationError(
                "expires_in_seconds must be between 60 and 3600",
                status=400,
                field="expires_in_seconds",
            )
        body: dict[str, Any] = {
            "collection_id": _collection_id(collection_id),
            "expires_in_seconds": expires_in_seconds,
        }
        if scopes is not None:
            unsupported = [scope for scope in scopes if scope not in SUPPORTED_SCOPES]
            if unsupported:
                raise ValidationError(
                    f"Unsupported Sticker Runtime scope: {unsupported[0]}",
                    status=400,
                    field="scopes",
                )
            body["scopes"] = list(scopes)
        # Token minting intentionally ignores a resource-bound client token because
        # only a durable workspace API key may exchange credentials.
        data = object_dict(
            self._transport.request(
                "POST",
                "/sticker-runtime/client-tokens",
                body=body,
                retry="never",
            )
        )
        return StickerRuntimeClientToken(
            access_token=str(data.get("access_token") or ""),
            token_type=cast(Literal["Bearer"], str(data.get("token_type") or "Bearer")),
            expires_in=int(data.get("expires_in") or 0),
            expires_at=str(data.get("expires_at") or ""),
            collection_id=str(data.get("collection_id") or ""),
            scopes=cast(list[StickerRuntimeScope], string_list(data.get("scopes"))),
            raw=data,
        )

    def list_packs(self, *, collection_id: str) -> StickerRuntimePackPage:
        """List published packs enabled for new use in one active collection."""

        data = object_dict(
            self._runtime_request(
                "GET",
                "/stickers/packs",
                query={"collection_id": _collection_id(collection_id)},
            )
        )
        rows = data.get("items")
        items = [_pack(item) for item in rows] if isinstance(rows, list) else []
        return StickerRuntimePackPage(items=items, total=int(data.get("total") or 0))

    def search(
        self,
        query: str,
        *,
        collection_id: str,
        pack_id: str | None = None,
        category: str | None = None,
        animated: bool | None = None,
        limit: int = 24,
    ) -> StickerRuntimeSearchResult:
        """Search enabled sticker metadata with deterministic server ranking."""

        normalized_query = query.strip()
        if not 1 <= len(normalized_query) <= 100:
            raise ValidationError(
                "query must contain between 1 and 100 characters",
                status=400,
                field="query",
            )
        if not 1 <= limit <= 50:
            raise ValidationError("limit must be between 1 and 50", status=400, field="limit")
        data = object_dict(
            self._runtime_request(
                "GET",
                "/stickers/search",
                query={
                    "q": normalized_query,
                    "collection_id": _collection_id(collection_id),
                    "pack_id": pack_id,
                    "category": category,
                    "animated": animated,
                    "limit": limit,
                },
            )
        )
        rows = data.get("items")
        items = [_sticker(item) for item in rows] if isinstance(rows, list) else []
        return StickerRuntimeSearchResult(
            query=str(data.get("query") or ""),
            items=items,
            total=int(data.get("total") or 0),
        )

    def typeahead(
        self,
        query: str,
        *,
        collection_id: str,
        pack_id: str | None = None,
        locale: str = "en",
        limit: int = 8,
    ) -> StickerRuntimeTypeaheadResult:
        """Return locale-aware prefix suggestions from enabled packs."""

        normalized_query = query.strip()
        if not 1 <= len(normalized_query) <= 100:
            raise ValidationError(
                "query must contain between 1 and 100 characters",
                status=400,
                field="query",
            )
        if not 1 <= limit <= 20:
            raise ValidationError("limit must be between 1 and 20", status=400, field="limit")
        if not 2 <= len(locale) <= 16:
            raise ValidationError(
                "locale must contain between 2 and 16 characters",
                status=400,
                field="locale",
            )
        data = object_dict(
            self._runtime_request(
                "GET",
                "/stickers/typeahead",
                query={
                    "q": normalized_query,
                    "collection_id": _collection_id(collection_id),
                    "pack_id": pack_id,
                    "locale": locale,
                    "limit": limit,
                },
            )
        )
        raw_suggestions = data.get("suggestions")
        suggestions: list[StickerRuntimeTypeaheadSuggestion] = []
        if isinstance(raw_suggestions, list):
            for item in raw_suggestions:
                suggestion = object_dict(item)
                suggestions.append(
                    StickerRuntimeTypeaheadSuggestion(
                        text=str(suggestion.get("text") or ""),
                        asset_count=int(suggestion.get("asset_count") or 0),
                        raw=suggestion,
                    )
                )
        return StickerRuntimeTypeaheadResult(
            query=str(data.get("query") or ""),
            locale=str(data.get("locale") or ""),
            suggestions=suggestions,
        )

    def get(self, sticker_id: str, *, collection_id: str) -> StickerRuntimeSticker:
        """Get stable metadata while the sticker remains enabled for new use."""

        return _sticker(
            self._runtime_request(
                "GET",
                f"/stickers/{_sticker_id(sticker_id)}",
                query={"collection_id": _collection_id(collection_id)},
            )
        )

    def resolve(
        self,
        sticker_id: str,
        variant: StickerVariantName,
        *,
        collection_id: str,
    ) -> StickerRuntimeAsset:
        """Authorize a historical-safe, short-lived URL for one private asset."""

        data = object_dict(
            self._runtime_request(
                "GET",
                f"/stickers/{_sticker_id(sticker_id)}/assets/{_variant_name(variant)}",
                query={"collection_id": _collection_id(collection_id)},
            )
        )
        return StickerRuntimeAsset(
            sticker_id=str(data.get("sticker_id") or ""),
            pack_id=str(data.get("pack_id") or ""),
            pack_version=str(data.get("pack_version") or ""),
            variant=str(data.get("variant") or ""),
            media_type=cast(
                Literal["image/webp"],
                str(data.get("media_type") or "image/webp"),
            ),
            bytes=int(data.get("bytes") or 0),
            sha256=str(data.get("sha256") or ""),
            url=str(data.get("url") or ""),
            expires_in_seconds=int(data.get("expires_in_seconds") or 0),
            expires_at=str(data.get("expires_at") or ""),
            raw=data,
        )

    def usage(self) -> StickerRuntimeUsage:
        """Read current workspace usage with the server API key."""

        # Usage is intentionally never authenticated by the resource's optional
        # client token; collection-scoped credentials cannot inspect workspace totals.
        data = object_dict(
            self._transport.request(
                "GET",
                "/sticker-runtime/usage/current",
                retry="safe",
            )
        )
        return StickerRuntimeUsage(
            month=str(data.get("month") or ""),
            operations=int(data.get("operations") or 0),
            included_operations=int(data.get("included_operations") or 0),
            remaining_operations=int(data.get("remaining_operations") or 0),
            operations_utilization_percent=float(data.get("operations_utilization_percent") or 0),
            authorized_delivery_bytes=int(data.get("authorized_delivery_bytes") or 0),
            included_delivery_bytes=int(data.get("included_delivery_bytes") or 0),
            remaining_delivery_bytes=int(data.get("remaining_delivery_bytes") or 0),
            delivery_utilization_percent=float(data.get("delivery_utilization_percent") or 0),
            overage_charged_cents=int(data.get("overage_charged_cents") or 0),
            currency=cast(Literal["USD"], str(data.get("currency") or "USD")),
            status=cast(
                Literal["healthy", "approaching_limit", "overage"],
                str(data.get("status") or "healthy"),
            ),
            raw=data,
        )


class StickerCollectionRuntimeClient:
    """Runtime reads bound to one collection to prevent cross-collection mistakes."""

    def __init__(self, stickers: StickersClient, collection_id: str) -> None:
        self._stickers = stickers
        # Validate once, but retain the canonical unescaped value for query encoding.
        self.collection_id = _collection_id(collection_id)

    def list_packs(self) -> StickerRuntimePackPage:
        """List published packs enabled in this collection."""

        return self._stickers.list_packs(collection_id=self.collection_id)

    def search(
        self,
        query: str,
        *,
        pack_id: str | None = None,
        category: str | None = None,
        animated: bool | None = None,
        limit: int = 24,
    ) -> StickerRuntimeSearchResult:
        """Search this collection's enabled sticker metadata."""

        return self._stickers.search(
            query,
            collection_id=self.collection_id,
            pack_id=pack_id,
            category=category,
            animated=animated,
            limit=limit,
        )

    def typeahead(
        self,
        query: str,
        *,
        pack_id: str | None = None,
        locale: str = "en",
        limit: int = 8,
    ) -> StickerRuntimeTypeaheadResult:
        """Return prefix suggestions from this collection's enabled packs."""

        return self._stickers.typeahead(
            query,
            collection_id=self.collection_id,
            pack_id=pack_id,
            locale=locale,
            limit=limit,
        )

    def get(self, sticker_id: str) -> StickerRuntimeSticker:
        """Get stable metadata for one enabled sticker reference."""

        return self._stickers.get(sticker_id, collection_id=self.collection_id)

    def resolve(
        self,
        sticker_id: str,
        variant: StickerVariantName,
    ) -> StickerRuntimeAsset:
        """Authorize one historical-safe, short-lived asset URL."""

        return self._stickers.resolve(
            sticker_id,
            variant,
            collection_id=self.collection_id,
        )
