from __future__ import annotations

import os
from types import TracebackType

import httpx

from .capabilities import CapabilitiesClient
from .jobs import JobsClient
from .transport import Transport
from .uploads import UploadsClient
from .watermark_logo import WatermarkLogoClient
from .webhooks import WebhooksClient

DEFAULT_BASE_URL = "https://mediaruntime.com"


class MediaRuntime:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        webhook_secret: str | None = None,
        timeout: float = 30,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
    ) -> None:
        if timeout <= 0:
            raise TypeError("timeout must be positive")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 10:
            raise TypeError("max_retries must be an integer between 0 and 10")
        self._transport = Transport(
            api_key=api_key or os.getenv("MEDIARUNTIME_API_KEY"),
            base_url=base_url or os.getenv("MEDIARUNTIME_API_URL") or DEFAULT_BASE_URL,
            timeout=timeout,
            max_retries=max_retries,
            client=http_client,
        )
        self.uploads = UploadsClient(self._transport)
        self.jobs = JobsClient(self._transport, self.uploads)
        self.capabilities = CapabilitiesClient(self._transport)
        self.watermark_logo = WatermarkLogoClient(self._transport)
        self.webhooks = WebhooksClient(webhook_secret or os.getenv("MEDIARUNTIME_WEBHOOK_SECRET"))

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> MediaRuntime:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
