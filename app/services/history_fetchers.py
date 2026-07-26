from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.models.auto_bet import DrawResult
from app.utils.history_records import (
    fetch_history_records,
    history_record_limit,
    supported_history_record_counts,
)


logger = logging.getLogger(__name__)

_SMALL_MAX_BY_SITE = {
    "pc28": 13,
    "macao": 24,
    "australia": 18,
    "norway": 13,
}


def normalize_result_label(site: str, result: object) -> str:
    """Convert a numeric sum to a betting label such as 大双 or 小单."""
    try:
        total = int(float(str(result).strip()))
    except (TypeError, ValueError):
        return str(result or "").strip()

    size = "小" if total <= _SMALL_MAX_BY_SITE.get(site, 13) else "大"
    parity = "双" if total % 2 == 0 else "单"
    return f"{size}{parity}"


class HistoryFetcher:
    """Fetch and convert normalized history records into DrawResult objects."""

    def fetch(self, site: str, count: int = 20) -> list[DrawResult]:
        count = min(max(1, int(count)), history_fetch_limit(site))
        try:
            records = fetch_history_records(site, page=1, page_size=count)
        except Exception as exc:
            logger.warning("Failed to fetch history records for %s: %s", site, exc)
            return []
        results: list[DrawResult] = []
        for record in records:
            result = self._record_to_draw_result(site, record)
            if result is not None:
                results.append(result)
        return results[:count]

    def _record_to_draw_result(self, site: str, record: dict[str, Any]) -> DrawResult | None:
        period = str(record.get("period", "") or "").strip()
        if not period:
            return None
        total = record.get("sum")
        if total is None:
            return None
        open_time = record.get("open_time")
        if open_time is not None and not isinstance(open_time, datetime):
            open_time = None
        return DrawResult(
            site=str(record.get("site") or site),
            period=period,
            result=normalize_result_label(site, total),
            open_time=open_time,
            total=int(total),
        )


def history_fetch_limit(site: str) -> int:
    """Expose the remote history window supported by a site's fetcher."""
    return history_record_limit(site)


def supported_history_fetch_counts(site: str) -> tuple[int, ...]:
    """Return the UI-safe selectable history windows for a site."""
    return supported_history_record_counts(site)
