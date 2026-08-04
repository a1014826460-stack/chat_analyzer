import asyncio
from datetime import datetime, timedelta, timezone

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
                await logs.write(user_id=None, level="INFO", category="system", message="global service event")
                await session.commit()

        asyncio.run(seed())
        response = client.get("/v1/runtime-logs", headers=owner)
        assert response.status_code == 200
        messages = [item["message"] for item in response.json()["items"]]
        assert "owner event" in messages
        assert "global service event" in messages
        assert "other event" not in messages

        start = datetime.utcnow().isoformat()
        end = (datetime.utcnow() - timedelta(seconds=1)).isoformat()
        assert client.get(f"/v1/runtime-logs?start_at={start}&end_at={end}", headers=owner).status_code == 422


def test_runtime_log_api_serializes_utc_and_accepts_beijing_filter_time(tmp_path):
    from server_api.services.runtime_logs import RuntimeLogService

    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        headers = _headers(client, signer, "beijing-runtime-machine")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                row = await RuntimeLogService(session).write(
                    user_id=1,
                    level="INFO",
                    category="strategy",
                    message="北京时间日志",
                )
                row.created_at = datetime(2026, 8, 4, 0, 8, 52)
                await session.commit()

        asyncio.run(seed())
        response = client.get(
            "/v1/runtime-logs?start_at=2026-08-04T08:08:00%2B08:00&end_at=2026-08-04T08:09:00%2B08:00",
            headers=headers,
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["created_at"] == "2026-08-04T00:08:52+00:00"
    assert item["message"] == "北京时间日志"


def test_runtime_log_api_backfills_group_name_and_site_period_for_legacy_strategy_logs(tmp_path):
    from server_api.db import AutoBetStrategy
    from server_api.services.runtime_logs import RuntimeLogService

    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        headers = _headers(client, signer, "legacy-strategy-log-machine")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                session.add(AutoBetStrategy(
                    user_id=1,
                    enabled=False,
                    site="pc28",
                    target_groups_json='["207191791"]',
                    target_group_names_json='{"207191791":"测试1群"}',
                ))
                await RuntimeLogService(session).write(
                    user_id=1,
                    level="INFO",
                    category="strategy",
                    message="WSS 已发送下注：【群组 207191791】【pc28 期号 3465420】【下注玩法 小单10、大双10、小双10】",
                    details={"site": "pc28", "period": "3465420", "group_id": "207191791"},
                )
                await RuntimeLogService(session).write(
                    user_id=1,
                    level="INFO",
                    category="strategy",
                    message="频率未达阈值：三门 小单,大双,小双，最高 30.0% < 阈值 45%",
                    details={"site": "pc28", "period": "3465421", "group_names": ["未命名群组"]},
                )
                await session.commit()

        asyncio.run(seed())
        items = client.get("/v1/runtime-logs?category=strategy", headers=headers).json()["items"]

    messages = [item["message"] for item in items]
    assert "【测试1群】【pc28 3465420】WSS 已发送下注：【下注玩法 小单10、大双10、小双10】" in messages
    assert "【测试1群】【pc28 3465421】频率未达阈值：三门 小单,大双,小双，最高 30.0% < 阈值 45%" in messages
