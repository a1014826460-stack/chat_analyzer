from fastapi.testclient import TestClient

from server_api.main import create_app


def _session(client: TestClient, machine: str, code: str) -> dict[str, str]:
    response = client.post("/v1/auth/session", json={"machine_code": machine, "activation_code": code})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_wss_credentials_are_encrypted_masked_and_user_isolated(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        admin = {"X-Admin-Token": "development-admin-token"}
        client.post("/v1/admin/activation-codes", headers=admin, json={"activation_code": "CODE-ONE", "expires_in_seconds": 3600})
        client.post("/v1/admin/activation-codes", headers=admin, json={"activation_code": "CODE-TWO", "expires_in_seconds": 3600})
        first = _session(client, "machine-one", "CODE-ONE")
        second = _session(client, "machine-two", "CODE-TWO")

        saved = client.put("/v1/integrations/wss-credentials", headers=first, json={
            "appid": "app", "accid": "account-12345", "user_sig": "super-secret-sig",
        })
        assert saved.status_code == 200
        assert "user_sig" not in saved.json()
        assert saved.json()["accid_masked"].endswith("2345")
        assert client.get("/v1/integrations/wss-credentials", headers=first).status_code == 200
        assert client.get("/v1/integrations/wss-credentials", headers=second).status_code == 404
