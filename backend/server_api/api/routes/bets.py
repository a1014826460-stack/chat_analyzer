from __future__ import annotations

from typing import Annotated
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session
from server_api.db import AuditEvent, BetOrder
from server_api.dependencies import current_user_id


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
    session: AsyncSession, *, bet_id: int, user_id: int, status_value: str, audit_action: str
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
    await session.commit()
    await session.refresh(row)
    return row


@router.post("/v1/bets/{bet_id}/skip")
async def skip_bet(bet_id: int, session: Session, user_id: UserId):
    return serialize(await _transition_pending_order(
        session, bet_id=bet_id, user_id=user_id, status_value="skipped", audit_action="bet_skipped"
    ))


@router.post("/v1/bets/{bet_id}/expire")
async def expire_bet(bet_id: int, session: Session, user_id: UserId):
    return serialize(await _transition_pending_order(
        session, bet_id=bet_id, user_id=user_id, status_value="expired", audit_action="bet_expired"
    ))


@router.get("/v1/audit-events")
async def audit_events(session: Session, user_id: UserId):
    rows = (await session.scalars(select(AuditEvent).where(AuditEvent.user_id == user_id).order_by(AuditEvent.id))).all()
    return {"items": [{"action": row.action, "resource_id": row.resource_id} for row in rows]}
