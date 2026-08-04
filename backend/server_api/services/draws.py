from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import DrawResult


COMPOSITE_PLAY_ORDER = ("小单", "大双", "小双", "大单")
PLAY_ORDER = ("小", "单", "大", "双", *COMPOSITE_PLAY_ORDER)


async def upsert_draw(
    session: AsyncSession, *, site: str, period: str, result: str, total: int | None, commit: bool = True
) -> DrawResult:
    row = await session.scalar(select(DrawResult).where(DrawResult.site == site, DrawResult.period == period))
    if row is None:
        row = DrawResult(site=site, period=period, result=result, total=total)
        session.add(row)
    else:
        row.result, row.total, row.updated_at = result, total, datetime.utcnow()
    if commit:
        await session.commit()
        await session.refresh(row)
    else:
        await session.flush()
    return row


async def history(session: AsyncSession, site: str, limit: int) -> list[DrawResult]:
    rows = (await session.scalars(
        select(DrawResult)
        .where(DrawResult.site == site)
    )).all()
    # Sorting in Python keeps numeric periods correct and works on SQLite/PostgreSQL.
    rows.sort(key=lambda row: _period_sort_key(row.period), reverse=True)
    return list(reversed(rows[:limit]))


def _period_sort_key(period: str) -> tuple[int, int | str]:
    return (1, int(period)) if period.isdigit() else (0, period)


def analyze(
    site: str,
    rows: list[DrawResult],
    history_count: int,
    confidence_threshold: int,
    target_period: str = "",
) -> dict[str, object]:
    rows = rows[-max(1, history_count):]
    composite = [row for row in rows if row.result in COMPOSITE_PLAY_ORDER]
    totals = [row.total for row in rows if isinstance(row.total, int)]
    counts = {play: 0 for play in PLAY_ORDER}
    for row in composite:
        counts[row.result] += 1
        counts[row.result[0]] += 1
        counts[row.result[1]] += 1
    sample_count = len(composite)
    probabilities = {key: (value * 100.0 / sample_count if sample_count else 0.0) for key, value in counts.items()}
    excluded = min(COMPOSITE_PLAY_ORDER, key=lambda play: (probabilities[play], COMPOSITE_PLAY_ORDER.index(play))) if sample_count else ""
    selected = [play for play in COMPOSITE_PLAY_ORDER if play != excluded]
    highest = max((probabilities[play] for play in selected), default=0.0)
    return {
        "site": site,
        "period": str(target_period),
        # This is the analysis snapshot time, not merely the latest source-row time.
        # It tells the desktop when the server last re-evaluated this target period.
        "updated_at": datetime.utcnow().isoformat(),
        "requested_history_count": int(history_count),
        "sample_count": sample_count,
        "number_sample_count": len(totals),
        "number_probabilities": {str(target): (sum(value == target for value in totals) * 100.0 / len(totals) if totals else 0.0) for target in (13, 14)},
        "play_probabilities": probabilities, "excluded_play": excluded, "selected_plays": selected,
        "highest_selected_probability": highest, "confidence_threshold": confidence_threshold,
        "should_bet": bool(sample_count and highest >= confidence_threshold),
    }
