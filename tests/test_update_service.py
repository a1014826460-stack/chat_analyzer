from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.error import URLError

from Crypto.PublicKey import ECC
import pytest


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


def test_signed_manifest_json_fetch_and_download_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.update_service import (
        download_and_verify,
        fetch_manifest,
        manifest_token_to_json,
        update_available,
    )

    private_pem, public_pem = _key_pair()
    artifact = tmp_path / "StarTrace-1.98.0.exe"
    artifact.write_bytes(b"new-binary")
    token = __import__("app.services.update_service", fromlist=["build_manifest"]).build_manifest(
        artifact_path=artifact,
        channel="user",
        version="1.98.0",
        base_url="https://cdn.example.com/startrace/user",
        notes="new build",
        private_key_pem=private_pem,
    )
    manifest_json = manifest_token_to_json(token)

    class Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    def fake_urlopen(url: str, timeout: int = 10) -> Response:
        if url.endswith("latest.json"):
            return Response(json.dumps(manifest_json).encode("utf-8"))
        if url.endswith("StarTrace-1.98.0.exe"):
            return Response(b"new-binary")
        raise URLError("unexpected url")

    monkeypatch.setattr("app.services.update_service.urlopen", fake_urlopen)

    manifest = fetch_manifest("https://cdn.example.com/startrace/user/latest.json", public_pem)
    target = tmp_path / "downloaded.exe"

    assert update_available("1.97.0", manifest)
    assert download_and_verify(manifest, target)
    assert target.read_bytes() == b"new-binary"


def test_build_config_artifact_name_tracks_edition(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import build_config

    monkeypatch.setattr(build_config, "APP_VERSION", "2.0.0")
    monkeypatch.setattr(build_config, "IS_ADMIN_VERSION", False)
    assert build_config.artifact_name() == "StarTrace-2.0.0"

    monkeypatch.setattr(build_config, "IS_ADMIN_VERSION", True)
    assert build_config.artifact_name() == "StarTrace-Admin-2.0.0"
