from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from app.models import DrawInfo


logger = logging.getLogger(__name__)

_last_good_draw: dict[str, DrawInfo] = {}
_SITE_INTERVAL_SEC: dict[str, int] = {
    "pc28": 210,
    "macao": 180,
    "australia": 180,
    "norway": 210,
}
_SITE_META: dict[str, dict[str, str]] = {
    "pc28": {"label": "PC28", "url": "https://1pc.cc"},
    "macao": {"label": "澳门", "url": "https://288.pet"},
    "australia": {"label": "澳洲", "url": "https://gaga28.com"},
    "norway": {"label": "挪威", "url": "https://norzx.com"},
}
_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%m-%d %H:%M:%S",
    "%Y%m%d%H%M%S",
    "%Y%m%d",
)
_MONTH_DAY_FORMATS = {"%m-%d %H:%M:%S"}


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
    return list(_SITE_META)


def site_label(site: str) -> str:
    return _SITE_META.get(site, {}).get("label", site)


def site_meta(site: str) -> dict[str, str]:
    return dict(_SITE_META.get(site, {}))


def fetch_pc_28_date() -> dict[str, Any]:
    return _get_json(
        "https://1pc.cc/data/get/checkData",
        params={"type": "jnd28", "sf": "1", "ms": "zh"},
        headers={"referer": "https://1pc.cc/", "x-requested-with": "XMLHttpRequest"},
    )


def fetch_macao_date() -> dict[str, Any]:
    return _get_json(
        "https://macao.zhifu.qpon/api/openApi/lottery/draw",
        params={"pageNum": "1", "pageSize": "20"},
        headers={"origin": "https://288.pet", "referer": "https://288.pet/"},
    )


def fetch_australia_date(number: str = "") -> dict[str, Any]:
    data = {"action": "beijing28"}
    if number:
        data["number"] = number
    return _post_json(
        "https://gaga28.com/api/ajax2.php",
        data=data,
        headers={
            "origin": "https://gaga28.com",
            "referer": "https://gaga28.com/az28.php",
            "x-requested-with": "XMLHttpRequest",
        },
    )


def fetch_norway_date() -> dict[str, Any]:
    return _get_json(
        "https://p17-qq-server.vqimpic.cc/v1/selfapi/lottery",
        params={"code": "nw28", "rows": "10"},
        headers={"origin": "https://norzx.com", "referer": "https://norzx.com/"},
    )


_FETCHERS = {
    "pc28": fetch_pc_28_date,
    "macao": fetch_macao_date,
    "australia": fetch_australia_date,
    "norway": fetch_norway_date,
}


def extract_draw_info(site: str, data: dict[str, Any] | None = None) -> DrawInfo:
    if site not in _FETCHERS:
        logger.warning("未知线路 %s，返回空数据", site)
        return DrawInfo(current_period="")
    payload = data if data is not None else _FETCHERS[site]()
    try:
        info = _parse_draw_info_payload(site, payload)
    except Exception as exc:
        if data is None:
            try:
                payload = _FETCHERS[site]()
                info = _parse_draw_info_payload(site, payload)
                if info.current_period:
                    logger.info("[%s] 开奖信息首次解析失败后重试成功: %s", site_label(site), exc)
                    _last_good_draw[site] = info
                    return info
            except Exception:
                logger.debug("[%s] 开奖信息重试仍失败", site_label(site), exc_info=True)
        fallback = _extrapolate_fallback(site)
        if fallback.current_period:
            logger.warning("[%s] 开奖信息解析失败，使用上一份有效数据: %s", site_label(site), exc)
        else:
            logger.warning("[%s] 开奖信息解析失败，且没有可用回退数据: %s", site_label(site), exc)
        return fallback
    if info.current_period:
        _last_good_draw[site] = info
    return info


def _parse_draw_info_payload(site: str, payload: dict[str, Any]) -> DrawInfo:
    if site == "pc28":
        return _parse_pc28(payload)
    if site == "macao":
        return _parse_macao(payload)
    if site == "australia":
        return _parse_australia(payload)
    if site == "norway":
        return _parse_norway(payload)
    return DrawInfo(current_period="")


def fetch_all_draw_infos() -> dict[str, DrawInfo]:
    result: dict[str, DrawInfo] = {}
    with ThreadPoolExecutor(max_workers=len(_FETCHERS)) as executor:
        futures = {executor.submit(extract_draw_info, site): site for site in site_list()}
        for future in as_completed(futures):
            site = futures[future]
            try:
                result[site] = future.result()
            except Exception as exc:
                logger.warning("[%s] 线路获取失败，使用回退数据: %s", site_label(site), exc)
                result[site] = _extrapolate_fallback(site)
    return result


