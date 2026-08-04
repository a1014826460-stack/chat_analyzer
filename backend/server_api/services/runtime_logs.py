"""Persist and safely query structured runtime events."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import RuntimeLogEvent


LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})
LOG_CATEGORIES = frozenset({"user_action", "system", "exception", "third_party", "strategy"})
_SECRET_KEY = re.compile(r"(?:authorization|password|secret|token|api[_-]?key|user[_-]?sig|signature|sig)", re.I)
_SECRET_VALUE = re.compile(r"(?i)(?:bearer\s+|api[_-]?key[=:]\s*|token[=:]\s*)[^\s,;]+")
_STRATEGY_CONTEXT = re.compile(r"^【[^】]*】【[^】]*】")
_LEGACY_SENT_CONTEXT = re.compile(r"^WSS 已发送下注：【群组\s*[^】]*】【[^】]*期号\s*[^】]*】")
_LEGACY_SITE_PERIOD = re.compile(r"站点\s*([^，,]+)[，,]\s*期号\s*([^，,]+)")
_LEGACY_BRACKET_PERIOD = re.compile(r"【([^】]+)\s+期号\s+([^】]+)】")


def format_strategy_context(*, group_names: list[str] | tuple[str, ...] | None, site: str, period: str) -> str:
    labels = [str(name).strip() for name in (group_names or []) if str(name).strip()]
    group_label = "、".join(dict.fromkeys(labels)) or "未命名群组"
    return f"【{group_label}】【{str(site).strip()} {str(period).strip()}】"


def format_runtime_log_for_display(row: RuntimeLogEvent, *, group_name_map: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a display-safe row, repairing legacy strategy-log context on read."""
    payload = serialize_runtime_log(row)
    if row.category != "strategy":
        return payload
    details = payload["details"] if isinstance(payload["details"], Mapping) else {}
    message = str(payload["message"])
    site = str(details.get("site") or "").strip()
    period = str(details.get("period") or "").strip()
    legacy_match = _LEGACY_BRACKET_PERIOD.search(message)
    if legacy_match:
        site = site or legacy_match.group(1).strip()
        period = period or legacy_match.group(2).strip()
    plain_match = _LEGACY_SITE_PERIOD.search(message)
    if plain_match:
        site = site or plain_match.group(1).strip()
        period = period or plain_match.group(2).strip()
    group_map = {str(key): str(value).strip() for key, value in dict(group_name_map or {}).items() if str(value).strip()}
    group_id = str(details.get("group_id") or "").strip()
    raw_group_names = details.get("group_names") if isinstance(details.get("group_names"), list) else []
    group_names = [
        str(value).strip()
        for value in raw_group_names
        if str(value).strip() and str(value).strip() != "未命名群组"
    ]
    if group_id and group_id in group_map:
        group_names = [group_map[group_id]]
    elif not group_names and group_map:
        group_names = list(dict.fromkeys(group_map.values()))
    elif not group_names:
        group_names = [str(value).strip() for value in raw_group_names if str(value).strip()]
    body = _STRATEGY_CONTEXT.sub("", message).strip()
    body = _LEGACY_SENT_CONTEXT.sub("WSS 已发送下注：", body).strip()
    if site and period:
        payload["message"] = f"{format_strategy_context(group_names=group_names, site=site, period=period)}{body}"
    return payload


def sanitize_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(str(value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def sanitize_value(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): sanitize_value(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[REDACTED]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


class RuntimeLogService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(
        self,
        *,
        level: str,
        category: str,
        message: str,
        user_id: int | None = None,
        details: Mapping[str, Any] | None = None,
        request_url: str | None = None,
        duration_ms: int | None = None,
        status_code: int | None = None,
        exception_traceback: str | None = None,
        service_name: str = "api",
    ) -> RuntimeLogEvent:
        normalized_level = str(level).upper()
        if normalized_level not in LOG_LEVELS:
            raise ValueError("invalid runtime log level")
        normalized_category = str(category).lower()
        if normalized_category not in LOG_CATEGORIES:
            raise ValueError("invalid runtime log category")
        row = RuntimeLogEvent(
            user_id=user_id,
            level=normalized_level,
            category=normalized_category,
            message=str(sanitize_value(message))[:1024],
            details_json=json.dumps(sanitize_value(dict(details or {})), ensure_ascii=False, separators=(",", ":")),
            request_url=sanitize_url(request_url),
            duration_ms=max(0, int(duration_ms)) if duration_ms is not None else None,
            status_code=int(status_code) if status_code is not None else None,
            exception_traceback=str(sanitize_value(exception_traceback)) if exception_traceback else None,
            service_name=str(service_name)[:64],
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def page_for_user(
        self,
        *,
        user_id: int,
        level: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> tuple[list[RuntimeLogEvent], bool]:
        conditions = [or_(RuntimeLogEvent.user_id == user_id, RuntimeLogEvent.user_id.is_(None))]
        if level:
            conditions.append(RuntimeLogEvent.level == level)
        if category:
            conditions.append(RuntimeLogEvent.category == category)
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(or_(RuntimeLogEvent.message.ilike(pattern), RuntimeLogEvent.details_json.ilike(pattern)))
        if start_at:
            conditions.append(RuntimeLogEvent.created_at >= start_at)
        if end_at:
            conditions.append(RuntimeLogEvent.created_at <= end_at)
        if before_id:
            conditions.append(RuntimeLogEvent.id < before_id)
        rows = (await self._session.scalars(
            select(RuntimeLogEvent).where(*conditions).order_by(RuntimeLogEvent.id.desc()).limit(limit + 1)
        )).all()
        return rows[:limit], len(rows) > limit


def serialize_runtime_log(row: RuntimeLogEvent) -> dict[str, Any]:
    created_at = row.created_at.replace(tzinfo=timezone.utc)
    return {
        "id": row.id,
        "level": row.level,
        "category": row.category,
        "message": row.message,
        "details": json.loads(row.details_json or "{}"),
        "request_url": row.request_url,
        "duration_ms": row.duration_ms,
        "status_code": row.status_code,
        "exception_traceback": row.exception_traceback,
        "service_name": row.service_name,
        "created_at": created_at.isoformat(),
    }
