from __future__ import annotations

from typing import Any

from ._utils import object_dict, string_list
from .models import Capabilities
from .transport import Transport


def _string_map(value: Any) -> dict[str, str]:
    return {str(key): item for key, item in object_dict(value).items() if isinstance(item, str)}


def _string_list_map(value: Any) -> dict[str, list[str]]:
    return {
        str(key): string_list(item)
        for key, item in object_dict(value).items()
        if isinstance(item, list)
    }


class CapabilitiesClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def retrieve(self) -> Capabilities:
        # Capabilities are public so clients can discover presets before obtaining a key.
        data = object_dict(
            self._transport.request(
                "GET",
                "/capabilities",
                authenticated=False,
                retry="safe",
            )
        )
        return Capabilities(
            capabilities=_string_map(data.get("capabilities")),
            output_types=_string_list_map(data.get("output_types")),
            preset_overrides=_string_list_map(data.get("preset_overrides")),
            public_presets=string_list(data.get("public_presets")),
            presets={
                str(key): object_dict(item)
                for key, item in object_dict(data.get("presets")).items()
            },
            features={
                str(key): object_dict(item)
                for key, item in object_dict(data.get("features")).items()
            },
            output_aliases={
                str(key): object_dict(item)
                for key, item in object_dict(data.get("output_aliases")).items()
            },
            notes=string_list(data.get("notes")),
        )
