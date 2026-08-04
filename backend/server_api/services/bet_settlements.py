from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import BetOrder, DrawResult, StrategyEvent
from server_api.services.bet_statistics import DEFAULT_ODDS, _bet_wins
from server_api.services.runtime_logs import RuntimeLogService, format_strategy_context


async def settle_new_draws(session: AsyncSession) -> int:
    rows = (await session.execute(
        select(BetOrder, DrawResult)
        .join(
            DrawResult,
            and_(DrawResult.site == BetOrder.site, DrawResult.period == BetOrder.period),
        )
        .where(BetOrder.status == "sent")
        .order_by(BetOrder.user_id, BetOrder.site, BetOrder.period, BetOrder.id)
    )).all()
    if not rows:
        return 0

    settled_keys = {
        (int(user_id), str(site), str(period))
        for user_id, site, period in (await session.execute(
            select(StrategyEvent.user_id, StrategyEvent.site, StrategyEvent.period)
            .where(StrategyEvent.event_type == "settled")
        )).all()
    }
    grouped: dict[tuple[int, str, str], list[tuple[BetOrder, DrawResult]]] = defaultdict(list)
    for order, draw in rows:
        grouped[(order.user_id, order.site, order.period)].append((order, draw))

    written = 0
    for key, entries in grouped.items():
        if key in settled_keys:
            continue
        user_id, site, period = key
        draw = entries[0][1]
        orders = [entry[0] for entry in entries]
        staked = round(sum(float(order.amount) for order in orders), 2)
        payout = round(sum(
            float(order.amount) * DEFAULT_ODDS.get(order.play_type, 1.0)
            for order in orders
            if _bet_wins(order.play_type, draw.result)
        ), 2)
        profit = round(payout - staked, 2)
        outcome = "win" if profit > 0 else "loss"
        outcome_label = "盈利" if outcome == "win" else "亏损"
        total_text = f"（和值 {draw.total}）" if draw.total is not None else ""
        context = format_strategy_context(
            group_names=[order.group_name for order in orders], site=site, period=period
        )
        message = (
            f"{context}结算：开奖结果 {draw.result}{total_text}，"
            f"投入 {staked:g}，返还 {payout:g}，净收益 {profit:+g}，{outcome_label}"
        )
        session.add(StrategyEvent(
            user_id=user_id,
            site=site,
            period=period,
            event_type="settled",
            message=message,
        ))
        await RuntimeLogService(session).write(
            user_id=user_id,
            level="INFO",
            category="strategy",
            message=message,
            details={
                "site": site,
                "period": period,
                "result": draw.result,
                "total": draw.total,
                "staked": staked,
                "payout": payout,
                "profit": profit,
                "outcome": outcome,
                "sent_order_count": len(orders),
            },
            service_name="settlement",
        )
        settled_keys.add(key)
        written += 1

    if written:
        await session.commit()
    return written
