from __future__ import annotations

from typing import Annotated
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session
from server_api.db import AuditEvent, BetAttempt, BetOrder, StrategyEvent
from server_api.dependencies import current_user_id
from server_api.services.strategy_events import add_order_event
from server_api.services.bet_statistics import betting_statistics
from server_api.services.runtime_logs import RuntimeLogService


router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(current_user_id)]


class BetRequest(BaseModel):
    site: str = Field(min_length=1, max_length=32)
    period: str = Field(min_length=1, max_length=64)
    group_id: str = Field(min_length=1, max_length=255)
    play_type: str = Field(min_length=1, max_length=16)
    amount: float = Field(gt=0)
    confirmation_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


def serialize(row: BetOrder) -> dict[str, object]:
    return {"id": row.id, "site": row.site, "period": row.period, "group_id": row.group_id, "play_type": row.play_type, "amount": row.amount, "status": row.status, "confirmation_deadline_at": row.confirmation_deadline_at.isoformat() if row.confirmation_deadline_at else None}


async def audit(session: AsyncSession, user_id: int, action: str, bet_id: int) -> None:
    session.add(AuditEvent(user_id=user_id, action=action, resource_type="bet_order", resource_id=str(bet_id)))
    await RuntimeLogService(session).write(
        user_id=user_id,
        level="INFO",
        category="user_action",
        message={
            "bet_created": "已创建下注订单",
            "bet_confirmed": "已确认下注订单",
            "bet_skipped": "已跳过下注订单",
            "bet_expired": "下注订单已过期",
        }.get(action, action),
        details={"bet_id": bet_id, "action": action},
    )


@router.post("/v1/bets", status_code=status.HTTP_201_CREATED)
async def create_bet(payload: BetRequest, response: Response, session: Session, user_id: UserId):
    row = await session.scalar(select(BetOrder).where(
        BetOrder.user_id == user_id, BetOrder.site == payload.site, BetOrder.period == payload.period,
        BetOrder.group_id == payload.group_id, BetOrder.play_type == payload.play_type,
    ))
    if row is not None:
        response.status_code = status.HTTP_200_OK
        return serialize(row)
    data = payload.model_dump()
    timeout_seconds = data.pop("confirmation_timeout_seconds")
    if timeout_seconds is not None:
        data["confirmation_deadline_at"] = datetime.utcnow() + timedelta(seconds=timeout_seconds)
    row = BetOrder(user_id=user_id, **data)
    session.add(row)
    await session.flush()
    await audit(session, user_id, "bet_created", row.id)
    await session.commit()
    await session.refresh(row)
    return serialize(row)


@router.post("/v1/bets/{bet_id}/confirm")
async def confirm_bet(bet_id: int, session: Session, user_id: UserId):
    row = await session.scalar(select(BetOrder).where(BetOrder.id == bet_id, BetOrder.user_id == user_id))
    if row is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    updated = await session.execute(
        update(BetOrder)
        .where(
            BetOrder.id == bet_id,
            BetOrder.user_id == user_id,
            BetOrder.status == "pending_confirmation",
        )
        .values(status="confirmed")
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=409, detail="订单状态不允许确认")
    await audit(session, user_id, "bet_confirmed", row.id)
    add_order_event(session, row, event_type="confirmed", prefix="客户端已确认下注")
    await session.commit()
    await session.refresh(row)
    return serialize(row)


@router.get("/v1/bets/pending")
async def pending_bets(session: Session, user_id: UserId):
    rows = (await session.scalars(
        select(BetOrder)
        .where(BetOrder.user_id == user_id, BetOrder.status == "pending_confirmation")
        .order_by(BetOrder.created_at)
    )).all()
    return {"items": [serialize(row) for row in rows]}


async def _transition_pending_order(
    session: AsyncSession, *, bet_id: int, user_id: int, status_value: str, audit_action: str, event_prefix: str
) -> BetOrder:
    row = await session.scalar(select(BetOrder).where(BetOrder.id == bet_id, BetOrder.user_id == user_id))
    if row is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    updated = await session.execute(
        update(BetOrder)
        .where(BetOrder.id == bet_id, BetOrder.user_id == user_id, BetOrder.status == "pending_confirmation")
        .values(status=status_value)
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=409, detail="订单状态不允许此操作")
    await audit(session, user_id, audit_action, bet_id)
    add_order_event(session, row, event_type=status_value, prefix=event_prefix)
    await session.commit()
    await session.refresh(row)
    return row


@router.post("/v1/bets/{bet_id}/skip")
async def skip_bet(bet_id: int, session: Session, user_id: UserId):
    return serialize(await _transition_pending_order(
        session, bet_id=bet_id, user_id=user_id, status_value="skipped", audit_action="bet_skipped", event_prefix="客户端已跳过下注"
    ))


@router.post("/v1/bets/{bet_id}/expire")
async def expire_bet(bet_id: int, session: Session, user_id: UserId):
    return serialize(await _transition_pending_order(
        session, bet_id=bet_id, user_id=user_id, status_value="expired", audit_action="bet_expired", event_prefix="客户端标记下注过期"
    ))


@router.get("/v1/audit-events")
async def audit_events(session: Session, user_id: UserId):
    rows = (await session.scalars(select(AuditEvent).where(AuditEvent.user_id == user_id).order_by(AuditEvent.id))).all()
    return {"items": [{"action": row.action, "resource_id": row.resource_id} for row in rows]}


@router.get("/v1/bets/statistics")
async def bet_statistics(
    session: Session,
    user_id: UserId,
    site: str = Query(..., min_length=1, max_length=32),
    ai_window: int = Query(20, ge=1, le=200),
    since: str | None = Query(default=None),
):
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            since_dt = None
    return await betting_statistics(session, user_id=user_id, site=site, ai_window=ai_window, since=since_dt)


@router.get("/v1/bets/events/latest")
async def latest_bet_event(session: Session, user_id: UserId, site: str | None = Query(default=None, max_length=32)):
    conditions = [StrategyEvent.user_id == user_id]
    if site:
        conditions.append(StrategyEvent.site == site)
    latest_id = await session.scalar(select(func.max(StrategyEvent.id)).where(*conditions))
    return {"latest_id": int(latest_id or 0)}


@router.get("/v1/bets/events")
async def bet_events(
    session: Session,
    user_id: UserId,
    after_id: int = 0,
    limit: int = 100,
    site: str | None = Query(default=None, max_length=32),
    since: str | None = Query(default=None),
):
    """Return user-visible strategy and send events without exposing credentials."""
    conditions = [StrategyEvent.user_id == user_id, StrategyEvent.id > max(0, after_id)]
    if site:
        conditions.append(StrategyEvent.site == site)
    if since:
        try:
            since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            since_dt = None
        if since_dt is not None:
            conditions.append(StrategyEvent.created_at >= since_dt)
    events = (await session.scalars(
        select(StrategyEvent)
        .where(*conditions)
        .order_by(StrategyEvent.id)
        .limit(min(max(1, limit), 200))
    )).all()
    return {"items": [
        {
            "id": event.id,
            "site": event.site,
            "period": event.period,
            "event_type": event.event_type,
            "message": event.message,
            "created_at": event.created_at.isoformat(),
        }
        for event in events
    ]}

