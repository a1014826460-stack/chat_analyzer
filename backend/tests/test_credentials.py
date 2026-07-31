from fastapi.testclient import TestClient

from server_api.main import create_app
from license_test_utils import LicenseSigner


def _session(client: TestClient, signer: LicenseSigner, machine: str) -> dict[str, str]:
    response = client.post("/v1/auth/session", json={"machine_code": machine, "license_token": signer.sign(machine)})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_wss_credentials_are_encrypted_masked_and_user_isolated(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        first = _session(client, signer, "machine-one")
        second = _session(client, signer, "machine-two")

        saved = client.put("/v1/integrations/wss-credentials", headers=first, json={
            "appid": "20011216", "accid": "account-12345", "user_sig": "super-secret-sig",
        })
        assert saved.status_code == 200
        assert saved.json()["appid"] == "20011216"
        assert "user_sig" not in saved.json()
        assert saved.json()["accid_masked"].endswith("2345")
        assert client.get("/v1/integrations/wss-credentials", headers=first).status_code == 200
        assert client.get("/v1/integrations/wss-credentials", headers=second).status_code == 404


def test_wss_credentials_reject_business_appid_because_web_wss_requires_numeric_sdk_appid(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        headers = _session(client, signer, "machine-one")

        saved = client.put("/v1/integrations/wss-credentials", headers=headers, json={
            "appid": "LYGG88888", "accid": "account-12345", "user_sig": "super-secret-sig",
        })

        assert saved.status_code == 422
        assert "IM SDK AppID" in saved.text
