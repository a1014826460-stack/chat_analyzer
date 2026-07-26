from datetime import timedelta

from fastapi.testclient import TestClient
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa
import base64
import json

from server_api.main import create_app


def _signed_license(*, machine_code: str, expires_in_seconds: int = 3600, edition: str = "user") -> tuple[str, str]:
    private = ECC.generate(curve="Ed25519")
    payload = {
        "license_id": "online-license-1",
        "edition": edition,
        "schema": 1,
        "machine_code": machine_code,
        "expires_at": (__import__("datetime").datetime.now() + timedelta(seconds=expires_in_seconds)).isoformat(),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(private, "rfc8032").sign(raw)
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"{encode(raw)}.{encode(signature)}", private.public_key().export_key(format="PEM")


def test_signed_local_user_license_creates_online_session_and_can_be_revoked(tmp_path):
    machine_code = "local-license-machine"
    license_token, public_key = _signed_license(machine_code=machine_code)
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=public_key,
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
    token, public_key = _signed_license(machine_code="licensed-machine")
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        license_public_key_pem=public_key,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        attempts = [
            {"machine_code": "other-machine", "license_token": token},
            {"machine_code": "licensed-machine", "license_token": token[:-1] + "A"},
            {"machine_code": "licensed-machine", "license_token": _signed_license(machine_code="licensed-machine", expires_in_seconds=-1)[0]},
            {"machine_code": "licensed-machine", "license_token": _signed_license(machine_code="licensed-machine", edition="admin")[0]},
        ]
        assert [client.post("/v1/auth/session", json=value).status_code for value in attempts] == [403, 403, 403, 403]


def test_activation_and_session_enforce_single_device_limit(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        created = client.post(
            "/v1/admin/activation-codes",
            headers={"X-Admin-Token": "development-admin-token"},
            json={"activation_code": "TEST-CODE", "expires_in_seconds": 3600, "max_devices": 1},
        )
        assert created.status_code == 201

        first = client.post(
            "/v1/auth/session",
            json={"machine_code": "machine-a", "activation_code": "TEST-CODE"},
        )
        assert first.status_code == 200
        assert first.json()["access_token"]

        second = client.post(
            "/v1/auth/session",
            json={"machine_code": "machine-b", "activation_code": "TEST-CODE"},
        )
        assert second.status_code == 403
        assert second.json()["detail"] == "设备数量已达到授权上限"


def test_revoked_or_expired_activation_cannot_create_a_session(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        headers = {"X-Admin-Token": "development-admin-token"}
        client.post("/v1/admin/activation-codes", headers=headers, json={
            "activation_code": "EXPIRED", "expires_in_seconds": -1,
        })
        expired = client.post("/v1/auth/session", json={
            "machine_code": "machine-a", "activation_code": "EXPIRED",
        })
        assert expired.status_code == 403

        created = client.post("/v1/admin/activation-codes", headers=headers, json={
            "activation_code": "REVOKED", "expires_in_seconds": int(timedelta(hours=1).total_seconds()),
        })
        activation_id = created.json()["id"]
        revoke = client.post(f"/v1/admin/activation-codes/{activation_id}/revoke", headers=headers)
        assert revoke.status_code == 204
        revoked = client.post("/v1/auth/session", json={
            "machine_code": "machine-a", "activation_code": "REVOKED",
        })
        assert revoked.status_code == 403


def test_logout_revokes_its_jwt_in_redis_and_rejects_later_requests(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        admin = {"X-Admin-Token": "development-admin-token"}
        client.post("/v1/admin/activation-codes", headers=admin, json={
            "activation_code": "LOGOUT-CODE", "expires_in_seconds": 3600,
        })
        token = client.post("/v1/auth/session", json={
            "machine_code": "logout-machine", "activation_code": "LOGOUT-CODE",
        }).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert client.delete("/v1/auth/session", headers=headers).status_code == 204
        assert client.get("/v1/audit-events", headers=headers).status_code == 401


def test_auth_session_rate_limits_repeated_requests_by_machine_code(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="t" * 32,
        initialize_schema=True,
        auth_session_limit=2,
        auth_session_window_seconds=60,
    )
    with TestClient(app) as client:
        admin = {"X-Admin-Token": "development-admin-token"}
        client.post("/v1/admin/activation-codes", headers=admin, json={
            "activation_code": "RATE-CODE", "expires_in_seconds": 3600,
        })
        payload = {"machine_code": "rate-machine", "activation_code": "RATE-CODE"}

        assert client.post("/v1/auth/session", json=payload).status_code == 200
        assert client.post("/v1/auth/session", json=payload).status_code == 200
        assert client.post("/v1/auth/session", json=payload).status_code == 429
