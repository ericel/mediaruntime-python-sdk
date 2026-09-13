from __future__ import annotations

import math
import random
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, NoReturn, cast
from urllib.parse import quote
from uuid import uuid4

from ._utils import bool_or_none, int_or_none, object_dict, string_list, string_or_none
from .errors import JobWaitTimeoutError, ValidationError
from .models import (
    ClipCandidatesResult,
    ClipEmptyReason,
    CodeDetectionResult,
    CompatibilityReportResult,
    JobDetails,
    JobPage,
    JobSummary,
    MediaReportResult,
    ModerationResult,
    RecipeAcknowledgement,
    RetryWebhookResult,
)
from .transport import Transport
from .uploads import Source, UploadsClient

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "REJECTED", "PARTIAL"}
# These aliases are the stable shorthand contract; explicit presets remain gateway-discovered.
OutputAlias = Literal[
    "video.web",
    "video.streaming",
    "video.social",
    "audio.web",
    "audio.transcription",
    "image.web",
]
RECIPE_REFERENCE_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}(?:@[1-9][0-9]*)?$")


def _parse_clip_candidates(value: Any) -> ClipCandidatesResult:
    """Validate source timing before a retrieved plan can be reused in a paid job."""

    def invalid(field: str) -> NoReturn:
        # Never put transcript text or unknown report fields into exception messages.
        raise ValidationError(
            f"Invalid clip candidate response: {field}",
            status=502,
            code="invalid_clip_plan",
            field=f"clip_candidates.{field}",
        )

    def number(value: Any, field: str, minimum: float, maximum: float) -> float:
        if (
            type(value) not in (int, float)
            or not minimum <= value <= maximum
            or not math.isfinite(value)
        ):
            invalid(field)
        return float(value)

    data = object_dict(value)
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        invalid("schema_version")
    if "version" in data and (type(data["version"]) is not int or data["version"] != 1):
        invalid("version")
    if "preset" in data and data["preset"] != "clip_candidates_v1":
        invalid("preset")
    source_duration = number(data.get("source_duration_sec"), "source_duration_sec", 0, 604800)
    if source_duration <= 0:
        invalid("source_duration_sec")
    if data.get("method") != "transcript_heuristics_v1":
        invalid("method")
    if data.get("transcript_source") not in ("supplied", "whisper"):
        invalid("transcript_source")
    if not isinstance(data.get("transcript"), list) or len(data["transcript"]) > 2000:
        invalid("transcript")
    if not isinstance(data.get("candidates"), list) or len(data["candidates"]) > 20:
        invalid("candidates")

    previous_start = -1.0
    text_bytes = 0
    transcript = []
    for index, raw in enumerate(data["transcript"]):
        segment = object_dict(raw)
        field = f"transcript[{index}]"
        start = number(segment.get("start_time_sec"), f"{field}.start_time_sec", 0, 604800)
        # Match the native allowance for the final Whisper cue rounded past the
        # duration, while preserving its source timestamp for later intersection.
        end = number(
            segment.get("end_time_sec"),
            f"{field}.end_time_sec",
            0,
            min(604800, source_duration + 0.1),
        )
        if end <= start or start < previous_start:
            invalid(field)
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            invalid(f"{field}.text")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            invalid(f"{field}.text")
        text_bytes += size
        if size > 2000 or text_bytes > 256 * 1024:
            invalid(f"{field}.text")
        previous_start = start
        transcript.append({"start_time_sec": start, "end_time_sec": end, "text": text})

    candidates = []
    for index, raw in enumerate(data["candidates"]):
        candidate = object_dict(raw)
        field = f"candidates[{index}]"
        start = number(candidate.get("start_time_sec"), f"{field}.start_time_sec", 0, 604800)
        duration = number(candidate.get("duration_sec"), f"{field}.duration_sec", 0, 300)
        if duration <= 0 or start + duration > source_duration + 0.1:
            invalid(field)
        text = candidate.get("text")
        if not isinstance(text, str) or len(text) > 256 * 1024:
            invalid(f"{field}.text")
        score = number(candidate.get("score"), f"{field}.score", 0, 1.7976931348623157e308)
        reasons = candidate.get("reasons")
        if (
            not isinstance(reasons, list)
            or len(reasons) > 20
            or any(not isinstance(reason, str) for reason in reasons)
        ):
            invalid(f"{field}.reasons")
        candidate_id = candidate.get("id")
        if candidate_id is not None and (
            not isinstance(candidate_id, str) or len(candidate_id) > 128
        ):
            invalid(f"{field}.id")
        candidates.append(
            {
                "id": candidate_id,
                "start_time_sec": start,
                "duration_sec": duration,
                "text": text,
                "score": score,
                "reasons": list(reasons),
            }
        )

    # Older reports omit this field. A supplied reason must still be a recognized
    # empty outcome without coercing arbitrary server data into the public type.
    empty_reason = data.get("empty_reason")
    if empty_reason is not None and (
        not isinstance(empty_reason, str)
        or empty_reason
        not in (
            "no_speech",
            "no_keyword_match",
            "no_matching_ranges",
            "source_too_short",
        )
    ):
        invalid("empty_reason")

    # Construct an allowlist instead of retaining arbitrary nested report fields.
    return ClipCandidatesResult(
        schema_version=1,
        source_duration_sec=source_duration,
        method=data["method"],
        transcript_source=data["transcript_source"],
        transcript=transcript,
        candidates=candidates,
        empty_reason=cast(ClipEmptyReason | None, empty_reason),
    )


