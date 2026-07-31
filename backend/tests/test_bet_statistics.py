from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import BetOrder, DrawResult, StrategyEvent, create_engine, create_schema, create_session_factory
from server_api.services.auth import create_activation_code, open_session


def test_server_betting_statistics_summarizes_runtime_and_ai_accuracy():
    from server_api.services.bet_statistics import betting_statistics

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_activation_code(session, activation_code="STATS-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="stats-machine", activation_code="STATS-CODE")
            session.add_all([
                DrawResult(site="pc28", period="100", result="小单", total=13),
                DrawResult(site="pc28", period="101", result="小双", total=12),
                BetOrder(user_id=user.id, site="pc28", period="100", group_id="g", play_type="小单", amount=10, status="sent"),
                BetOrder(user_id=user.id, site="pc28", period="100", group_id="g", play_type="大双", amount=10, status="sent"),
                BetOrder(user_id=user.id, site="pc28", period="101", group_id="g", play_type="小单", amount=10, status="sent"),
                BetOrder(user_id=user.id, site="pc28", period="102", group_id="g", play_type="大单", amount=10, status="sent"),
                StrategyEvent(user_id=user.id, site="pc28", period="100", event_type="ai_execute", message="频率通过：三门 小单,大双,大单；AI 执行（置信度 80/100）：ok"),
                StrategyEvent(user_id=user.id, site="pc28", period="101", event_type="ai_execute", message="频率通过：三门 小单,大双,大单；AI 执行（置信度 80/100）：miss"),
            ])
            await session.commit()

            summary = await betting_statistics(session, user_id=user.id, site="pc28", ai_window=20)

            runtime = summary["runtime_state"]
            assert runtime["pending_staked"] == 10
            assert runtime["total_staked"] == 30
            assert round(runtime["total_payout"], 2) == 36.80
            assert round(runtime["total_profit"], 2) == 6.80
            assert runtime["total_rounds"] == 2
            assert runtime["win_rounds"] == 1
            assert runtime["lose_rounds"] == 1
            ai = summary["ai_statistics"]
            assert ai["settled_count"] == 2
            assert ai["overall"]["direction_hits"] == 1
            assert ai["overall"]["exact_hits"] == 1
            assert ai["streak"] == {"result": "miss", "count": 1}
        await engine.dispose()

    asyncio.run(scenario())


def test_server_betting_statistics_can_start_from_current_run_time():
    from datetime import datetime, timedelta
    from server_api.services.bet_statistics import betting_statistics

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_activation_code(session, activation_code="STATS-SINCE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="stats-since-machine", activation_code="STATS-SINCE")
            start = datetime.utcnow()
            session.add_all([
                DrawResult(site="pc28", period="900", result="小单", total=13),
                DrawResult(site="pc28", period="901", result="大双", total=14),
                BetOrder(user_id=user.id, site="pc28", period="900", group_id="g", play_type="小单", amount=10, status="sent", created_at=start - timedelta(minutes=5)),
                BetOrder(user_id=user.id, site="pc28", period="901", group_id="g", play_type="大双", amount=10, status="sent", created_at=start + timedelta(seconds=1)),
                StrategyEvent(user_id=user.id, site="pc28", period="900", event_type="ai_execute", message="频率通过：三门 小单,大双,大单；AI 执行（置信度 80/100）：old", created_at=start - timedelta(minutes=5)),
                StrategyEvent(user_id=user.id, site="pc28", period="901", event_type="ai_execute", message="频率通过：三门 小单,大双,大单；AI 执行（置信度 80/100）：new", created_at=start + timedelta(seconds=1)),
            ])
            await session.commit()

            summary = await betting_statistics(session, user_id=user.id, site="pc28", ai_window=20, since=start)

            assert summary["runtime_state"]["total_rounds"] == 1
            assert summary["runtime_state"]["total_staked"] == 10
            assert summary["ai_statistics"]["settled_count"] == 1
        await engine.dispose()

    asyncio.run(scenario())
