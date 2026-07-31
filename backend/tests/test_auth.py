from fastapi.testclient import TestClient

from server_api.main import create_app
from license_test_utils import LicenseSigner


def test_signed_local_user_license_creates_online_session_and_can_be_revoked(tmp_path):
    machine_code = "local-license-machine"
    signer = LicenseSigner()
    license_token = signer.sign(machine_code, license_id="online-license-1")
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        created = client.post("/v1/auth/session", json={
            "machine_code": machine_code,
            "license_token": license_token,
        })
        assert created.status_code == 200
        assert created.json()["access_token"]
        authorization_id = created.json()["authorization_id"]

        assert client.post(
            f"/v1/admin/activation-codes/{authorization_id}/revoke",
            headers={"X-Admin-Token": "development-admin-token"},
        ).status_code == 204
        rejected = client.post("/v1/auth/session", json={
            "machine_code": machine_code,
            "license_token": license_token,
        })
        assert rejected.status_code == 403


def test_online_session_rejects_tampered_expired_wrong_machine_or_non_user_license(tmp_path):
    signer = LicenseSigner()
    token = signer.sign("licensed-machine")
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        attempts = [
            {"machine_code": "other-machine", "license_token": token},
            {"machine_code": "licensed-machine", "license_token": token[:-1] + "A"},
            {"machine_code": "licensed-machine", "license_token": signer.sign("licensed-machine", expires_in_seconds=-1)},
            {"machine_code": "licensed-machine", "license_token": signer.sign("licensed-machine", edition="admin")},
        ]
        assert [client.post("/v1/auth/session", json=value).status_code for value in attempts] == [403, 403, 403, 403]


def test_signed_license_session_enforces_single_device_limit(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        first = client.post(
            "/v1/auth/session",
            json={"machine_code": "machine-a", "license_token": signer.sign("machine-a", license_id="same-license")},
        )
        assert first.status_code == 200
        assert first.json()["access_token"]

        second = client.post(
            "/v1/auth/session",
            json={"machine_code": "machine-b", "license_token": signer.sign("machine-b", license_id="same-license")},
        )
        assert second.status_code == 403
        assert second.json()["detail"] == "设备数量已达到授权上限"


def test_revoked_or_expired_signed_license_cannot_create_a_session(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        expired = client.post("/v1/auth/session", json={
            "machine_code": "machine-a", "license_token": signer.sign("machine-a", expires_in_seconds=-1),
        })
        assert expired.status_code == 403

        active_token = signer.sign("machine-a", license_id="revoked-license")
        activation_id = client.post("/v1/auth/session", json={"machine_code": "machine-a", "license_token": active_token}).json()["authorization_id"]
        revoke = client.post(f"/v1/admin/activation-codes/{activation_id}/revoke", headers={"X-Admin-Token": "development-admin-token"})
        assert revoke.status_code == 204
        revoked = client.post("/v1/auth/session", json={
            "machine_code": "machine-a", "license_token": active_token,
        })
        assert revoked.status_code == 403


def test_logout_revokes_its_jwt_in_redis_and_rejects_later_requests(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        token = client.post("/v1/auth/session", json={
            "machine_code": "logout-machine", "license_token": signer.sign("logout-machine"),
        }).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert client.delete("/v1/auth/session", headers=headers).status_code == 204
        assert client.get("/v1/audit-events", headers=headers).status_code == 401


def test_auth_session_rate_limits_repeated_requests_by_machine_code(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
        auth_session_limit=2,
        auth_session_window_seconds=60,
    )
    with TestClient(app) as client:
        payload = {"machine_code": "rate-machine", "license_token": signer.sign("rate-machine")}

        assert client.post("/v1/auth/session", json=payload).status_code == 200
        assert client.post("/v1/auth/session", json=payload).status_code == 200
        assert client.post("/v1/auth/session", json=payload).status_code == 429