def _recipe_acknowledgement(value: Any) -> RecipeAcknowledgement | None:
    if not isinstance(value, Mapping):
        return None
    return RecipeAcknowledgement(
        name=str(value.get("name") or ""),
        version=int(value.get("version") or 0),
        reference=str(value.get("reference") or ""),
        built_in=bool(value.get("built_in")),
        sha256=str(value.get("sha256") or ""),
    )


def _job_id(value: str) -> str:
    result = value.strip()
    if not result:
        raise ValidationError("job_id must not be empty", status=400, field="job_id")
    # Treat a caller-provided ID as one path segment even if the input contains delimiters.
    return quote(result, safe="")


def _job_details(value: Any) -> JobDetails:
    data = object_dict(value)
    return JobDetails(
        id=str(data.get("id") or data.get("job_id") or ""),
        status=str(data.get("status") or "UNKNOWN"),
        tier=object_dict(data.get("tier")),
        usage=object_dict(data.get("usage")),
        billing=object_dict(data.get("billing")),
        bundle=object_dict(data.get("bundle")),
        media=object_dict(data.get("media")) if isinstance(data.get("media"), Mapping) else None,
        metadata=object_dict(data.get("metadata")),
        error=string_or_none(data.get("error")),
        created_at=string_or_none(data.get("created_at")),
        updated_at=string_or_none(data.get("updated_at")),
        started_at=string_or_none(data.get("started_at")),
        completed_at=string_or_none(data.get("completed_at")),
        recipe=_recipe_acknowledgement(data.get("recipe")),
        raw=data,
    )


def _moderation(value: Any) -> ModerationResult:
    data = object_dict(value)
    raw_checks = data.get("checks")
    checks = [object_dict(item) for item in raw_checks] if isinstance(raw_checks, list) else []
    return ModerationResult(
        verdict=string_or_none(data.get("verdict")),
        mode=string_or_none(data.get("mode")),
        media_type=string_or_none(data.get("media_type")),
        requested_checks=string_list(data.get("requested_checks")),
        flagged_checks=string_list(data.get("flagged_checks")),
        review_only_checks=string_list(data.get("review_only_checks")),
        checks=checks,
        judge=object_dict(data.get("judge")) if isinstance(data.get("judge"), Mapping) else None,
        ok=bool_or_none(data.get("ok")),
        error=string_or_none(data.get("error")),
        raw=data,
    )


class Job:
    def __init__(
        self,
        *,
        id: str,
        status: str,
        tier: str,
        required_tier: str | None,
        outputs: list[dict[str, Any]],
        message: str,
        recipe: RecipeAcknowledgement | None,
        jobs: JobsClient,
    ) -> None:
        self.id = id
        self.status = status
        self.tier = tier
        self.required_tier = required_tier
        self.outputs = outputs
        self.message = message
        self.recipe = recipe
        self._jobs = jobs

    def refresh(self) -> JobDetails:
        return self._jobs.get(self.id)

    def wait(
        self,
        *,
        timeout: float = 300,
        initial_delay: float = 1,
        max_delay: float = 10,
    ) -> JobDetails:
        return self._jobs.wait(
            self.id,
            timeout=timeout,
            initial_delay=initial_delay,
            max_delay=max_delay,
        )


