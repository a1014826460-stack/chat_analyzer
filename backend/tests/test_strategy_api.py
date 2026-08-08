from __future__ import annotations

import asyncio

from sqlalchemy import select

from server_api.db import AutoBetStrategy, create_engine, create_schema, create_session_factory


def test_strategy_api_round_trips_extended_fields():
    from server_api.api.routes.strategies import serialize

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            row = AutoBetStrategy(
                user_id=1, enabled=True, site="pc28",
                target_groups_json='["g1"]', target_group_names_json='{"g1":"群1"}',
                strategy_type="martingale", play_types_json='["大","小"]',
                observation_window=12, trigger_threshold=4, martingale_sequence_json='[10,20,40]',
            )
            session.add(row)
            await session.commit()
            data = serialize(await session.scalar(select(AutoBetStrategy).where(AutoBetStrategy.user_id == 1)))
            assert data["strategy_type"] == "martingale"
            assert data["play_types"] == ["大", "小"]
            assert data["observation_window"] == 12
            assert data["trigger_threshold"] == 4
            assert data["martingale_sequence"] == [10, 20, 40]
        await engine.dispose()

    asyncio.run(scenario())
