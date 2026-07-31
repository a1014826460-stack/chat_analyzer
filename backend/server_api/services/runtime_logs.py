"""Persist and safely query structured runtime events."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import RuntimeLogEvent


LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})
LOG_CATEGORIES = frozenset({"user_action", "system", "exception", "third_party", "strategy"})
_SECRET_KEY = re.compile(r"(?:authorization|password|secret|token|api[_-]?key|user[_-]?sig|signature|sig)", re.I)
_SECRET_VALUE = re.compile(r"(?i)(?:bearer\s+|api[_-]?key[=:]\s*|token[=:]\s*)[^\s,;]+")


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
        conditions = [RuntimeLogEvent.user_id == user_id]
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
        "created_at": row.created_at.isoformat(),
    }
