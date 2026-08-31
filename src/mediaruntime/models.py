from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

PrivacyDetector = Literal["face", "license_plate", "text"]
StickerCollectionStatus = Literal["active", "archived"]
StickerBindingStatus = Literal["enabled", "disabled"]
StickerHistoricalAccess = Literal["preserve", "revoke"]
StickerRuntimeScope = Literal[
    "packs:read",
    "stickers:search",
    "stickers:read",
    "assets:resolve",
]
StickerVariantName = Literal[
    "animated",
    "reduced_motion",
    "small_80",
    "small_100",
    "small_160",
    "thumbnail",
]


class _PrivacyRedactionOptional(TypedDict, total=False):
    style: Literal["blur", "pixelate", "solid"]
    failure_mode: Literal["fail_closed", "report_only"]
    min_confidence: float
    sample_interval_sec: float
    max_frames: int
    box_padding_ratio: float
    solid_color: str
    pixel_block_size: int
    privacy_strength: Literal["standard", "strong"]
    include_debug_observations: bool


class PrivacyRedactionOptions(_PrivacyRedactionOptional):
    """Premium Preview accepted on still-image inputs with image outputs only."""

    detectors: list[PrivacyDetector]


@dataclass(frozen=True, slots=True)
class JobDetails:
    # `raw` preserves additive contract fields without weakening the typed stable surface.
    id: str
    status: str
    tier: dict[str, Any]
    usage: dict[str, Any]
    billing: dict[str, Any]
    bundle: dict[str, Any]
    media: dict[str, Any] | None
    metadata: dict[str, Any]
    error: str | None
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    completed_at: str | None
    recipe: RecipeAcknowledgement | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RecipeAcknowledgement:
    name: str
    version: int
    reference: str
    built_in: bool
    sha256: str


@dataclass(frozen=True, slots=True)
class HostedRecipe:
    name: str
    version: int
    reference: str
    description: str
    built_in: bool
    status: str
    sha256: str
    template: dict[str, Any] | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class JobSummary:
    id: str
    status: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class JobPage:
    jobs: list[JobSummary]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ModerationResult:
    verdict: str | None
    mode: str | None
    media_type: str | None
    requested_checks: list[str]
    flagged_checks: list[str]
    review_only_checks: list[str]
    checks: list[dict[str, Any]]
    judge: dict[str, Any] | None
    ok: bool | None
    error: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MediaReportResult:
    job_id: str
    report: dict[str, Any] | None
    download_url: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class CompatibilityReportResult:
    job_id: str
    report: dict[str, Any] | None
    download_url: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class CodeDetectionResult:
    job_id: str
    report: dict[str, Any] | None
    download_url: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class RetryWebhookResult:
    status: str
    message: str
    attempts: int
    http_status: int | None


@dataclass(frozen=True, slots=True)
class UploadTarget:
    upload_url: str
    file_uri: str
    upload_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class UploadFileResult(UploadTarget):
    filename: str
    content_type: str


@dataclass(frozen=True, slots=True)
class WatermarkLogo:
    logo_url: str
    position: str
    opacity_pct: float
    scale_pct: float


@dataclass(frozen=True, slots=True)
class Capabilities:
    capabilities: dict[str, str]
    output_types: dict[str, list[str]]
    preset_overrides: dict[str, list[str]]
    public_presets: list[str]
    presets: dict[str, dict[str, Any]]
    features: dict[str, dict[str, Any]]
    output_aliases: dict[str, dict[str, Any]]
    notes: list[str]


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    id: str
    job_id: str
    account_id: str | None
    status: str
    type: str
    recipe: RecipeAcknowledgement | None
    data: dict[str, Any]
    raw_body: bytes


@dataclass(frozen=True, slots=True)
class StickerCollectionPackBinding:
    """A retained link between an application collection and a paid pack activation."""

    binding_id: str
    collection_id: str
    activation_id: str
    pack_id: str
    pack_slug: str
    pack_name: str
    pack_version: str
    status: StickerBindingStatus
    historical_access: StickerHistoricalAccess
    first_enabled_at: str | None
    enabled_at: str | None
    disabled_at: str | None
    updated_at: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerCollection:
    """Application-scoped runtime configuration with its currently enabled packs."""

    collection_id: str
    workspace_id: str
    name: str
    description: str
    status: StickerCollectionStatus
    packs: list[StickerCollectionPackBinding]
    created_at: str
    archived_at: str | None
    updated_at: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerCollectionPage:
    """Bounded collection results returned for one workspace."""

    items: list[StickerCollection]
    total: int


@dataclass(frozen=True, slots=True)
class StickerCollectionPackBindingPage:
    """Enabled and disabled binding history for one collection."""

    items: list[StickerCollectionPackBinding]
    total: int


@dataclass(frozen=True, slots=True)
class StickerRuntimeCharacter:
    """A character family represented in an enabled runtime pack."""

    id: str
    name: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimePack:
    """Published pack metadata available for new use in one collection."""

    pack_id: str
    slug: str
    name: str
    version: str
    asset_count: int
    animated: bool
    categories: list[str]
    characters: list[StickerRuntimeCharacter]
    activation_id: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimePackPage:
    """Collection-enabled runtime packs and their reported total."""

    items: list[StickerRuntimePack]
    total: int


@dataclass(frozen=True, slots=True)
class StickerRuntimeVariant:
    """Approved private representation metadata without its storage object key."""

    name: StickerVariantName
    state: str
    media_type: Literal["image/webp"]
    bytes: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimeSticker:
    """Stable sticker metadata suitable for persistence in an application record."""

    sticker_id: str
    semantic_id: str
    pack_id: str
    pack_slug: str
    pack_version: str
    label: str
    emoji: str | None
    category: str | None
    keywords: list[str]
    animated: bool
    variants: list[StickerRuntimeVariant]
    score: int | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimeSearchResult:
    """Deterministically ranked sticker matches for a normalized query."""

    query: str
    items: list[StickerRuntimeSticker]
    total: int


@dataclass(frozen=True, slots=True)
class StickerRuntimeTypeaheadSuggestion:
    """A catalog-derived search suggestion and its matching asset count."""

    text: str
    asset_count: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimeTypeaheadResult:
    """Locale-aware suggestions for a normalized prefix."""

    query: str
    locale: str
    suggestions: list[StickerRuntimeTypeaheadSuggestion]


@dataclass(frozen=True, slots=True)
class StickerRuntimeAsset:
    """A short-lived, integrity-pinned delivery authorization for one WebP variant."""

    sticker_id: str
    pack_id: str
    pack_version: str
    variant: str
    media_type: Literal["image/webp"]
    bytes: int
    sha256: str
    url: str
    expires_in_seconds: int
    expires_at: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimeClientToken:
    """Short-lived bearer credential restricted to one collection and scope set."""

    access_token: str
    token_type: Literal["Bearer"]
    expires_in: int
    expires_at: str
    collection_id: str
    scopes: list[StickerRuntimeScope]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StickerRuntimeUsage:
    """Current workspace operation and authorized-delivery usage totals."""

    month: str
    operations: int
    included_operations: int
    remaining_operations: int
    operations_utilization_percent: float
    authorized_delivery_bytes: int
    included_delivery_bytes: int
    remaining_delivery_bytes: int
    delivery_utilization_percent: float
    overage_charged_cents: int
    currency: Literal["USD"]
    status: Literal["healthy", "approaching_limit", "overage"]
    raw: dict[str, Any]
