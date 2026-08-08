import hashlib

from fastapi.testclient import TestClient

from license_test_utils import LicenseSigner
from server_api.main import create_app


def test_updates_manifest_and_artifact_require_jwt_and_stay_inside_release_directory(tmp_path):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    artifact_bytes = b"artifact"
    (release_dir / "latest.json").write_text(
        '{"version":"2.0.0","url":"https://cdn.example/StarTrace-2.0.0.exe",'
        f'"size":{len(artifact_bytes)},"sha256":"{hashlib.sha256(artifact_bytes).hexdigest()}","signature":"sig"}}',
        encoding="utf-8",
    )
    (release_dir / "StarTrace-2.0.0.exe").write_bytes(artifact_bytes)
    (release_dir / "unpublished.exe").write_bytes(b"not-for-release")
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
        update_release_dir=str(release_dir),
    )
    with TestClient(app) as client:
        assert client.get("/v1/updates/manifest").status_code == 401
        token = client.post("/v1/auth/session", json={"machine_code": "update-machine", "license_token": signer.sign("update-machine")}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/v1/updates/manifest", headers=headers).json()["version"] == "2.0.0"
        artifact = client.get("/v1/updates/files/StarTrace-2.0.0.exe", headers=headers)
        assert artifact.status_code == 200
        assert artifact.content == b"artifact"
        assert client.get("/v1/updates/files/unpublished.exe", headers=headers).status_code == 404
        assert client.get("/v1/updates/files/..%2Flatest.json", headers=headers).status_code == 404


def test_updates_manifest_rejects_missing_signed_artifact_metadata(tmp_path):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    (release_dir / "latest.json").write_text(
        '{"version":"2.0.0","url":"https://cdn.example/update.exe","signature":"sig"}',
        encoding="utf-8",
    )
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
        update_release_dir=str(release_dir),
    )
    with TestClient(app) as client:
        token = client.post(
            "/v1/auth/session",
            json={"machine_code": "update-machine", "license_token": signer.sign("update-machine")},
        ).json()["access_token"]
        response = client.get(
            "/v1/updates/manifest",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503


def test_download_page_returns_html_with_setup_link(tmp_path):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    (release_dir / "latest.json").write_text(
        '{"version":"2.0.1","url":"http://127.0.0.1:8080/v1/updates/files/StarTrace-Setup-2.0.1.exe",'
        f'"size":1,"sha256":"{"0" * 64}","signature":"sig"}}',
        encoding="utf-8",
    )
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
        update_release_dir=str(release_dir),
    )
    with TestClient(app) as client:
        resp = client.get("/download")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "StarTrace-Setup-2.0.1.exe" in resp.text
