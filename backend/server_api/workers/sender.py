from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from inspect import isawaitable
import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import ActivationCode, AuditEvent, BetAttempt, BetOrder, User
from server_api.services.credentials import decrypt_user_sig, get_credentials
from server_api.services.strategy_events import add_order_event
from server_api.services.wss_sender import WsMessageSender


class ProductionWssSender:
    """Narrow async facade over the verified WSS protocol implementation."""

    def __init__(self, appid: str, accid: str, user_sig: str) -> None:
        self._sender = WsMessageSender(appid, accid, user_sig)

    async def send_group_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        return await asyncio.to_thread(self._send_group_bet, group_id, play_type, amount)

    def _send_group_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        if not self._sender.startup():
            return False
        try:
            return self._sender.inject_bet(group_id, play_type, amount)
        finally:
            self._sender.shutdown()


async def process_confirmed_order(
    session: AsyncSession,
    *,
    order_id: int,
    encryption_secret: str,
    sender_factory: Callable[[str, str, str], object],
) -> bool:
    order = await session.get(BetOrder, order_id)
    if order is None or order.status != "confirmed":
        return False

    if order.betting_deadline_at is not None and order.betting_deadline_at <= datetime.utcnow():
        return await _finish(session, order, "expired", "betting window closed")

    claimed = await session.execute(
        update(BetOrder).where(BetOrder.id == order_id, BetOrder.status == "confirmed").values(status="sending")
    )
    if claimed.rowcount != 1:
        await session.rollback()
        return False
    await session.flush()

    authorization = await session.scalar(
        select(ActivationCode).join(User, User.activation_id == ActivationCode.id).where(User.id == order.user_id)
    )
    if authorization is None or authorization.revoked or authorization.expires_at <= datetime.utcnow():
        return await _finish(session, order, "failed", "authorization is inactive")

    credentials = await get_credentials(session, user_id=order.user_id)
    if credentials is None:
        return await _finish(session, order, "failed", "missing WSS credentials")

    try:
        user_sig = decrypt_user_sig(credentials.encrypted_user_sig, encryption_secret)
        sender = sender_factory(credentials.appid, credentials.accid, user_sig)
        result = sender.send_group_bet(order.group_id, order.play_type, order.amount)
        if isawaitable(result):
            result = await result
        return await _finish(session, order, "sent" if result else "failed", None if result else "WSS send rejected")
    except Exception as exc:
        return await _finish(session, order, "failed", str(exc))


async def _finish(session: AsyncSession, order: BetOrder, status: str, error_message: str | None) -> bool:
    order.status = status
    session.add(BetAttempt(order_id=order.id, status=status, error_message=error_message))
    prefixes = {
        "sent": "WSS 已发送下注",
        "failed": "WSS 下注失败",
        "expired": "下注已过期",
    }
    add_order_event(
        session,
        order,
        event_type=status,
        prefix=prefixes.get(status, "下注状态更新"),
        detail=error_message,
    )
    await session.commit()
    return status == "sent"


async def expire_non_current_confirmed_orders(
    session: AsyncSession,
    current_periods: dict[str, str],
) -> int:
    """Expire confirmed orders that do not match the current query period.

    The worker may see confirmed orders left from an older client run or an older
    draw period. Those orders must never be sent in a later cycle; otherwise the
    desktop log appears to bet many historical periods at once.
    """
    orders = (await session.scalars(
        select(BetOrder).where(BetOrder.status == "confirmed")
    )).all()
    expired = 0
    for order in orders:
        current_period = current_periods.get(order.site)
        if current_period is not None and str(order.period) == str(current_period):
            continue
        order.status = "expired"
        session.add(BetAttempt(
            order_id=order.id,
            status="expired",
            error_message="not current query period",
        ))
        expired += 1
    if expired:
        await session.commit()
    return expired


async def expire_pending_orders(session: AsyncSession, now: datetime | None = None) -> int:
    current = now or datetime.utcnow()
    orders = (await session.scalars(
        select(BetOrder).where(
            BetOrder.status == "pending_confirmation",
            BetOrder.confirmation_deadline_at.is_not(None),
            BetOrder.confirmation_deadline_at <= current,
        )
    )).all()
    for order in orders:
        order.status = "expired"
        session.add(BetAttempt(order_id=order.id, status="expired", error_message="confirmation timed out"))
        session.add(AuditEvent(
            user_id=order.user_id,
            action="bet_expired",
            resource_type="bet_order",
            resource_id=str(order.id),
        ))
        add_order_event(
            session, order, event_type="expired", prefix="待确认下注已过期", detail="confirmation timed out"
        )
    if orders:
        await session.commit()
    return len(orders)
