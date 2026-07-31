from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import DrawResult, create_engine, create_schema, create_session_factory


def test_crawler_worker_normalizes_and_upserts_shared_draws():
    from server_api.workers.crawler import crawl_site

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        source = lambda site, count: [
            {"site": site, "period": "100", "sum": 14},
            {"site": site, "period": "101", "sum": 13},
        ]
        async with factory() as session:
            written = await crawl_site(session, site="pc28", history_count=20, fetch_records=source)
            assert written == 2
            rows = (await session.scalars(select(DrawResult).order_by(DrawResult.period))).all()
            assert [(row.period, row.result, row.total) for row in rows] == [
                ("100", "大双", 14),
                ("101", "小单", 13),
            ]

        async with factory() as session:
            repeated = await crawl_site(session, site="pc28", history_count=20, fetch_records=source)
            assert repeated == 0
            rows = (await session.scalars(select(DrawResult).order_by(DrawResult.period))).all()
            assert len(rows) == 2
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_cycle_crawls_sites_and_sends_only_confirmed_orders(monkeypatch):
    from server_api.worker import run_cycle

    class RecordingSender:
        sends: list[tuple[str, str, float]] = []

        def __init__(self, *_: str) -> None:
            pass

        async def send_group_bet(self, group_id: str, play_type: str, amount: float) -> bool:
            type(self).sends.append((group_id, play_type, amount))
            return True

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            from server_api.db import BetOrder
            from server_api.services.auth import create_activation_code, open_session
            from server_api.services.credentials import save_credentials

            await create_activation_code(session, activation_code="CYCLE-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="cycle-machine", activation_code="CYCLE-CODE")
            await save_credentials(
                session, user_id=user.id, appid="10001", accid="accid", user_sig="sig", encryption_secret="development-credential-encryption-secret"
            )
            session.add(BetOrder(user_id=user.id, site="pc28", period="300", group_id="group", play_type="大", amount=2, status="confirmed"))
            session.add(BetOrder(user_id=user.id, site="pc28", period="301", group_id="group", play_type="小", amount=2, status="pending_confirmation"))
            await session.commit()

        monkeypatch.setattr("server_api.worker.site_list", lambda: ["pc28"])
        monkeypatch.setattr(
            "server_api.worker.fetch_current_period",
            lambda site: type("Current", (), {"period": "300", "betting_deadline_at": None})(),
        )
        await run_cycle(
            factory,
            fetch_records=lambda site, count: [{"site": site, "period": "302", "sum": 14}],
            sender_factory=RecordingSender,
        )
        async with factory() as session:
            rows = (await session.scalars(select(DrawResult).where(DrawResult.period == "302"))).all()
            orders = (await session.scalars(select(BetOrder).order_by(BetOrder.period))).all()
            assert len(rows) == 1
            assert [order.status for order in orders] == ["sent", "pending_confirmation"]
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_cycle_returns_without_work_when_redis_lock_is_owned():
    from server_api.services.redis_state import InMemoryRedis, acquire_lock
    from server_api.worker import run_cycle

    async def scenario() -> None:
        redis = InMemoryRedis()
        assert await acquire_lock(redis, "worker:central-cycle") is True
        called = False

        def factory():
            raise AssertionError("database session must not be opened while locked")

        def fetch_records(site: str, count: int):
            nonlocal called
            called = True
            return []

        await run_cycle(factory, fetch_records=fetch_records, redis=redis)
        assert called is False

    asyncio.run(scenario())
