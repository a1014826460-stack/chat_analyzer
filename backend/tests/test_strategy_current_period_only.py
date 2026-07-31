from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import AutoBetStrategy, DrawResult, StrategyEvent, create_engine, create_schema, create_session_factory


def test_worker_strategy_scheduler_only_evaluates_current_period_not_backfilled_history(monkeypatch):
    from server_api.worker import run_cycle
    from server_api.workers.current_period import CurrentPeriod

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=1,
                enabled=True,
                site="pc28",
                target_groups_json='["group-a"]',
                history_count=20,
                confidence_threshold=99,
                require_confirmation=False,
                bet_amount=1,
            ))
            await session.commit()

        monkeypatch.setattr("server_api.worker.site_list", lambda: ["pc28"])
        monkeypatch.setattr("server_api.worker.fetch_current_period", lambda site: CurrentPeriod("3462300", None))

        await run_cycle(
            factory,
            fetch_records=lambda site, count: [
                {"site": site, "period": "3462211", "sum": 1},
                {"site": site, "period": "3462212", "sum": 2},
                {"site": site, "period": "3462213", "sum": 3},
            ],
            sender_factory=lambda *_args, **_kwargs: None,
        )

        async with factory() as session:
            draw_periods = [row.period for row in (await session.scalars(select(DrawResult).order_by(DrawResult.period))).all()]
            events = (await session.scalars(select(StrategyEvent).order_by(StrategyEvent.id))).all()
            assert draw_periods == ["3462211", "3462212", "3462213"]
            assert [event.period for event in events] == ["3462300"]
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_sends_only_orders_for_current_query_period(monkeypatch):
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from server_api.worker import run_cycle
    from server_api.workers.current_period import CurrentPeriod
    from server_api.db import ActivationCode, BetAttempt, BetOrder, User, create_engine, create_schema, create_session_factory

    sent: list[tuple[str, str, float]] = []

    class Sender:
        def __init__(self, *_args):
            pass
        async def send_group_bet(self, group_id, play_type, amount):
            sent.append((group_id, play_type, amount))
            return True

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            code = ActivationCode(code_hash="h", expires_at=datetime.utcnow() + timedelta(hours=1), max_devices=1, revoked=False)
            session.add(code)
            await session.flush()
            user = User(activation_id=code.id)
            session.add(user)
            await session.flush()
            session.add_all([
                BetOrder(user_id=user.id, site="pc28", period="old", group_id="g", play_type="小单", amount=10, status="confirmed"),
                BetOrder(user_id=user.id, site="pc28", period="current", group_id="g", play_type="大双", amount=10, status="confirmed"),
            ])
            await session.commit()

        monkeypatch.setattr("server_api.worker.site_list", lambda: ["pc28"])
        async def fake_credentials(*args, **kwargs):
            return SimpleNamespace(appid="10001", accid="accid", encrypted_user_sig="encrypted")

        monkeypatch.setattr("server_api.worker.site_list", lambda: ["pc28"])
        monkeypatch.setattr("server_api.worker.fetch_current_period", lambda site: CurrentPeriod("current", None))
        monkeypatch.setattr("server_api.workers.sender.get_credentials", fake_credentials)
        monkeypatch.setattr("server_api.workers.sender.decrypt_user_sig", lambda *_args: "sig")
        await run_cycle(factory, fetch_records=lambda site, count: [], sender_factory=Sender)

        async with factory() as session:
            rows = (await session.scalars(select(BetOrder).order_by(BetOrder.period))).all()
            statuses = {row.period: row.status for row in rows}
            assert statuses["old"] == "expired"
            assert statuses["current"] == "sent"
            attempts = (await session.scalars(select(BetAttempt).order_by(BetAttempt.order_id))).all()
            assert [(attempt.order_id, attempt.status) for attempt in attempts] == [(1, "expired"), (2, "sent")]
            events = (await session.scalars(select(StrategyEvent).order_by(StrategyEvent.id))).all()
            assert [(event.period, event.event_type) for event in events] == [("current", "sent")]
        await engine.dispose()

    asyncio.run(scenario())
