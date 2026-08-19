from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from ._utils import object_dict
from .errors import ValidationError
from .models import HostedRecipe
from .transport import Transport

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


def _name(value: str) -> str:
    normalized = value.strip()
    if not NAME_RE.fullmatch(normalized):
        raise ValidationError(
            "recipe name must use lowercase letters, numbers, and hyphens",
            status=400,
            field="name",
        )
    return quote(normalized, safe="")


def _recipe(value: Any) -> HostedRecipe:
    data = object_dict(value)
    template = data.get("template")
    return HostedRecipe(
        name=str(data.get("name") or ""),
        version=int(data.get("version") or data.get("latest_version") or 0),
        reference=str(data.get("reference") or ""),
        description=str(data.get("description") or ""),
        built_in=bool(data.get("built_in")),
        status=str(data.get("status") or "unknown"),
        sha256=str(data.get("sha256") or ""),
        template=dict(template) if isinstance(template, Mapping) else None,
        raw=data,
    )


class RecipesClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def list(self) -> list[HostedRecipe]:
        data = object_dict(self._transport.request("GET", "/recipes", retry="safe"))
        rows = data.get("recipes")
        return [_recipe(item) for item in rows] if isinstance(rows, list) else []

    def get(self, name: str, *, version: int | None = None) -> HostedRecipe:
        if version is not None and version < 1:
            raise ValidationError("version must be at least 1", status=400, field="version")
        path = f"/recipes/{_name(name)}"
        if version is not None:
            path += f"/versions/{version}"
        return _recipe(self._transport.request("GET", path, retry="safe"))

    def create(
        self,
        *,
        name: str,
        description: str,
        template: Mapping[str, Any],
    ) -> HostedRecipe:
        normalized_name = _name(name)
        return _recipe(
            self._transport.request(
                "POST",
                "/recipes",
                body={
                    "name": normalized_name,
                    "description": description,
                    "template": dict(template),
                },
                retry="never",
            )
        )

    def create_version(
        self,
        name: str,
        *,
        expected_latest_version: int,
        template: Mapping[str, Any],
        description: str | None = None,
    ) -> HostedRecipe:
        if expected_latest_version < 1:
            raise ValidationError(
                "expected_latest_version must be at least 1",
                status=400,
                field="expected_latest_version",
            )
        body: dict[str, Any] = {
            "expected_latest_version": expected_latest_version,
            "template": dict(template),
        }
        if description is not None:
            body["description"] = description
        return _recipe(
            self._transport.request(
                "POST",
                f"/recipes/{_name(name)}/versions",
                body=body,
                retry="never",
            )
        )

    def archive(self, name: str) -> dict[str, Any]:
        return object_dict(
            self._transport.request(
                "DELETE",
                f"/recipes/{_name(name)}",
                retry="never",
            )
        )
