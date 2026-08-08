from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from server_api.db import BetOrder, DrawResult, RuntimeLogEvent, StrategyEvent, create_engine, create_schema, create_session_factory
from server_api.services.auth import create_activation_code, open_session


def test_settle_new_draws_writes_one_aggregate_log_for_sent_orders_only():
    from server_api.services.bet_settlements import settle_new_draws

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_activation_code(session, activation_code="SETTLE-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="settle-machine", activation_code="SETTLE-CODE")
            session.add(DrawResult(site="pc28", period="500", result="小单", total=13))
            session.add_all([
                BetOrder(user_id=user.id, site="pc28", period="500", group_id="g1", play_type="小单", amount=10, status="sent"),
                BetOrder(user_id=user.id, site="pc28", period="500", group_id="g1", play_type="大双", amount=10, status="sent"),
                BetOrder(user_id=user.id, site="pc28", period="500", group_id="g2", play_type="小", amount=5, status="sent"),
                BetOrder(user_id=user.id, site="pc28", period="500", group_id="g3", play_type="小单", amount=99, status="failed"),
                BetOrder(user_id=user.id, site="pc28", period="500", group_id="g4", play_type="小单", amount=88, status="expired"),
                BetOrder(user_id=user.id, site="pc28", period="500", group_id="g5", play_type="小单", amount=77, status="confirmed"),
            ])
            await session.commit()

            assert await settle_new_draws(session) == 1
            assert await settle_new_draws(session) == 0

            events = (await session.scalars(
                select(StrategyEvent).where(StrategyEvent.user_id == user.id, StrategyEvent.event_type == "settled")
            )).all()
            assert len(events) == 1
            assert events[0].period == "500"
            logs = (await session.scalars(
                select(RuntimeLogEvent).where(RuntimeLogEvent.user_id == user.id, RuntimeLogEvent.category == "strategy")
            )).all()
            assert len(logs) == 1
            details = json.loads(logs[0].details_json)
            assert details == {
                "site": "pc28",
                "period": "500",
                "result": "小单",
                "total": 13,
                "staked": 25.0,
                "payout": 46.7,
                "profit": 21.7,
                "outcome": "win",
                "sent_order_count": 3,
            }
            assert "投入 25" in logs[0].message
            assert "返还 46.7" in logs[0].message
            assert "净收益 +21.7" in logs[0].message
            assert "盈利" in logs[0].message
        await engine.dispose()

    asyncio.run(scenario())


def test_settle_new_draws_keeps_users_and_sites_independent():
    from server_api.services.bet_settlements import settle_new_draws

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_activation_code(session, activation_code="SETTLE-FIRST", expires_in_seconds=3600)
            await create_activation_code(session, activation_code="SETTLE-SECOND", expires_in_seconds=3600)
            first, _ = await open_session(session, machine_code="settle-first", activation_code="SETTLE-FIRST")
            second, _ = await open_session(session, machine_code="settle-second", activation_code="SETTLE-SECOND")
            session.add_all([
                DrawResult(site="pc28", period="600", result="大双", total=14),
                DrawResult(site="macao", period="600", result="小单", total=21),
                BetOrder(user_id=first.id, site="pc28", period="600", group_id="g", play_type="大双", amount=10, status="sent"),
                BetOrder(user_id=second.id, site="pc28", period="600", group_id="g", play_type="小单", amount=10, status="sent"),
                BetOrder(user_id=first.id, site="macao", period="600", group_id="g", play_type="小单", amount=10, status="sent"),
            ])
            await session.commit()

            assert await settle_new_draws(session) == 3
            keys = (await session.execute(
                select(StrategyEvent.user_id, StrategyEvent.site, StrategyEvent.period)
                .where(StrategyEvent.event_type == "settled")
            )).all()
            assert set(keys) == {
                (first.id, "pc28", "600"),
                (second.id, "pc28", "600"),
                (first.id, "macao", "600"),
            }
        await engine.dispose()

    asyncio.run(scenario())


def test_result_detail_mapping():
    from server_api.services.bet_settlements import _result_detail

    assert _result_detail("小单", "小单") == "exact_hit"
    assert _result_detail("小", "小单") == "direction_hit"
    assert _result_detail("单", "小单") == "direction_hit"
    assert _result_detail("小单", "大单") == ""
