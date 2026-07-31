from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session
from server_api.dependencies import current_user_id
from server_api.services.runtime_logs import LOG_CATEGORIES, LOG_LEVELS, RuntimeLogService, serialize_runtime_log


router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(current_user_id)]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="时间格式必须为 ISO 8601") from exc


@router.get("/v1/runtime-logs")
async def get_runtime_logs(
    session: Session,
    user_id: UserId,
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"] | None = None,
    category: Literal["user_action", "system", "exception", "third_party", "strategy"] | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    start_at: str | None = None,
    end_at: str | None = None,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
):
    start = _parse_time(start_at)
    end = _parse_time(end_at)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="开始时间不能晚于结束时间")
    rows, has_more = await RuntimeLogService(session).page_for_user(
        user_id=user_id,
        level=level,
        category=category,
        keyword=keyword.strip() if keyword else None,
        start_at=start,
        end_at=end,
        before_id=before_id,
        limit=limit,
    )
    return {
        "items": [serialize_runtime_log(row) for row in rows],
        "next_before_id": rows[-1].id if has_more and rows else None,
        "has_more": has_more,
    }
