from __future__ import annotations

from datetime import timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session, require_admin
from server_api.dependencies import current_user_id
from server_api.services.draws import analyze, history, upsert_draw
from server_api.workers.current_period import SUPPORTED_CURRENT_PERIOD_SITES, fetch_current_period


router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


class DrawRequest(BaseModel):
    site: str = Field(min_length=1, max_length=32)
    period: str = Field(min_length=1, max_length=64)
    result: str = Field(min_length=1, max_length=16)
    total: int | None = None


def serialize(row) -> dict[str, object]:
    return {"site": row.site, "period": row.period, "result": row.result, "total": row.total}


@router.put("/v1/admin/draws")
async def write_draw(payload: DrawRequest, session: Session, _: None = Depends(require_admin)):
    return serialize(await upsert_draw(session, **payload.model_dump()))


@router.get("/v1/draws/{site}/history")
async def read_history(site: str, session: Session, _: int = Depends(current_user_id), limit: int = Query(50, ge=1, le=500)):
    return {"items": [serialize(row) for row in await history(session, site, limit)]}


@router.get("/v1/draws/{site}/current")
async def read_current_draw(site: str, _: int = Depends(current_user_id)):
    if site not in SUPPORTED_CURRENT_PERIOD_SITES:
        raise HTTPException(status_code=422, detail="不支持的站点")
    current = fetch_current_period(site)
    if current is None:
        raise HTTPException(status_code=503, detail="当前期数据暂不可用")
    next_time = current.betting_deadline_at
    if next_time is not None:
        if next_time.tzinfo is None:
            next_time = next_time.replace(tzinfo=timezone.utc)
        else:
            next_time = next_time.astimezone(timezone.utc)
    return {
        "site": site,
        "current_period": current.current_period,
        "next_period": current.period,
        "next_time": next_time.isoformat() if next_time else None,
    }


@router.get("/v1/analysis/frequency")
async def frequency(
    site: str,
    session: Session,
    _: int = Depends(current_user_id),
    history_count: int = Query(50, ge=1, le=500),
    confidence_threshold: int = Query(45, ge=0, le=100),
    target_period: str = Query(default="", max_length=64),
):
    return analyze(
        site,
        await history(session, site, history_count),
        history_count,
        confidence_threshold,
        target_period,
    )
