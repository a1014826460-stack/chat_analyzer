from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session, require_admin
from server_api.dependencies import current_user_id
from server_api.services.draws import analyze, history, upsert_draw


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


@router.get("/v1/analysis/frequency")
async def frequency(site: str, session: Session, _: int = Depends(current_user_id), history_count: int = Query(50, ge=1, le=500), confidence_threshold: int = Query(45, ge=0, le=100)):
    return analyze(site, await history(session, site, history_count), history_count, confidence_threshold)
