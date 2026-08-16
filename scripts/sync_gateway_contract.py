#!/usr/bin/env python3
"""Synchronize and validate the versioned gateway contract snapshot.

The SDK never reads another repository at runtime. Maintainers use ``--gateway-repo``
when updating the checked-in snapshot; ordinary CI validates the local copy only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ARTIFACTS = ("openapi.json", "conformance.json")
SDK_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = SDK_ROOT / "contracts" / "v1"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Missing contract artifact: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid JSON contract artifact {path}: {error}") from error


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    openapi = _read_json(snapshot_dir / "openapi.json")
    conformance = _read_json(snapshot_dir / "conformance.json")
    if not isinstance(openapi, dict) or not str(openapi.get("openapi", "")).startswith("3."):
        raise SystemExit("contracts/v1/openapi.json is not an OpenAPI 3 document")
    if not isinstance(conformance, dict):
        raise SystemExit("contracts/v1/conformance.json must be a JSON object")
    return {"openapi.json": openapi, "conformance.json": conformance}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gateway-repo",
        type=Path,
        help="Gateway checkout containing contracts/v1 (maintainer use only)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate without writing; with --gateway-repo also reject drift",
    )
    args = parser.parse_args()

    if args.gateway_repo is None:
        _validate_snapshot(SNAPSHOT_DIR)
        for name in ARTIFACTS:
            print(f"{name}: sha256:{_digest((SNAPSHOT_DIR / name).read_bytes())}")
        return 0

    source_dir = args.gateway_repo.resolve() / "contracts" / "v1"
    _validate_snapshot(source_dir)
    if args.check:
        _validate_snapshot(SNAPSHOT_DIR)
        drift = [
            name
            for name in ARTIFACTS
            if (source_dir / name).read_bytes() != (SNAPSHOT_DIR / name).read_bytes()
        ]
        if drift:
            raise SystemExit(
                "Gateway contract snapshot is stale: "
                + ", ".join(drift)
                + ". Run the sync command documented in contracts/README.md."
            )
        print("Gateway contract snapshot is current")
        return 0

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACTS:
        artifact = (source_dir / name).read_bytes()
        (SNAPSHOT_DIR / name).write_bytes(artifact)
        print(f"updated contracts/v1/{name}: sha256:{_digest(artifact)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
