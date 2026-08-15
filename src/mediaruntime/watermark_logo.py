from __future__ import annotations

from pathlib import Path

from ._utils import object_dict
from .errors import ValidationError
from .models import UploadTarget, WatermarkLogo
from .transport import Transport


def _target(value: object) -> UploadTarget:
    data = object_dict(value)
    raw_headers = object_dict(data.get("upload_headers"))
    return UploadTarget(
        upload_url=str(data.get("upload_url") or ""),
        file_uri=str(data.get("file_uri") or ""),
        upload_headers={
            str(key): item for key, item in raw_headers.items() if isinstance(item, str)
        },
    )


def _logo(value: object) -> WatermarkLogo:
    data = object_dict(value)
    return WatermarkLogo(
        logo_url=str(data.get("logo_url") or ""),
        position=str(data.get("position") or "bottom_right"),
        opacity_pct=float(data.get("opacity_pct") or 100),
        scale_pct=float(data.get("scale_pct") or 12),
    )


class WatermarkLogoClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def create_upload_target(self, content_type: str = "image/png") -> UploadTarget:
        return _target(
            self._transport.request(
                "POST",
                "/account/watermark-logo/upload-url",
                body={"content_type": content_type},
                retry="never",
            )
        )

    def confirm(
        self,
        *,
        file_uri: str,
        position: str = "bottom_right",
        opacity_pct: float = 100,
        scale_pct: float = 12,
    ) -> WatermarkLogo:
        return _logo(
            self._transport.request(
                "POST",
                "/account/watermark-logo/confirm",
                body={
                    "file_uri": file_uri,
                    "position": position,
                    "opacity_pct": opacity_pct,
                    "scale_pct": scale_pct,
                },
                retry="never",
            )
        )

    def upload(
        self,
        path: str | Path,
        *,
        position: str = "bottom_right",
        opacity_pct: float = 100,
        scale_pct: float = 12,
    ) -> WatermarkLogo:
        source = Path(path).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".png":
            raise ValidationError("Watermark logo must be a PNG file", status=400, field="path")
        target = self.create_upload_target()
        headers = dict(target.upload_headers)
        headers.setdefault("Content-Length", str(source.stat().st_size))
        with source.open("rb") as handle:
            self._transport.upload(target.upload_url, content=handle, headers=headers)
        return self.confirm(
            file_uri=target.file_uri,
            position=position,
            opacity_pct=opacity_pct,
            scale_pct=scale_pct,
        )
