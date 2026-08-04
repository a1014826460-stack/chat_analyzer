from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta

from server_api.main import create_app
from server_api.db import StrategyEvent
from license_test_utils import LicenseSigner


def _headers(client: TestClient, signer: LicenseSigner, machine: str) -> dict[str, str]:
    response = client.post("/v1/auth/session", json={"machine_code": machine, "license_token": signer.sign(machine)})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_bet_order_is_idempotent_owned_and_confirmed_once(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "bet-machine-owner")
        other = _headers(client, signer, "bet-machine-other")
        payload = {"site": "pc28", "period": "1001", "group_id": "group-1", "group_name": "测试一群", "play_type": "大", "amount": 10}
        created = client.post("/v1/bets", headers=owner, json=payload)
        duplicate = client.post("/v1/bets", headers=owner, json=payload)
        assert created.status_code == 201
        assert duplicate.status_code == 200
        bet_id = created.json()["id"]
        assert duplicate.json()["id"] == bet_id

        assert client.post(f"/v1/bets/{bet_id}/confirm", headers=other).status_code == 404
        assert client.post(f"/v1/bets/{bet_id}/confirm", headers=owner).json()["status"] == "confirmed"
        assert client.post(f"/v1/bets/{bet_id}/confirm", headers=owner).status_code == 409
        events = client.get("/v1/audit-events", headers=owner).json()["items"]
        assert [event["action"] for event in events] == ["bet_created", "bet_confirmed"]
        strategy_events = client.get("/v1/bets/events", headers=owner).json()["items"]
        assert [(event["event_type"], event["period"]) for event in strategy_events] == [("confirmed", "1001")]
        assert "测试一群" in strategy_events[0]["message"] and "大10" in strategy_events[0]["message"]
        runtime_messages = [item["message"] for item in client.get("/v1/runtime-logs", headers=owner).json()["items"]]
        assert any(message.startswith("【测试一群】【pc28 1001】已确认下注订单：玩法 大10") for message in runtime_messages)


def test_concurrent_confirmation_has_exactly_one_winner(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "concurrent-machine")
        created = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "1002", "group_id": "group-1", "play_type": "大", "amount": 10,
        })
        bet_id = created.json()["id"]

    def confirm() -> int:
        with TestClient(app) as client:
            return client.post(f"/v1/bets/{bet_id}/confirm", headers=owner).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: confirm(), range(2)))

    assert sorted(statuses) == [200, 409]


def test_pending_bets_can_be_listed_skipped_and_expired(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "pending-machine")
        created = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "1003", "group_id": "group-1", "play_type": "小", "amount": 10,
            "confirmation_timeout_seconds": 60,
        })
        bet_id = created.json()["id"]
        assert created.json()["confirmation_deadline_at"]

        listed = client.get("/v1/bets/pending", headers=owner)
        assert [item["id"] for item in listed.json()["items"]] == [bet_id]
        assert client.post(f"/v1/bets/{bet_id}/skip", headers=owner).json()["status"] == "skipped"
        assert client.get("/v1/bets/pending", headers=owner).json()["items"] == []
        strategy_events = client.get("/v1/bets/events", headers=owner).json()["items"]
        assert [(event["event_type"], event["period"]) for event in strategy_events] == [("skipped", "1003")]

        next_bet = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "1004", "group_id": "group-1", "play_type": "大", "amount": 10,
        }).json()
        expired = client.post(f"/v1/bets/{next_bet['id']}/expire", headers=owner)
        assert expired.status_code == 200
        assert expired.json()["status"] == "expired"


def test_expire_pending_orders_writes_an_audit_event():
    from sqlalchemy import select

    from server_api.db import AuditEvent, BetOrder, StrategyEvent, create_engine, create_schema, create_session_factory
    from server_api.services.auth import create_activation_code, open_session
    from server_api.workers.sender import expire_pending_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_activation_code(session, activation_code="AUDIT-EXPIRE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="audit-expire-machine", activation_code="AUDIT-EXPIRE")
            order = BetOrder(
                user_id=user.id, site="pc28", period="1005", group_id="group", play_type="小", amount=1,
                status="pending_confirmation", confirmation_deadline_at=datetime.utcnow() - timedelta(seconds=1),
            )
            session.add(order)
            await session.commit()

            assert await expire_pending_orders(session) == 1
            events = (await session.scalars(select(AuditEvent).where(AuditEvent.user_id == user.id))).all()
            assert [(event.action, event.resource_id) for event in events] == [("bet_expired", str(order.id))]
            strategy_event = await session.scalar(select(StrategyEvent).where(StrategyEvent.user_id == user.id))
            assert strategy_event.event_type == "expired"
            assert "confirmation timed out" in strategy_event.message
        await engine.dispose()

    asyncio.run(scenario())


def test_betting_events_latest_returns_only_current_users_highest_event_id(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "latest-owner")
        other = _headers(client, signer, "latest-other")

        assert client.get("/v1/bets/events/latest", headers=owner).json() == {"latest_id": 0}
        created = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "2001", "group_id": "group-1", "play_type": "大", "amount": 10,
            "confirmation_timeout_seconds": 60,
        }).json()
        client.post(f"/v1/bets/{created['id']}/skip", headers=owner)
        client.post("/v1/bets", headers=other, json={
            "site": "pc28", "period": "2002", "group_id": "group-2", "play_type": "小", "amount": 10,
            "confirmation_timeout_seconds": 60,
        })

        latest = client.get("/v1/bets/events/latest", headers=owner)
        assert latest.status_code == 200
        assert latest.json()["latest_id"] > 0
        assert client.get(f"/v1/bets/events?after_id={latest.json()['latest_id']}", headers=owner).json()["items"] == []


