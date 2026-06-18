from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from app.services.signing_service import b64url_decode, b64url_encode, canonical_json_bytes, sign_payload, verify_token


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


def manifest_token_to_json(token: str) -> dict[str, Any]:
    payload_b64, signature_b64 = token.strip().split(".", 1)
    payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid manifest payload.")
    payload["signature"] = signature_b64
    return payload


def manifest_json_to_token(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    signature = str(payload.pop("signature", "")).strip()
    if not signature:
        raise ValueError("Manifest signature is missing.")
    return f"{b64url_encode(canonical_json_bytes(payload))}.{signature}"


def fetch_manifest(manifest_url: str, public_key_pem: str, *, timeout: int = 10) -> dict[str, Any]:
    with urlopen(manifest_url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid manifest response.")
    return verify_manifest_token(manifest_json_to_token(payload), public_key_pem)


def update_available(current_version: str, manifest: dict[str, Any]) -> bool:
    return compare_versions(str(manifest.get("version", "")), current_version) > 0


def download_and_verify(manifest: dict[str, Any], target_path: Path, *, timeout: int = 60) -> bool:
    with urlopen(str(manifest["url"]), timeout=timeout) as response:
        data = response.read()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)
    if verify_download_hash(target_path, str(manifest["sha256"])):
        return True
    try:
        target_path.unlink()
    except OSError:
        pass
    return False


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
