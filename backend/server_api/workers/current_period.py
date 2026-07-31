"""Adapters for the official current-period endpoints used to gate sending."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from server_api.workers import history_sources


@dataclass(frozen=True)
class CurrentPeriod:
    period: str
    betting_deadline_at: datetime | None


def fetch_current_period(site: str) -> CurrentPeriod | None:
    payload = _fetch_payload(site)
    if site == "pc28":
        if not isinstance(payload, dict):
            return None
        rows = payload.get("recent_records")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            current = str(rows[0].get("draw_number") or rows[0].get("qishu") or "").strip()
            countdown_payload = payload.get("countdown")
            next_period = ""
            if isinstance(countdown_payload, dict):
                next_period = str(countdown_payload.get("next_draw_number") or "").strip()
                countdown = _int_or_none(countdown_payload.get("countdown_seconds"))
            else:
                countdown = _int_or_none(countdown_payload)
            deadline = datetime.now() + timedelta(seconds=countdown) if countdown is not None else None
            period = next_period or _increment_period(current)
            return CurrentPeriod(period, deadline) if period else None
        issues = payload.get("issue", [])
        if not isinstance(issues, list) or not issues or not isinstance(issues[0], dict):
            return None
        current = str(issues[0].get("qishu") or "").strip()
        return CurrentPeriod(_increment_period(current), _parse_timestamp(issues[0].get("next"))) if current else None
    if site == "macao":
        rows = _nested(payload, "data.drawList")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        row = rows[0]
        period = str(row.get("nextQihao") or _increment_period(str(row.get("qihao") or ""))).strip()
        return CurrentPeriod(period, _parse_timestamp(row.get("nextOpenTime"))) if period else None
    if site == "australia":
        if not isinstance(payload, dict):
            return None
        next_row = payload.get("next") if isinstance(payload.get("next"), dict) else {}
        current = str(payload.get("qi") or payload.get("current_period") or "").strip()
        period = str(next_row.get("qi") or payload.get("next_period") or _increment_period(current)).strip()
        return CurrentPeriod(period, _parse_timestamp(next_row.get("time") or payload.get("next_time"))) if period else None
    if site == "norway":
        rows = payload.get("result", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        row = rows[0]
        period = str(row.get("nextexpect") or _increment_period(str(row.get("expect") or ""))).strip()
        return CurrentPeriod(period, _parse_timestamp(row.get("next"))) if period else None
    raise ValueError(f"unsupported site: {site}")


def _fetch_payload(site: str) -> Any:
    if site == "pc28":
        return history_sources._get_json(
            "https://jnd28-yc.vip/api/dashboard",
            params={"limit": "5"},
            headers={"referer": "https://jnd28-yc.vip/"},
        )
    if site == "macao":
        return history_sources._get_json(
            "https://macao.zhifu.qpon/api/openApi/lottery/draw",
            params={"pageNum": "1", "pageSize": "1"},
            headers={"origin": "https://288.pet", "referer": "https://288.pet/"},
        )
    if site == "australia":
        return history_sources._get_json(
            "https://gaga28.com/api/ajax2.php",
            params={"action": "beijing28"},
            headers={"origin": "https://gaga28.com", "referer": "https://gaga28.com/az28.php"},
        )
    if site == "norway":
        return history_sources._get_json(
            "https://p17-qq-server.vqimpic.cc/v1/selfapi/lottery",
            params={"code": "nw28", "rows": "1"},
            headers={"origin": "https://norzx.com", "referer": "https://norzx.com/"},
        )
    raise ValueError(f"unsupported site: {site}")


def _nested(value: object, path: str) -> object:
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _increment_period(value: str) -> str:
    value = value.strip()
    if not value.isdigit():
        return ""
    return str(int(value) + 1).zfill(len(value))


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return datetime.fromtimestamp(timestamp) if timestamp > 0 else None
