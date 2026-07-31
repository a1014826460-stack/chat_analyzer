from fastapi.testclient import TestClient

from server_api.main import create_app
from license_test_utils import LicenseSigner


def _user_headers(client: TestClient, signer: LicenseSigner) -> dict[str, str]:
    response = client.post("/v1/auth/session", json={
        "machine_code": "draw-machine", "license_token": signer.sign("draw-machine"),
    })
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_shared_draw_upsert_history_and_frequency_analysis(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        admin = {"X-Admin-Token": "development-admin-token"}
        for period, result, total in (("1", "小单", 13), ("2", "大双", 14), ("3", "大单", 15), ("4", "小双", 12)):
            response = client.put("/v1/admin/draws", headers=admin, json={
                "site": "pc28", "period": period, "result": result, "total": total,
            })
            assert response.status_code == 200
        # Repeated crawler data updates the record rather than duplicating it.
        assert client.put("/v1/admin/draws", headers=admin, json={
            "site": "pc28", "period": "4", "result": "小双", "total": 12,
        }).status_code == 200

        headers = _user_headers(client, signer)
        history = client.get("/v1/draws/pc28/history?limit=20", headers=headers)
        assert [item["period"] for item in history.json()["items"]] == ["1", "2", "3", "4"]

        analysis = client.get("/v1/analysis/frequency?site=pc28&history_count=20", headers=headers)
        payload = analysis.json()
        assert payload["sample_count"] == 4
        assert payload["number_probabilities"] == {"13": 25.0, "14": 25.0}
        assert payload["excluded_play"] == "小单"
        assert payload["selected_plays"] == ["大双", "小双", "大单"]
