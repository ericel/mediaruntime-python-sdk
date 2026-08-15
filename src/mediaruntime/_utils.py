from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def object_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return int(value) if isinstance(value, (int, float)) else None


def bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
