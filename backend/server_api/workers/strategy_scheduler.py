from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import AutoBetStrategy, BetOrder
from server_api.services.draws import analyze, history


async def schedule_frequency_orders(
    session: AsyncSession,
    *,
    site: str,
    period: str,
    betting_deadline_at: datetime | None = None,
) -> int:
    strategies = (await session.scalars(
        select(AutoBetStrategy).where(AutoBetStrategy.enabled.is_(True), AutoBetStrategy.site == site)
    )).all()
    created = 0
    for strategy in strategies:
        analysis = analyze(
            site,
            await history(session, site, strategy.history_count),
            strategy.history_count,
            strategy.confidence_threshold,
        )
        if not analysis["should_bet"]:
            continue
        plays = list(analysis["selected_plays"])
        for group_id in json.loads(strategy.target_groups_json):
            for play_type in plays:
                exists = await session.scalar(select(BetOrder.id).where(
                    BetOrder.user_id == strategy.user_id,
                    BetOrder.site == site,
                    BetOrder.period == period,
                    BetOrder.group_id == group_id,
                    BetOrder.play_type == play_type,
                ))
                if exists is not None:
                    continue
                deadline = datetime.utcnow() + timedelta(seconds=30) if strategy.require_confirmation else None
                session.add(BetOrder(
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    group_id=group_id,
                    play_type=play_type,
                    amount=strategy.bet_amount,
                    status="pending_confirmation" if strategy.require_confirmation else "confirmed",
                    confirmation_deadline_at=deadline,
                    betting_deadline_at=betting_deadline_at,
                ))
                created += 1
    if created:
        await session.commit()
    return created