def _get_json(url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return _request_json(url, data=None, headers=headers)


def _post_json(url: str, data: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request_headers = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}
    if headers:
        request_headers.update(headers)
    return _request_json(url, data=encoded, headers=request_headers)


def _request_json(url: str, data: bytes | None, headers: dict[str, str] | None) -> dict[str, Any]:
    request_headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError:
        raise
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected payload from {url}")
    return payload


def _parse_pc28(data: dict[str, Any]) -> DrawInfo:
    issue_list = data.get("issue", [])
    if not isinstance(issue_list, list) or not issue_list:
        raise ValueError("PC28: API 返回空 issue 列表")
    first = issue_list[0]
    current_period = _str_val(first.get("qishu"))
    current_time = _parse_ts(first.get("time"))
    next_time = _parse_unix_ts(first.get("next"))
    return DrawInfo(
        current_period=current_period,
        current_time=current_time,
        next_countdown=_countdown_from_ts(first.get("next")),
        next_period=_increment_period(current_period),
        next_time=next_time,
        auto_period=current_period,
    )


def _parse_macao(data: dict[str, Any]) -> DrawInfo:
    draw_list = _deep_get(data, "data.drawList")
    if not isinstance(draw_list, list) or not draw_list:
        raise ValueError("澳门: API 返回空 drawList")
    first = draw_list[0]
    current_period = _str_val(first.get("qihao"))
    return DrawInfo(
        current_period=current_period,
        current_time=_parse_ts(first.get("opentime")),
        next_countdown=0,
        next_period=_str_val(first.get("nextQihao")) or _increment_period(current_period),
        next_time=_parse_ts(first.get("nextOpenTime")),
        auto_period=current_period,
    )


def _parse_australia(data: dict[str, Any]) -> DrawInfo:
    current_period = _str_val(data.get("qi") or data.get("current_period"))
    nxt = data.get("next") if isinstance(data.get("next"), dict) else {}
    next_period = _str_val((nxt or {}).get("qi") or data.get("next_period")) or _increment_period(current_period)
    next_countdown = _int_val((nxt or {}).get("sec") or data.get("next_countdown"))
    return DrawInfo(
        current_period=current_period,
        current_time=_parse_ts(data.get("time") or data.get("current_time")),
        next_countdown=next_countdown,
        next_period=next_period,
        next_time=_parse_ts((nxt or {}).get("time") or data.get("next_time")),
        auto_period=current_period,
    )


def _parse_norway(data: dict[str, Any]) -> DrawInfo:
    lottery_data = data.get("lottery_data", [])
    if not isinstance(lottery_data, list) or not lottery_data:
        raise ValueError("挪威: API 返回空 lottery_data")
    first = lottery_data[0]
    current_period = _str_val(first.get("expect"))
    return DrawInfo(
        current_period=current_period,
        current_time=_parse_ts(first.get("opentime")),
        next_countdown=_countdown_from_ts(first.get("next")),
        next_period=_str_val(first.get("nextexpect")) or _increment_period(current_period),
        next_time=_parse_unix_ts(first.get("next")),
        auto_period=current_period,
    )


def _extrapolate_fallback(site: str) -> DrawInfo:
    previous = _last_good_draw.get(site)
    if previous is None or not previous.current_period:
        return DrawInfo(current_period="")

    interval = _SITE_INTERVAL_SEC.get(site, 180)
    now = datetime.now()
    current_time = previous.current_time or now
    next_time = previous.next_time or (current_time + timedelta(seconds=interval))
    while next_time <= now:
        current_time = next_time
        next_time = current_time + timedelta(seconds=interval)

    return DrawInfo(
        current_period=_increment_period(previous.current_period, 0),
        current_time=current_time,
        next_countdown=max(0, int((next_time - now).total_seconds())),
        next_period=_increment_period(previous.current_period),
        next_time=next_time,
        auto_period=_increment_period(previous.current_period, 0),
    )


def _deep_get(obj: Any, path: str) -> Any:
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and key.isdigit():
            obj = obj[int(key)]
        else:
            return None
    return obj


def _str_val(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value))
    return str(value).strip()


def _int_val(value: object) -> int:
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def _parse_ts(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _parse_unix_ts(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_unix_ts(text)
    for fmt in _TS_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt in _MONTH_DAY_FORMATS:
            parsed = parsed.replace(year=datetime.now().year)
        return parsed
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _countdown_from_ts(value: object) -> int:
    ts = _int_val(value)
    if ts <= 0:
        return 0
    if ts > 10_000_000_000:
        ts //= 1000
    return max(0, ts - int(datetime.now().timestamp()))


def _parse_unix_ts(value: object) -> datetime | None:
    ts = _int_val(value)
    if ts <= 0:
        return None
    if ts > 100_000_000_000_000:
        ts //= 1_000_000
    elif ts > 10_000_000_000:
        ts //= 1000
    return datetime.fromtimestamp(ts)


def _increment_period(period: str, delta: int = 1) -> str:
    if not period or not period.isdigit():
        return ""
    return str(int(period) + delta).zfill(len(period))
