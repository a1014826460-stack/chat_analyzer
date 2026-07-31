import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from license_test_utils import LicenseSigner
from server_api.main import create_app


def _headers(client: TestClient, signer: LicenseSigner, machine_code: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/session",
        json={"machine_code": machine_code, "license_token": signer.sign(machine_code)},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_runtime_logs_filter_paginate_and_redact_sensitive_details(tmp_path):
    from server_api.services.runtime_logs import RuntimeLogService

    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        headers = _headers(client, signer, "runtime-log-machine")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                logs = RuntimeLogService(session)
                await logs.write(
                    user_id=1,
                    level="ERROR",
                    category="third_party",
                    message="upstream timeout",
                    request_url="https://source.example/path?token=server-secret&safe=1",
                    duration_ms=12,
                    status_code=504,
                    details={"api_key": "server-secret", "note": "timeout"},
                )
                await logs.write(user_id=1, level="INFO", category="user_action", message="strategy saved")
                await logs.write(
                    user_id=1,
                    level="ERROR",
                    category="exception",
                    message="another timeout",
                    request_url="https://source.example/second?sig=second-secret",
                    duration_ms=5,
                    status_code=502,
                )
                await session.commit()

        asyncio.run(seed())
        response = client.get("/v1/runtime-logs?level=ERROR&keyword=timeout&limit=1", headers=headers)

        assert response.status_code == 200
        page = response.json()
        assert len(page["items"]) == 1
        assert page["has_more"] is True
        assert page["next_before_id"] == page["items"][0]["id"]
        assert "server-secret" not in response.text
        assert page["items"][0]["level"] == "ERROR"
        assert page["items"][0]["request_url"] == "https://source.example/second"

        next_page = client.get(f"/v1/runtime-logs?before_id={page['next_before_id']}", headers=headers)
        assert next_page.status_code == 200
        assert all(item["id"] < page["next_before_id"] for item in next_page.json()["items"])


def test_runtime_logs_are_user_scoped_and_validate_time_range(tmp_path):
    from server_api.services.runtime_logs import RuntimeLogService

    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "runtime-owner")
        _headers(client, signer, "runtime-other")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                logs = RuntimeLogService(session)
                await logs.write(user_id=1, level="INFO", category="user_action", message="owner event")
                await logs.write(user_id=2, level="INFO", category="user_action", message="other event")
                await session.commit()

        asyncio.run(seed())
        response = client.get("/v1/runtime-logs", headers=owner)
        assert response.status_code == 200
        messages = [item["message"] for item in response.json()["items"]]
        assert "owner event" in messages
        assert "other event" not in messages

        start = datetime.utcnow().isoformat()
        end = (datetime.utcnow() - timedelta(seconds=1)).isoformat()
        assert client.get(f"/v1/runtime-logs?start_at={start}&end_at={end}", headers=owner).status_code == 422
