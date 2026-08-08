from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import AutoBetStrategy, BetOrder, DrawResult, StrategyEvent, create_engine, create_schema, create_session_factory


def test_frequency_scheduler_creates_three_door_orders_for_each_target_group():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class ExecuteAi:
        def recommend_three_doors(self, *, site, history, selected_plays):
            return {"action": "execute", "confidence": 75, "reason": "通过"}

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

            created = await schedule_frequency_orders(session, site="pc28", period="next-1", ai_client=ExecuteAi())
            assert created == 6
            rows = (await session.scalars(select(BetOrder).order_by(BetOrder.group_id, BetOrder.play_type))).all()
            assert {row.play_type for row in rows} == {"小单", "大双", "大单"}
            assert {row.group_id for row in rows} == {"group-a", "group-b"}
            assert {row.status for row in rows} == {"pending_confirmation"}
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_does_not_create_orders_below_confidence_threshold():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class MustNotCallAi:
        def recommend_three_doors(self, **_kwargs):
            raise AssertionError("AI must not be called when frequency threshold is not reached")

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
            assert await schedule_frequency_orders(session, site="pc28", period="next-2", ai_client=MustNotCallAi()) == 0
            assert (await session.scalars(select(BetOrder))).all() == []
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_is_idempotent_for_an_existing_period():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class ExecuteAi:
        def recommend_three_doors(self, *, site, history, selected_plays):
            return {"action": "execute", "confidence": 75, "reason": "通过"}

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

            assert await schedule_frequency_orders(session, site="pc28", period="next-3", ai_client=ExecuteAi()) == 3
            assert await schedule_frequency_orders(session, site="pc28", period="next-3", ai_client=ExecuteAi()) == 0
            assert len((await session.scalars(select(BetOrder))).all()) == 3
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_places_algorithm_orders_without_ai():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=10, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            # 不传 ai_client：纯算法模式，频率达标直接下注
            assert await schedule_frequency_orders(session, site="pc28", period="next-4") == 3
            rows = (await session.scalars(select(BetOrder))).all()
            assert {row.play_type for row in rows} == {"小单", "大双", "大单"}
            event = await session.scalar(select(StrategyEvent))
            assert event.event_type == "ai_execute"
            assert "算法决策下注" in event.message
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_records_one_decision_event_per_user_period_and_type():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=11, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=80, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="小双", total=12),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-dup") == 0
            assert await schedule_frequency_orders(session, site="pc28", period="next-dup") == 0
            events = (await session.scalars(select(StrategyEvent))).all()
            assert [(event.event_type, event.period) for event in events] == [("frequency_skip", "next-dup")]
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_algorithm_mode_skips_below_threshold_without_ai():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=12, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=80, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="小双", total=12),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-5") == 0
            assert (await session.scalars(select(BetOrder))).all() == []
            event = await session.scalar(select(StrategyEvent))
            assert event.event_type == "frequency_skip"
            assert "频率未达阈值" in event.message
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_scheduler_trend_following_reverse_bet():
    from server_api.workers.strategy_scheduler import _trend_following_plays

    rows = [DrawResult(site="pc28", period=str(i), result="小单", total=13) for i in range(1, 6)]
    assert _trend_following_plays("pc28", rows, window=5, threshold=3) == ["大"]

    rows_break = [
        DrawResult(site="pc28", period=str(i), result="小单" if i < 5 else "大单", total=13 if i < 5 else 15)
        for i in range(1, 6)
    ]
    assert _trend_following_plays("pc28", rows_break, window=5, threshold=3) is None


def test_frequency_scheduler_writes_strategy_snapshot():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=20, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False,
                bet_amount=3, strategy_type="three_doors",
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()
            assert await schedule_frequency_orders(session, site="pc28", period="next-snap") == 3
            order = await session.scalar(select(BetOrder))
            assert order.strategy_type == "three_doors"
            import json
            snapshot = json.loads(order.strategy_snapshot)
            assert snapshot["history_count"] == 4
            assert snapshot["confidence_threshold"] == 50
            assert order.result == "pending"
        await engine.dispose()

    asyncio.run(scenario())
