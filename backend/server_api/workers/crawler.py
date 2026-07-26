from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from server_api.db import DrawResult

from server_api.services.draws import upsert_draw


SMALL_MAX_BY_SITE = {"pc28": 13, "macao": 24, "australia": 18, "norway": 13}


def normalize_result(site: str, total: int) -> str:
    size = "小" if total <= SMALL_MAX_BY_SITE.get(site, 13) else "大"
    parity = "双" if total % 2 == 0 else "单"
    return f"{size}{parity}"


async def crawl_site(
    session: AsyncSession,
    *,
    site: str,
    history_count: int,
    fetch_records: Callable[[str, int], list[dict[str, Any]]],
) -> int:
    written = 0
    for record in fetch_records(site, history_count):
        period = str(record.get("period") or "").strip()
        total_value = record.get("sum")
        if not period or total_value is None:
            continue
        try:
            total = int(total_value)
        except (TypeError, ValueError):
            continue
        existing = await session.scalar(
            select(DrawResult.id).where(DrawResult.site == site, DrawResult.period == period)
        )
        await upsert_draw(
            session,
            site=site,
            period=period,
            result=normalize_result(site, total),
            total=total,
            commit=False,
        )
        if existing is None:
            written += 1
    await session.commit()
    return written
