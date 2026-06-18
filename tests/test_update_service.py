from __future__ import annotations

import hashlib
import json
from pathlib import Path

from Crypto.PublicKey import ECC


def _key_pair() -> tuple[str, str]:
    key = ECC.generate(curve="Ed25519")
    return key.export_key(format="PEM"), key.public_key().export_key(format="PEM")


def test_manifest_round_trip_and_version_comparison(tmp_path: Path) -> None:
    from app.services.update_service import (
        build_manifest,
        compare_versions,
        verify_download_hash,
        verify_manifest_token,
    )

    private_pem, public_pem = _key_pair()
    artifact = tmp_path / "StarTrace-1.97.0.exe"
    artifact.write_bytes(b"binary-data")

    token = build_manifest(
        artifact_path=artifact,
        channel="user",
        version="1.97.0",
        base_url="https://cdn.example.com/startrace/user",
        notes="bug fixes",
        private_key_pem=private_pem,
    )

    manifest = verify_manifest_token(token, public_pem)

    assert manifest["channel"] == "user"
    assert manifest["version"] == "1.97.0"
    assert manifest["url"].endswith("/StarTrace-1.97.0.exe")
    assert compare_versions("1.97.0", "1.96.9") > 0
    assert compare_versions("1.97.0", "1.97.0") == 0
    assert compare_versions("1.96.9", "1.97.0") < 0
    assert verify_download_hash(artifact, manifest["sha256"])


def test_manifest_verification_rejects_tampering(tmp_path: Path) -> None:
    from app.services.update_service import build_manifest, verify_manifest_token

    private_pem, public_pem = _key_pair()
    artifact = tmp_path / "StarTrace-1.97.0.exe"
    artifact.write_bytes(b"binary-data")

    token = build_manifest(
        artifact_path=artifact,
        channel="admin",
        version="1.97.0",
        base_url="https://cdn.example.com/startrace/admin",
        notes="admin update",
        private_key_pem=private_pem,
    )
    payload_b64, signature_b64 = token.split(".", 1)
    payload = json.loads(__import__("base64").urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)).decode("utf-8"))
    payload["version"] = "9.99.9"
    tampered_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    tampered_token = (
        __import__("base64").urlsafe_b64encode(tampered_payload).decode("ascii").rstrip("=")
        + "."
        + signature_b64
    )

    try:
        verify_manifest_token(tampered_token, public_pem)
    except ValueError as exc:
        assert "signature" in str(exc).lower()
    else:
        raise AssertionError("tampered manifest must be rejected")


def test_verify_download_hash_detects_corruption(tmp_path: Path) -> None:
    from app.services.update_service import verify_download_hash

    artifact = tmp_path / "StarTrace-1.97.0.exe"
    artifact.write_bytes(b"binary-data")
    expected = hashlib.sha256(b"binary-data").hexdigest()

    assert verify_download_hash(artifact, expected)

    artifact.write_bytes(b"corrupted-data")
    assert not verify_download_hash(artifact, expected)
