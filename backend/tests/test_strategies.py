from fastapi.testclient import TestClient

from server_api.main import create_app
from license_test_utils import LicenseSigner


def _headers(client: TestClient, signer: LicenseSigner, machine: str) -> dict[str, str]:
    response = client.post("/v1/auth/session", json={"machine_code": machine, "license_token": signer.sign(machine)})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_auto_bet_strategy_is_saved_per_user_and_hides_client_ai_key(tmp_path):
    signer = LicenseSigner()
    app = create_app(database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}", license_public_key_pem=signer.public_key_pem, initialize_schema=True)
    payload = {
        "enabled": True,
        "site": "pc28",
        "target_groups": ["group-1"],
        "target_group_names": {"group-1": "测试一群"},
        "history_count": 50,
        "confidence_threshold": 60,
        "require_confirmation": True,
        "bet_amount": 10,
        "client_ai_api_key": "must-not-be-stored",
    }
    with TestClient(app) as client:
        owner = _headers(client, signer, "strategy-machine-one")
        other = _headers(client, signer, "strategy-machine-two")

        saved = client.put("/v1/strategies/auto-bet", headers=owner, json=payload)
        assert saved.status_code == 200
        assert "client_ai_api_key" not in saved.json()
        assert saved.json()["target_groups"] == ["group-1"]
        assert saved.json()["target_group_names"] == {"group-1": "测试一群"}
        assert client.get("/v1/strategies/auto-bet", headers=other).json()["enabled"] is False

        own = client.get("/v1/strategies/auto-bet", headers=owner)
        assert own.status_code == 200
        assert own.json()["confidence_threshold"] == 60


def test_strategy_decision_log_uses_saved_group_name_and_site_period(tmp_path):
    import asyncio

    from server_api.db import AutoBetStrategy, create_engine, create_schema, create_session_factory
    from server_api.services.runtime_logs import RuntimeLogService
    from server_api.workers.strategy_scheduler import _add_decision_event_once

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            strategy = AutoBetStrategy(
                user_id=7,
                enabled=True,
                site="pc28",
                target_groups_json='["group-1"]',
                target_group_names_json='{"group-1":"测试一群"}',
            )
            session.add(strategy)
            await session.commit()
            assert await _add_decision_event_once(
                session,
                user_id=7,
                site="pc28",
                period="3465235",
                event_type="frequency_skip",
                message="频率未达阈值",
                group_names=["测试一群"],
            ) is True
            await session.commit()
            rows, _ = await RuntimeLogService(session).page_for_user(user_id=7)
            assert rows[0].message == "【测试一群】【pc28 3465235】频率未达阈值"
        await engine.dispose()

    asyncio.run(scenario())


def test_repeating_an_unchanged_auto_bet_strategy_does_not_repeat_runtime_log(tmp_path):
    signer = LicenseSigner()
    app = create_app(database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}", license_public_key_pem=signer.public_key_pem, initialize_schema=True)
    payload = {
        "enabled": True,
        "site": "pc28",
        "target_groups": ["group-1"],
        "history_count": 50,
        "confidence_threshold": 60,
        "require_confirmation": True,
        "bet_amount": 10,
    }
    with TestClient(app) as client:
        headers = _headers(client, signer, "strategy-log-machine")

        assert client.put("/v1/strategies/auto-bet", headers=headers, json=payload).status_code == 200
        assert client.put("/v1/strategies/auto-bet", headers=headers, json=payload).status_code == 200

        messages = [item["message"] for item in client.get("/v1/runtime-logs", headers=headers).json()["items"]]
        assert messages.count("自动下注策略已保存") == 1
