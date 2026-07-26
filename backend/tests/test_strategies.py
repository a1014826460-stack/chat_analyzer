from fastapi.testclient import TestClient

from server_api.main import create_app


def _headers(client: TestClient, code: str, machine: str) -> dict[str, str]:
    admin = {"X-Admin-Token": "development-admin-token"}
    client.post("/v1/admin/activation-codes", headers=admin, json={"activation_code": code, "expires_in_seconds": 3600})
    response = client.post("/v1/auth/session", json={"machine_code": machine, "activation_code": code})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_auto_bet_strategy_is_saved_per_user_and_hides_client_ai_key(tmp_path):
    app = create_app(database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}", initialize_schema=True)
    payload = {
        "enabled": True,
        "site": "pc28",
        "target_groups": ["group-1"],
        "history_count": 50,
        "confidence_threshold": 60,
        "require_confirmation": True,
        "bet_amount": 10,
        "client_ai_api_key": "must-not-be-stored",
    }
    with TestClient(app) as client:
        owner = _headers(client, "STRATEGY-ONE", "strategy-machine-one")
        other = _headers(client, "STRATEGY-TWO", "strategy-machine-two")

        saved = client.put("/v1/strategies/auto-bet", headers=owner, json=payload)
        assert saved.status_code == 200
        assert "client_ai_api_key" not in saved.json()
        assert saved.json()["target_groups"] == ["group-1"]
        assert client.get("/v1/strategies/auto-bet", headers=other).json()["enabled"] is False

        own = client.get("/v1/strategies/auto-bet", headers=owner)
        assert own.status_code == 200
        assert own.json()["confidence_threshold"] == 60
