from __future__ import annotations

import random
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

from ._utils import bool_or_none, int_or_none, object_dict, string_list, string_or_none
from .errors import JobWaitTimeoutError, ValidationError
from .models import (
    JobDetails,
    JobPage,
    JobSummary,
    MediaReportResult,
    ModerationResult,
    RetryWebhookResult,
)
from .transport import Transport
from .uploads import Source, UploadsClient

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "REJECTED", "PARTIAL"}
OutputAlias = Literal[
    "video.web",
    "video.streaming",
    "video.social",
    "audio.web",
    "audio.transcription",
    "image.web",
]


def _job_id(value: str) -> str:
    result = value.strip()
    if not result:
        raise ValidationError("job_id must not be empty", status=400, field="job_id")
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
        jobs: JobsClient,
    ) -> None:
        self.id = id
        self.status = status
        self.tier = tier
        self.required_tier = required_tier
        self.outputs = outputs
        self.message = message
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
        if outputs is not None and len(outputs) > 10:
            raise ValidationError(
                "outputs must not contain more than 10 items",
                status=400,
                field="outputs",
            )
        if not outputs and not (moderation and moderation.get("enabled") is True):
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
        body: dict[str, Any] = {"outputs": serialized_outputs}
        if source is not None:
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
        return MediaReportResult(
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
