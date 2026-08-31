"""Workspace configuration APIs for Hosted Sticker Runtime collections."""

from __future__ import annotations

import re
from typing import Any, cast
from urllib.parse import quote

from ._utils import object_dict, string_or_none
from .errors import ValidationError
from .models import (
    StickerBindingStatus,
    StickerCollection,
    StickerCollectionPackBinding,
    StickerCollectionPackBindingPage,
    StickerCollectionPage,
    StickerCollectionStatus,
    StickerHistoricalAccess,
)
from .transport import Transport

COLLECTION_ID_RE = re.compile(r"^stc_[0-9a-f]{32}$")
ACTIVATION_ID_RE = re.compile(r"^rpa_[0-9a-f]{32}$")
_UNSET = object()


def _collection_id(value: str) -> str:
    """Validate and escape one opaque collection identifier for safe path use."""

    normalized = value.strip()
    if not COLLECTION_ID_RE.fullmatch(normalized):
        raise ValidationError(
            "collection_id must be a MediaRuntime sticker collection ID",
            status=400,
            field="collection_id",
        )
    return quote(normalized, safe="")


def _pack_id(value: str) -> str:
    """Bound and escape a stable pack ID without duplicating server-only grammar."""

    normalized = value.strip()
    if not 2 <= len(normalized) <= 160:
        raise ValidationError(
            "pack_id must contain between 2 and 160 characters",
            status=400,
            field="pack_id",
        )
    return quote(normalized, safe="")


def _binding(value: Any) -> StickerCollectionPackBinding:
    """Project a binding while preserving additive gateway fields in ``raw``."""

    data = object_dict(value)
    return StickerCollectionPackBinding(
        binding_id=str(data.get("binding_id") or ""),
        collection_id=str(data.get("collection_id") or ""),
        activation_id=str(data.get("activation_id") or ""),
        pack_id=str(data.get("pack_id") or ""),
        pack_slug=str(data.get("pack_slug") or ""),
        pack_name=str(data.get("pack_name") or ""),
        pack_version=str(data.get("pack_version") or ""),
        status=cast(StickerBindingStatus, str(data.get("status") or "disabled")),
        historical_access=cast(
            StickerHistoricalAccess,
            str(data.get("historical_access") or "preserve"),
        ),
        first_enabled_at=string_or_none(data.get("first_enabled_at")),
        enabled_at=string_or_none(data.get("enabled_at")),
        disabled_at=string_or_none(data.get("disabled_at")),
        updated_at=string_or_none(data.get("updated_at")),
        raw=data,
    )


def _collection(value: Any) -> StickerCollection:
    """Project one collection and its currently enabled pack bindings."""

    data = object_dict(value)
    raw_packs = data.get("packs")
    packs = [_binding(item) for item in raw_packs] if isinstance(raw_packs, list) else []
    return StickerCollection(
        collection_id=str(data.get("collection_id") or ""),
        workspace_id=str(data.get("workspace_id") or ""),
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        status=cast(StickerCollectionStatus, str(data.get("status") or "active")),
        packs=packs,
        created_at=str(data.get("created_at") or ""),
        archived_at=string_or_none(data.get("archived_at")),
        updated_at=str(data.get("updated_at") or ""),
        raw=data,
    )


class StickerCollectionsClient:
    """Manage app collections with the MediaRuntime workspace API key."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def list(self, *, include_archived: bool = False) -> StickerCollectionPage:
        """List active collections, optionally including recoverably archived ones."""

        data = object_dict(
            self._transport.request(
                "GET",
                "/sticker-collections",
                query={"include_archived": include_archived},
                retry="safe",
            )
        )
        rows = data.get("items")
        items = [_collection(item) for item in rows] if isinstance(rows, list) else []
        return StickerCollectionPage(items=items, total=int(data.get("total") or 0))

    def create(self, *, name: str, description: str | None = None) -> StickerCollection:
        """Create an empty collection without purchasing or activating a pack."""

        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        return _collection(
            self._transport.request(
                "POST",
                "/sticker-collections",
                body=body,
                retry="never",
            )
        )

    def get(self, collection_id: str) -> StickerCollection:
        """Retrieve one workspace-owned collection and its enabled packs."""

        return _collection(
            self._transport.request(
                "GET",
                f"/sticker-collections/{_collection_id(collection_id)}",
                retry="safe",
            )
        )

    def update(
        self,
        collection_id: str,
        *,
        name: str | object = _UNSET,
        description: str | None | object = _UNSET,
        status: StickerCollectionStatus | object = _UNSET,
    ) -> StickerCollection:
        """Update only explicitly supplied metadata or lifecycle fields."""

        body: dict[str, Any] = {}
        # The sentinel preserves the gateway distinction between omitted and explicit null.
        if name is not _UNSET:
            body["name"] = name
        if description is not _UNSET:
            body["description"] = description
        if status is not _UNSET:
            body["status"] = status
        if not body:
            raise ValidationError(
                "Provide at least one collection field to update",
                status=400,
            )
        return _collection(
            self._transport.request(
                "PATCH",
                f"/sticker-collections/{_collection_id(collection_id)}",
                body=body,
                retry="never",
            )
        )

    def archive(self, collection_id: str) -> StickerCollection:
        """Recoverably archive a collection while retaining historical bindings."""

        return _collection(
            self._transport.request(
                "DELETE",
                f"/sticker-collections/{_collection_id(collection_id)}",
                retry="never",
            )
        )

    def list_pack_bindings(self, collection_id: str) -> StickerCollectionPackBindingPage:
        """List enabled and disabled binding history for audit and management."""

        data = object_dict(
            self._transport.request(
                "GET",
                f"/sticker-collections/{_collection_id(collection_id)}/packs",
                retry="safe",
            )
        )
        rows = data.get("items")
        items = [_binding(item) for item in rows] if isinstance(rows, list) else []
        return StickerCollectionPackBindingPage(
            items=items,
            total=int(data.get("total") or 0),
        )

    def add_activation(
        self,
        collection_id: str,
        *,
        activation_id: str,
    ) -> StickerCollectionPackBinding:
        """Enable an existing paid activation without another wallet charge."""

        normalized_activation = activation_id.strip()
        if not ACTIVATION_ID_RE.fullmatch(normalized_activation):
            raise ValidationError(
                "activation_id must be a MediaRuntime pack activation ID",
                status=400,
                field="activation_id",
            )
        return _binding(
            self._transport.request(
                "POST",
                f"/sticker-collections/{_collection_id(collection_id)}/packs",
                body={"activation_id": normalized_activation},
                retry="never",
            )
        )

    def enable_pack(
        self,
        collection_id: str,
        pack_id: str,
    ) -> StickerCollectionPackBinding:
        """Enable an already-activated stable pack ID for new collection use."""

        return _binding(
            self._transport.request(
                "PUT",
                f"/sticker-collections/{_collection_id(collection_id)}/packs/{_pack_id(pack_id)}",
                retry="never",
            )
        )

    def disable_pack(
        self,
        collection_id: str,
        pack_id: str,
    ) -> StickerCollectionPackBinding:
        """Disable new discovery while preserving historical sticker resolution."""

        return _binding(
            self._transport.request(
                "DELETE",
                f"/sticker-collections/{_collection_id(collection_id)}/packs/{_pack_id(pack_id)}",
                retry="never",
            )
        )
