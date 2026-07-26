from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta

from server_api.main import create_app


def _headers(client: TestClient, code: str, machine: str) -> dict[str, str]:
    admin = {"X-Admin-Token": "development-admin-token"}
    client.post("/v1/admin/activation-codes", headers=admin, json={"activation_code": code, "expires_in_seconds": 3600})
    response = client.post("/v1/auth/session", json={"machine_code": machine, "activation_code": code})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_bet_order_is_idempotent_owned_and_confirmed_once(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, "BET-OWNER", "bet-machine-owner")
        other = _headers(client, "BET-OTHER", "bet-machine-other")
        payload = {"site": "pc28", "period": "1001", "group_id": "group-1", "play_type": "大", "amount": 10}
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


def test_concurrent_confirmation_has_exactly_one_winner(tmp_path):
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, "BET-CONCURRENT", "concurrent-machine")
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
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        jwt_secret="x" * 32,
        initialize_schema=True,
    )
    with TestClient(app) as client:
        owner = _headers(client, "BET-PENDING", "pending-machine")
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

        next_bet = client.post("/v1/bets", headers=owner, json={
            "site": "pc28", "period": "1004", "group_id": "group-1", "play_type": "大", "amount": 10,
        }).json()
        expired = client.post(f"/v1/bets/{next_bet['id']}/expire", headers=owner)
        assert expired.status_code == 200
        assert expired.json()["status"] == "expired"


def test_expire_pending_orders_writes_an_audit_event():
    from sqlalchemy import select

    from server_api.db import AuditEvent, BetOrder, create_engine, create_schema, create_session_factory
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
        await engine.dispose()

    asyncio.run(scenario())
