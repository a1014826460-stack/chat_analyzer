from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import BetOrder, StrategyEvent


def format_amount(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def add_order_event(
    session: AsyncSession,
    order: BetOrder,
    *,
    event_type: str,
    prefix: str,
    detail: str | None = None,
) -> None:
    message = f"{prefix}：群组 {order.group_id}，玩法 {order.play_type}{format_amount(order.amount)}"
    if detail:
        message += f"，{detail}"
    session.add(StrategyEvent(
        user_id=order.user_id,
        site=order.site,
        period=order.period,
        event_type=event_type,
        message=message,
    ))
