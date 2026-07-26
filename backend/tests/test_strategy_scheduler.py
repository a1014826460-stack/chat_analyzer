from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import AutoBetStrategy, BetOrder, DrawResult, create_engine, create_schema, create_session_factory


def test_frequency_scheduler_creates_three_door_orders_for_each_target_group():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            strategy = AutoBetStrategy(
                user_id=7, enabled=True, site="pc28", target_groups_json='["group-a","group-b"]',
                history_count=4, confidence_threshold=50, require_confirmation=True, bet_amount=3,
            )
            session.add(strategy)
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            created = await schedule_frequency_orders(session, site="pc28", period="next-1")
            assert created == 6
            rows = (await session.scalars(select(BetOrder).order_by(BetOrder.group_id, BetOrder.play_type))).all()
            assert {row.play_type for row in rows} == {"小单", "大双", "大单"}
            assert {row.group_id for row in rows} == {"group-a", "group-b"}
            assert {row.status for row in rows} == {"pending_confirmation"}
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_does_not_create_orders_below_confidence_threshold():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=8, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=80, require_confirmation=True, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="小双", total=12),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()
            assert await schedule_frequency_orders(session, site="pc28", period="next-2") == 0
            assert (await session.scalars(select(BetOrder))).all() == []
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_is_idempotent_for_an_existing_period():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=9, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-3") == 3
            assert await schedule_frequency_orders(session, site="pc28", period="next-3") == 0
            assert len((await session.scalars(select(BetOrder))).all()) == 3
        await engine.dispose()

    asyncio.run(scenario())
