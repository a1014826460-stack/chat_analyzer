from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import (
    AutoBetStrategy,
    BetOrder,
    DrawResult,
    StrategyEvent,
    create_engine,
    create_schema,
    create_session_factory,
)


def test_frequency_qualified_strategy_uses_ai_to_decide_whether_to_create_all_three_orders():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class ExecuteAi:
        def recommend_three_doors(self, *, site, history, selected_plays):
            assert site == "pc28"
            assert selected_plays == ["小单", "大双", "大单"]
            return {"action": "execute", "confidence": 75, "reason": "近期样本支持执行三门"}

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=7, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-1", ai_client=ExecuteAi()) == 3
            orders = (await session.scalars(select(BetOrder).order_by(BetOrder.play_type))).all()
            events = (await session.scalars(select(StrategyEvent).order_by(StrategyEvent.id))).all()
            assert {row.play_type for row in orders} == {"小单", "大双", "大单"}
            assert events[-1].event_type == "ai_execute"
            assert "75" in events[-1].message
            from server_api.services.runtime_logs import RuntimeLogService
            runtime_rows, _ = await RuntimeLogService(session).page_for_user(user_id=7)
            assert any(row.category == "strategy" and "AI 执行" in row.message for row in runtime_rows)
        await engine.dispose()

    asyncio.run(scenario())


def test_frequency_qualified_strategy_records_ai_skip_without_creating_orders():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class SkipAi:
        def recommend_three_doors(self, *, site, history, selected_plays):
            return {"action": "skip", "confidence": 32, "reason": "没有足够优势"}

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=8, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-2", ai_client=SkipAi()) == 0
            assert (await session.scalars(select(BetOrder))).all() == []
            event = await session.scalar(select(StrategyEvent))
            assert event.event_type == "ai_skip"
            assert "没有足够优势" in event.message
        await engine.dispose()

    asyncio.run(scenario())