class JobsClient:
    def __init__(self, transport: Transport, uploads: UploadsClient) -> None:
        self._transport = transport
        self._uploads = uploads

    def create(
        self,
        *,
        source: Source | None = None,
        inputs: Sequence[Mapping[str, Any]] | None = None,
        outputs: Sequence[Mapping[str, Any] | OutputAlias] | None = None,
        webhook_url: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        moderation: Mapping[str, Any] | None = None,
        watermark: Mapping[str, Any] | None = None,
        recipe: str | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        if (source is None) == (inputs is None):
            raise ValidationError(
                "Provide exactly one of source or inputs",
                status=400,
                field="source",
            )
        if inputs is not None and not 1 <= len(inputs) <= 25:
            raise ValidationError(
                "inputs must contain between 1 and 25 items",
                status=400,
                field="inputs",
            )
        normalized_recipe = recipe.strip() if recipe is not None else None
        if normalized_recipe is not None and not RECIPE_REFERENCE_RE.fullmatch(normalized_recipe):
            raise ValidationError(
                "recipe must be a valid name or name@version",
                status=400,
                field="recipe",
            )
        if normalized_recipe is not None and (outputs or moderation or watermark):
            raise ValidationError(
                "recipe cannot be combined with outputs, moderation, or watermark",
                status=400,
                field="recipe",
            )
        if outputs is not None and len(outputs) > 10:
            raise ValidationError(
                "outputs must not contain more than 10 items",
                status=400,
                field="outputs",
            )
        analysis_only = moderation is not None and moderation.get("enabled") is True
        if normalized_recipe is None and not outputs and not analysis_only:
            raise ValidationError(
                "Provide at least one output, or enable moderation for an analysis-only job",
                status=400,
                field="outputs",
            )
        caller_key = idempotency_key.strip() if idempotency_key is not None else None
        if caller_key is not None and not 1 <= len(caller_key) <= 255:
            raise ValidationError(
                "idempotency_key must contain between 1 and 255 characters",
                status=400,
                field="idempotency_key",
            )
        # One opaque key protects retries made by this live invocation. It is deliberately
        # not retained on Job and does not replace a caller's durable business key.
        key = caller_key if caller_key is not None else str(uuid4())

        serialized_outputs: list[dict[str, Any] | str] = []
        for item in outputs or []:
            serialized_outputs.append(item if isinstance(item, str) else dict(item))
        body: dict[str, Any] = {}
        if normalized_recipe is not None:
            body["recipe"] = normalized_recipe
        else:
            body["outputs"] = serialized_outputs
        if source is not None:
            # Local paths upload transparently; public, signed, and gs:// sources pass through.
            body["source"] = self._uploads.resolve_source(source)
        else:
            resolved_inputs: list[dict[str, Any]] = []
            for item in inputs or []:
                if "source" not in item:
                    raise ValidationError(
                        "Each input requires source",
                        status=400,
                        field="inputs",
                    )
                raw_source = item["source"]
                if not isinstance(raw_source, (str, Path)):
                    raise ValidationError(
                        "Each input source must be a URL or local path",
                        status=400,
                        field="inputs",
                    )
                resolved = {"source": self._uploads.resolve_source(raw_source)}
                if "input_id" in item:
                    resolved["input_id"] = item["input_id"]
                if "metadata" in item:
                    resolved["metadata"] = item["metadata"]
                resolved_inputs.append(resolved)
            body["inputs"] = resolved_inputs
        for name, value in {
            "webhook_url": webhook_url,
            "metadata": dict(metadata) if metadata is not None else None,
            "moderation": dict(moderation) if moderation is not None else None,
            "watermark": dict(watermark) if watermark is not None else None,
        }.items():
            if value is not None:
                body[name] = value

        value = object_dict(
            self._transport.request(
                "POST",
                "/jobs",
                body=body,
                headers={"Idempotency-Key": key},
                retry="idempotent-submit",
                operation="create-job",
            )
        )
        return Job(
            id=str(value.get("id") or value.get("job_id") or ""),
            status=str(value.get("status") or "UNKNOWN"),
            tier=str(value.get("tier") or ""),
            required_tier=string_or_none(value.get("required_tier")),
            outputs=[
                object_dict(item) for item in value.get("outputs", []) if isinstance(item, Mapping)
            ],
            message=str(value.get("msg") or value.get("message") or ""),
            recipe=_recipe_acknowledgement(value.get("recipe")),
            jobs=self,
        )

    def get(self, job_id: str) -> JobDetails:
        return _job_details(
            self._transport.request("GET", f"/jobs/{_job_id(job_id)}", retry="safe")
        )

    def list(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> JobPage:
        data = object_dict(
            self._transport.request(
                "GET",
                "/jobs",
                query={"status": status, "limit": limit, "cursor": cursor},
                retry="safe",
            )
        )
        raw_jobs = data.get("jobs")
        jobs = []
        if isinstance(raw_jobs, list):
            for item in raw_jobs:
                raw = object_dict(item)
                jobs.append(
                    JobSummary(
                        id=str(raw.get("id") or raw.get("job_id") or ""),
                        status=str(raw.get("status") or "UNKNOWN"),
                        raw=raw,
                    )
                )
        return JobPage(jobs=jobs, next_cursor=string_or_none(data.get("next_cursor")))

    def wait(
        self,
        job_id: str,
        *,
        timeout: float = 300,
        initial_delay: float = 1,
        max_delay: float = 10,
    ) -> JobDetails:
        if timeout <= 0 or initial_delay < 0 or max_delay < 0:
            raise TypeError("wait timing options must be non-negative and timeout must be positive")
        deadline = time.monotonic() + timeout
        delay = initial_delay
        last_job: JobDetails | None = None
        while True:
            last_job = self.get(job_id)
            if last_job.status.upper() in TERMINAL_STATUSES:
                return last_job
            # Monotonic time avoids wall-clock changes; jitter prevents synchronized polling.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JobWaitTimeoutError(timeout, last_job)
            time.sleep(min(remaining, delay * random.uniform(0.85, 1.15)))
            delay = min(max_delay, max(0.001, delay * 1.5))

    def get_moderation(self, job_id: str) -> ModerationResult:
        return _moderation(
            self._transport.request(
                "GET",
                f"/jobs/{_job_id(job_id)}/moderation",
                retry="safe",
            )
        )

    def get_media_report(self, job_id: str) -> MediaReportResult:
        data = object_dict(
            self._transport.request(
                "GET",
                f"/jobs/{_job_id(job_id)}/media-report",
                retry="safe",
            )
        )
        # download_url is signed and time-limited; report is the durable parsed representation.
        return MediaReportResult(
            job_id=str(data.get("job_id") or job_id),
            report=object_dict(data.get("report"))
            if isinstance(data.get("report"), Mapping)
            else None,
            download_url=string_or_none(data.get("download_url")),
            note=string_or_none(data.get("note")),
        )

    def get_compatibility_report(self, job_id: str) -> CompatibilityReportResult:
        data = object_dict(
            self._transport.request(
                "GET",
                f"/jobs/{_job_id(job_id)}/compatibility-report",
                retry="safe",
            )
        )
        return CompatibilityReportResult(
            job_id=str(data.get("job_id") or job_id),
            report=object_dict(data.get("report"))
            if isinstance(data.get("report"), Mapping)
            else None,
            download_url=string_or_none(data.get("download_url")),
            note=string_or_none(data.get("note")),
        )

    def get_clip_candidates(self, job_id: str) -> ClipCandidatesResult:
        """Fetch the editable plan. Reuse its transcript to render without another ASR pass."""
        return _parse_clip_candidates(
            self._transport.request("GET", f"/jobs/{_job_id(job_id)}/clip-candidates", retry="safe")
        )

    def get_code_detections(self, job_id: str) -> CodeDetectionResult:
        """Return the inert QR/barcode detection report for a completed job."""
        data = object_dict(
            self._transport.request(
                "GET",
                f"/jobs/{_job_id(job_id)}/codes",
                retry="safe",
            )
        )
        return CodeDetectionResult(
            job_id=str(data.get("job_id") or job_id),
            report=object_dict(data.get("report"))
            if isinstance(data.get("report"), Mapping)
            else None,
            download_url=string_or_none(data.get("download_url")),
            note=string_or_none(data.get("note")),
        )

    def retry_webhook(self, job_id: str) -> RetryWebhookResult:
        data = object_dict(
            self._transport.request(
                "POST",
                f"/jobs/{_job_id(job_id)}/retry-webhook",
                retry="never",
            )
        )
        return RetryWebhookResult(
            status=str(data.get("status") or ""),
            message=str(data.get("msg") or data.get("message") or ""),
            attempts=int(data.get("attempts") or 0),
            http_status=int_or_none(data.get("http_status")),
        )
