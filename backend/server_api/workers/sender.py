from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from inspect import isawaitable
import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import ActivationCode, AuditEvent, BetAttempt, BetOrder, User
from server_api.services.credentials import decrypt_user_sig, get_credentials
from server_api.services.runtime_logs import RuntimeLogService, format_strategy_context
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


def build_group_bet_runtime_message(orders: Iterable[object]) -> str:
    rows = list(orders)
    if not rows:
        return ""
    first = rows[0]
    plays = [
        f"{getattr(order, 'play_type', '')}{float(getattr(order, 'amount', 0)):g}"
        for order in rows
    ]
    statuses = {str(getattr(order, "status", "")).strip() for order in rows}
    if statuses == {"sent"}:
        prefix = "WSS 已发送下注"
    elif statuses <= {"failed", "expired"}:
        prefix = "WSS 下注未发送"
    else:
        prefix = "下注处理完成"
    return (
        f"{format_strategy_context(group_names=[getattr(first, 'group_name', '')], site=getattr(first, 'site', ''), period=getattr(first, 'period', ''))}"
        f"{prefix}："
        f"【下注玩法 {'、'.join(plays)}】"
    )


async def write_group_bet_runtime_logs(session: AsyncSession, order_ids: Iterable[int]) -> int:
    ids = [int(order_id) for order_id in order_ids]
    if not ids:
        return 0
    orders = (await session.scalars(
        select(BetOrder).where(BetOrder.id.in_(ids)).order_by(BetOrder.id)
    )).all()
    grouped: dict[tuple[int, str, str, str], list[BetOrder]] = defaultdict(list)
    for order in orders:
        grouped[(order.user_id, order.site, order.period, order.group_id)].append(order)
    for group_orders in grouped.values():
        message = build_group_bet_runtime_message(group_orders)
        statuses = [str(order.status) for order in group_orders]
        await RuntimeLogService(session).write(
            user_id=group_orders[0].user_id,
            level="INFO" if all(status == "sent" for status in statuses) else "WARN",
            category="strategy",
            message=message,
            details={
                "site": group_orders[0].site,
                "period": group_orders[0].period,
                "group_id": group_orders[0].group_id,
                "group_name": group_orders[0].group_name,
                "plays": [
                    {"play_type": order.play_type, "amount": order.amount, "status": order.status}
                    for order in group_orders
                ],
            },
            service_name="wss_sender",
        )
    await session.commit()
    return len(grouped)


async def process_confirmed_order(
    session: AsyncSession,
    *,
    order_id: int,
    encryption_secret: str,
    sender_factory: Callable[[str, str, str], object],
    emit_runtime_log: bool = True,
) -> bool:
    order = await session.get(BetOrder, order_id)
    if order is None or order.status != "confirmed":
        return False

    if order.betting_deadline_at is not None and order.betting_deadline_at <= datetime.utcnow():
        return await _finish(session, order, "expired", "betting window closed", emit_runtime_log=emit_runtime_log)

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
        return await _finish(session, order, "failed", "authorization is inactive", emit_runtime_log=emit_runtime_log)

    credentials = await get_credentials(session, user_id=order.user_id)
    if credentials is None:
        return await _finish(session, order, "failed", "missing WSS credentials", emit_runtime_log=emit_runtime_log)

    try:
        user_sig = decrypt_user_sig(credentials.encrypted_user_sig, encryption_secret)
        sender = sender_factory(credentials.appid, credentials.accid, user_sig)
        result = sender.send_group_bet(order.group_id, order.play_type, order.amount)
        if isawaitable(result):
            result = await result
        return await _finish(
            session,
            order,
            "sent" if result else "failed",
            None if result else "WSS send rejected",
            emit_runtime_log=emit_runtime_log,
        )
    except Exception as exc:
        return await _finish(session, order, "failed", str(exc), emit_runtime_log=emit_runtime_log)


async def _finish(
    session: AsyncSession,
    order: BetOrder,
    status: str,
    error_message: str | None,
    *,
    emit_runtime_log: bool = True,
) -> bool:
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
    if emit_runtime_log:
        message = (
            f"{format_strategy_context(group_names=[order.group_name], site=order.site, period=order.period)}"
            f"{prefixes.get(status, '下注状态更新')}：玩法 {order.play_type}{order.amount:g}"
        )
        if error_message:
            message += f"，{error_message}"
        await RuntimeLogService(session).write(
            user_id=order.user_id,
            level="INFO" if status == "sent" else "WARN",
            category="strategy",
            message=message,
            details={
                "site": order.site,
                "period": order.period,
                "group_id": order.group_id,
                "play_type": order.play_type,
                "amount": order.amount,
                "status": status,
            },
            service_name="wss_sender",
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
        await RuntimeLogService(session).write(
            user_id=order.user_id,
            level="WARN",
            category="strategy",
            message=(
                f"{format_strategy_context(group_names=[order.group_name], site=order.site, period=order.period)}"
                f"下注已过期：玩法 {order.play_type}{order.amount:g}，非当前查询期"
            ),
            details={"site": order.site, "period": order.period, "group_id": order.group_id, "group_name": order.group_name, "play_type": order.play_type, "amount": order.amount, "status": "expired"},
            service_name="wss_sender",
        )
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
        await RuntimeLogService(session).write(
            user_id=order.user_id,
            level="WARN",
            category="strategy",
            message=(
                f"{format_strategy_context(group_names=[order.group_name], site=order.site, period=order.period)}"
                f"待确认下注已过期：玩法 {order.play_type}{order.amount:g}，confirmation timed out"
            ),
            details={"site": order.site, "period": order.period, "group_id": order.group_id, "group_name": order.group_name, "play_type": order.play_type, "amount": order.amount, "status": "expired"},
            service_name="wss_sender",
        )
    if orders:
        await session.commit()
    return len(orders)
