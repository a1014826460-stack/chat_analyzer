from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import AutoBetStrategy, BetOrder, DrawResult, StrategyEvent, create_engine, create_schema, create_session_factory


def _seed_frequency_passing_data(session) -> None:
    session.add_all([
        DrawResult(site="pc28", period="1", result="小单", total=13),
        DrawResult(site="pc28", period="2", result="大双", total=14),
        DrawResult(site="pc28", period="3", result="大双", total=14),
        DrawResult(site="pc28", period="4", result="大单", total=15),
    ])


def test_strategy_scheduler_does_not_redecide_same_user_site_period_after_ai_execute():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class CountingAi:
        def __init__(self):
            self.calls = 0

        def recommend_three_doors(self, *, site, history, selected_plays):
            self.calls += 1
            return {"action": "execute", "confidence": 80, "reason": f"call {self.calls}"}

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        ai = CountingAi()
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=7, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            _seed_frequency_passing_data(session)
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-1", ai_client=ai) == 3
            assert await schedule_frequency_orders(session, site="pc28", period="next-1", ai_client=ai) == 0
            assert ai.calls == 1
            events = (await session.scalars(select(StrategyEvent).order_by(StrategyEvent.id))).all()
            assert [event.event_type for event in events] == ["ai_execute"]
            assert len((await session.scalars(select(BetOrder))).all()) == 3
        await engine.dispose()

    asyncio.run(scenario())


def test_strategy_scheduler_does_not_retry_same_user_site_period_after_ai_error():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class FailingAi:
        def __init__(self):
            self.calls = 0

        def recommend_three_doors(self, *, site, history, selected_plays):
            self.calls += 1
            raise RuntimeError("temporary timeout")

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        ai = FailingAi()
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=8, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            _seed_frequency_passing_data(session)
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-2", ai_client=ai) == 0
            assert await schedule_frequency_orders(session, site="pc28", period="next-2", ai_client=ai) == 0
            assert ai.calls == 1
            events = (await session.scalars(select(StrategyEvent).order_by(StrategyEvent.id))).all()
            assert [event.event_type for event in events] == ["ai_error"]
        await engine.dispose()

    asyncio.run(scenario())
