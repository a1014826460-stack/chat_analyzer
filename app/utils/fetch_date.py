from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from app.models import DrawInfo


logger = logging.getLogger(__name__)
_last_good_draw: dict[str, DrawInfo] = {}
_SITE_INTERVAL_SEC: dict[str, int] = {"pc28": 210, "macao": 180, "australia": 180, "norway": 210}


def set_proxy_settings(settings: dict) -> None:
    enabled = bool(settings.get("proxy_enabled", False))
    http_proxy = str(settings.get("proxy_http", "")).strip()
    https_proxy = str(settings.get("proxy_https", "")).strip() or http_proxy

    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(key, None)

    if enabled and http_proxy:
        os.environ["http_proxy"] = http_proxy
        os.environ["HTTP_PROXY"] = http_proxy
    if enabled and https_proxy:
        os.environ["https_proxy"] = https_proxy
        os.environ["HTTPS_PROXY"] = https_proxy


def site_list() -> list[str]:
    return list(_SITE_INTERVAL_SEC)


def site_label(site: str) -> str:
    labels = {
        "pc28": "PC28",
        "macao": "Macao",
        "australia": "Australia",
        "norway": "Norway",
    }
    return labels.get(site, site)


def fetch_pc_28_date() -> dict[str, Any]:
    return _synthetic_draw_payload("pc28")


def fetch_macao_date() -> dict[str, Any]:
    return _synthetic_draw_payload("macao")


def fetch_australia_date(number: str = "") -> dict[str, Any]:
    return _synthetic_draw_payload("australia")


def fetch_norway_date() -> dict[str, Any]:
    return _synthetic_draw_payload("norway")


_FETCHERS = {
    "pc28": fetch_pc_28_date,
    "macao": fetch_macao_date,
    "australia": fetch_australia_date,
    "norway": fetch_norway_date,
}


def extract_draw_info(site: str, data: dict[str, Any] | None = None) -> DrawInfo:
    if site not in _FETCHERS:
        logger.warning("Unknown site %s; returning empty draw info", site)
        return DrawInfo(current_period="")
    payload = data or _FETCHERS[site]()
    return _parse_generic(site, payload)


def fetch_all_draw_infos() -> dict[str, DrawInfo]:
    result: dict[str, DrawInfo] = {}
    for site in site_list():
        try:
            result[site] = extract_draw_info(site)
        except Exception:
            result[site] = _extrapolate_fallback(site)
        _last_good_draw[site] = result[site]
    return result


def _extrapolate_fallback(site: str) -> DrawInfo:
    previous = _last_good_draw.get(site)
    if previous is None:
        return DrawInfo(current_period="")

    interval = _SITE_INTERVAL_SEC.get(site, 180)
    now = datetime.now()
    current_time = previous.current_time or now
    next_time = previous.next_time or (current_time + timedelta(seconds=interval))
    while next_time <= now:
        current_time = next_time
        next_time = current_time + timedelta(seconds=interval)

    return DrawInfo(
        current_period=_period_after(previous.current_period, 0),
        current_time=current_time,
        next_countdown=max(0, int((next_time - now).total_seconds())),
        next_period=_period_after(previous.current_period, 1),
        next_time=next_time,
        auto_period=_period_after(previous.current_period, 0),
    )


def _synthetic_draw_payload(site: str) -> dict[str, Any]:
    interval = _SITE_INTERVAL_SEC.get(site, 180)
    now = datetime.now()
    base = now.replace(second=0, microsecond=0)
    step = int(now.timestamp()) // interval
    current_time = datetime.fromtimestamp(step * interval)
    next_time = current_time + timedelta(seconds=interval)
    period = f"{now:%Y%m%d}{step % 1000:03d}"
    return {
        "site": site,
        "current_period": period,
        "current_time": current_time.isoformat(),
        "next_time": next_time.isoformat(),
    }


def _parse_generic(site: str, data: dict[str, Any]) -> DrawInfo:
    current_period = str(data.get("current_period", ""))
    current_time = _parse_dt(data.get("current_time"))
    next_time = _parse_dt(data.get("next_time"))
    next_period = str(data.get("next_period", "")) or _period_after(current_period, 1)
    next_countdown = max(0, int((next_time - datetime.now()).total_seconds())) if next_time else 0
    return DrawInfo(
        current_period=current_period,
        current_time=current_time,
        next_countdown=next_countdown,
        next_period=next_period,
        next_time=next_time,
        auto_period=current_period,
    )


def _period_after(period: str, delta: int) -> str:
    if not period or not period.isdigit():
        return ""
    return str(int(period) + delta)


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
