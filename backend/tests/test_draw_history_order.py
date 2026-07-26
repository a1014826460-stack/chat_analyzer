from __future__ import annotations

import asyncio

from server_api.db import DrawResult, create_engine, create_schema, create_session_factory
from server_api.services.draws import history


def test_history_orders_numeric_periods_numerically_not_lexically():
    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add_all([
                DrawResult(site="pc28", period="9", result="小单", total=9),
                DrawResult(site="pc28", period="10", result="大双", total=14),
                DrawResult(site="pc28", period="11", result="大单", total=15),
            ])
            await session.commit()
            assert [row.period for row in await history(session, "pc28", 2)] == ["10", "11"]
        await engine.dispose()

    asyncio.run(scenario())
