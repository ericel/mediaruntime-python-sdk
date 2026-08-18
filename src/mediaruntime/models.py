from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class JobDetails:
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
    data: dict[str, Any]
    raw_body: bytes
