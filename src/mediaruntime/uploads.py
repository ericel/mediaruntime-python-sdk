from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ._utils import object_dict
from .errors import ValidationError
from .models import UploadFileResult, UploadTarget
from .transport import Transport

Source = str | Path


def _target(value: Any) -> UploadTarget:
    data = object_dict(value)
    raw_headers = object_dict(data.get("upload_headers"))
    return UploadTarget(
        upload_url=str(data.get("upload_url") or ""),
        file_uri=str(data.get("file_uri") or ""),
        upload_headers={
            str(key): item for key, item in raw_headers.items() if isinstance(item, str)
        },
    )


class UploadsClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def create_target(
        self,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> UploadTarget:
        if not filename.strip():
            raise ValidationError("filename must not be empty", status=400, field="filename")
        return _target(
            self._transport.request(
                "POST",
                "/upload-url",
                body={"filename": filename, "content_type": content_type},
                retry="never",
            )
        )

    def upload_file(self, path: str | Path, *, content_type: str | None = None) -> UploadFileResult:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValidationError(
                f"Source is not a regular file: {source}",
                status=400,
                field="source",
            )
        resolved_type = (
            content_type or mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        )
        # The API supplies the exact signed destination and any storage-provider headers.
        target = self.create_target(source.name, resolved_type)
        headers = dict(target.upload_headers)
        headers.setdefault("Content-Length", str(source.stat().st_size))
        with source.open("rb") as handle:
            self._transport.upload(target.upload_url, content=handle, headers=headers)
        # Jobs consume file_uri; upload_url is an expiring transport detail returned for audit.
        return UploadFileResult(
            upload_url=target.upload_url,
            file_uri=target.file_uri,
            upload_headers=target.upload_headers,
            filename=source.name,
            content_type=resolved_type,
        )

    def resolve_source(self, source: Source) -> str:
        value = str(source).strip()
        if not value:
            raise ValidationError("source must not be empty", status=400, field="source")
        parsed = urlparse(value)
        # Hosted sources pass through; local paths are uploaded and replaced with private URIs.
        if parsed.scheme.lower() in {"http", "https", "gs"}:
            return value
        if parsed.scheme.lower() == "file":
            return self.upload_file(Path(parsed.path)).file_uri
        if parsed.scheme:
            raise ValidationError(
                f"Unsupported source protocol: {parsed.scheme}",
                status=400,
                field="source",
            )
        return self.upload_file(value).file_uri