def test_betting_events_latest_can_be_scoped_to_site(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "event-site-machine")
        macao = client.post("/v1/bets", headers=owner, json={
            "site": "macao", "period": "100", "group_id": "g", "play_type": "大", "amount": 1,
            "confirmation_timeout_seconds": 60,
        }).json()
        client.post(f"/v1/bets/{macao['id']}/skip", headers=owner)
        pc28 = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "200", "group_id": "g", "play_type": "大", "amount": 1,
            "confirmation_timeout_seconds": 60,
        }).json()
        client.post(f"/v1/bets/{pc28['id']}/skip", headers=owner)

        latest = client.get("/v1/bets/events/latest?site=pc28", headers=owner)

        assert latest.status_code == 200
        assert latest.json()["latest_id"] > 0
        assert client.get(f"/v1/bets/events?after_id={latest.json()['latest_id']}&site=pc28", headers=owner).json()["items"] == []


def test_betting_events_can_be_scoped_to_site(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "event-list-site-machine")
        macao = client.post("/v1/bets", headers=owner, json={
            "site": "macao", "period": "100", "group_id": "g", "play_type": "大", "amount": 1,
            "confirmation_timeout_seconds": 60,
        }).json()
        client.post(f"/v1/bets/{macao['id']}/skip", headers=owner)
        pc28 = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "200", "group_id": "g", "play_type": "大", "amount": 1,
            "confirmation_timeout_seconds": 60,
        }).json()
        client.post(f"/v1/bets/{pc28['id']}/skip", headers=owner)

        events = client.get("/v1/bets/events?after_id=0&site=pc28", headers=owner)

        assert events.status_code == 200
        assert [item["site"] for item in events.json()["items"]] == ["pc28"]


def test_betting_statistics_endpoint_returns_runtime_and_ai_cards(tmp_path):
    import asyncio
    from fastapi.testclient import TestClient
    from server_api.db import BetOrder, DrawResult, StrategyEvent

    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "stats-endpoint-machine")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                user_id = 1
                session.add_all([
                    DrawResult(site="pc28", period="500", result="小单", total=13),
                    BetOrder(user_id=user_id, site="pc28", period="500", group_id="g", play_type="小单", amount=10, status="sent"),
                    StrategyEvent(user_id=user_id, site="pc28", period="500", event_type="ai_execute", message="频率通过：三门 小单,大双,大单；AI 执行（置信度 80/100）：ok"),
                ])
                await session.commit()

        asyncio.run(seed())
        response = client.get("/v1/bets/statistics?site=pc28&ai_window=20", headers=owner)

        assert response.status_code == 200
        payload = response.json()
        assert payload["runtime_state"]["total_rounds"] == 1
        assert payload["runtime_state"]["win_rounds"] == 1
        assert payload["ai_statistics"]["settled_count"] == 1
        assert payload["ai_statistics"]["overall"]["direction_accuracy"] == 1.0


def test_betting_events_can_be_filtered_since_run_start(tmp_path):
    import asyncio
    from datetime import datetime
    from fastapi.testclient import TestClient
    from server_api.db import StrategyEvent

    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "event-since-machine")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                session.add_all([
                    StrategyEvent(
                        user_id=1, site="pc28", period="old", event_type="sent", message="旧期",
                        created_at=datetime(2026, 7, 28, 22, 22, 48),
                    ),
                    StrategyEvent(
                        user_id=1, site="pc28", period="current", event_type="sent", message="本次",
                        created_at=datetime(2026, 7, 28, 22, 22, 50),
                    ),
                ])
                await session.commit()

        asyncio.run(seed())
        response = client.get(
            "/v1/bets/events?after_id=0&site=pc28&since=2026-07-28T22:22:49",
            headers=owner,
        )

        assert response.status_code == 200
    assert [(item["period"], item["message"]) for item in response.json()["items"]] == [("current", "本次")]


def test_ai_prediction_history_is_authenticated_user_scoped_and_newest_first(tmp_path):
    signer = LicenseSigner()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        license_public_key_pem=signer.public_key_pem,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, signer, "ai-history-owner")
        _headers(client, signer, "ai-history-other")

        async def seed() -> None:
            async with app.state.session_factory() as session:
                session.add_all([
                    StrategyEvent(user_id=1, site="pc28", period="1001", event_type="ai_skip", message="older AI decision"),
                    StrategyEvent(user_id=1, site="pc28", period="1002", event_type="ai_execute", message="latest AI decision"),
                    StrategyEvent(user_id=2, site="pc28", period="1003", event_type="ai_execute", message="other user"),
                    StrategyEvent(user_id=1, site="macao", period="1004", event_type="sent", message="not an AI decision"),
                ])
                await session.commit()

        asyncio.run(seed())
        response = client.get("/v1/bets/ai-history?site=pc28&limit=10", headers=owner)

        assert response.status_code == 200
        assert [(item["period"], item["message"]) for item in response.json()["items"]] == [
            ("1002", "latest AI decision"),
            ("1001", "older AI decision"),
        ]
