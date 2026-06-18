from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.signing_service import sign_payload, verify_token


MANIFEST_SCHEMA = 1


@dataclass(frozen=True)
class UpdateManifest:
    channel: str
    version: str
    min_supported_version: str
    force: bool
    url: str
    sha256: str
    size: int
    notes: str
    published_at: str
    schema: int = MANIFEST_SCHEMA


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def build_manifest(
    *,
    artifact_path: Path,
    channel: str,
    version: str,
    base_url: str,
    notes: str,
    private_key_pem: str,
    min_supported_version: str | None = None,
    force: bool = False,
    published_at: str = "",
) -> str:
    payload = {
        "schema": MANIFEST_SCHEMA,
        "channel": channel,
        "version": version,
        "min_supported_version": min_supported_version or version,
        "force": force,
        "url": f"{base_url.rstrip('/')}/{artifact_path.name}",
        "sha256": sha256_file(artifact_path),
        "size": artifact_path.stat().st_size,
        "notes": notes,
        "published_at": published_at,
    }
    return sign_payload(payload, private_key_pem)


def verify_manifest_token(token: str, public_key_pem: str) -> dict[str, Any]:
    payload = verify_token(token, public_key_pem)
    if int(payload.get("schema", 0)) != MANIFEST_SCHEMA:
        raise ValueError("Unsupported manifest schema.")
    return payload


def verify_download_hash(path: Path, expected_sha256: str) -> bool:
    return sha256_file(path) == expected_sha256.strip().lower()


def compare_versions(left: str, right: str) -> int:
    def parse(value: str) -> tuple[int, ...]:
        parts = []
        for piece in value.split("."):
            try:
                parts.append(int(piece))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    left_parts = parse(left)
    right_parts = parse(right)
    max_len = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (max_len - len(left_parts))
    right_parts += (0,) * (max_len - len(right_parts))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0
