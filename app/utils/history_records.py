from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from typing import Any


HistoryRecord = dict[str, object]

_SITES = ("pc28", "australia", "macao", "norway")
_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%m-%d %H:%M:%S",
)
_MONTH_DAY_FORMATS = {"%m-%d %H:%M:%S"}
_RESULT_RE = re.compile(r"(?P<a>\d+)\s*\+\s*(?P<b>\d+)\s*\+\s*(?P<c>\d+)(?:\s*=\s*(?P<sum>\d+))?")


def apply_saved_proxy_settings() -> None:
    """Use the same persisted proxy settings as the line-selection requests."""
    from app.services.settings_service import SettingsService
    from app.utils.fetch_date import set_proxy_settings

    set_proxy_settings(SettingsService().load())


def site_list() -> list[str]:
    return list(_SITES)


def fetch_history_records(site: str, page: int = 1, page_size: int = 20) -> list[HistoryRecord]:
    normalized = _normalize_site(site)
    payload = _fetch_history_payload(normalized, page=page, page_size=page_size)
    return parse_history_records(normalized, payload)[:page_size]


def fetch_all_history_records(page: int = 1, page_size: int = 20) -> dict[str, list[HistoryRecord]]:
    return {site: fetch_history_records(site, page=page, page_size=page_size) for site in _SITES}


def parse_history_records(site: str, payload: Any) -> list[HistoryRecord]:
    normalized = _normalize_site(site)
    if normalized == "pc28":
        if not isinstance(payload, dict):
            raise ValueError("PC28 history payload must be a dict")
        return _parse_pc28_history(payload)
    if normalized == "australia":
        if not isinstance(payload, str):
            raise ValueError("Australia history payload must be HTML text")
        return parse_australia_history_html(payload)
    if normalized == "macao":
        if not isinstance(payload, dict):
            raise ValueError("Macao history payload must be a dict")
        return _parse_macao_history(payload)
    if normalized == "norway":
        if not isinstance(payload, dict):
            raise ValueError("Norway history payload must be a dict")
        return _parse_norway_history(payload)
    raise ValueError(f"unsupported site: {site}")


def parse_australia_history_html(page_html: str) -> list[HistoryRecord]:
    parser = _TableRowParser()
    parser.feed(page_html)
    records: list[HistoryRecord] = []
    for row in parser.rows:
        if len(row) < 3:
            continue
        period, open_time_text, result_text = (row[0].strip(), row[1].strip(), row[2].strip())
        numbers, total = _parse_numbers_and_sum(result_text)
        if not period.isdigit() or len(numbers) != 3:
            continue
        records.append(
            _record(
                "australia",
                period=period,
                open_time=_parse_ts(open_time_text),
                numbers=numbers,
                total=total,
                raw={"period": period, "open_time": open_time_text, "result": result_text},
            )
        )
    return records


def _fetch_history_payload(site: str, *, page: int, page_size: int) -> Any:
    if site == "pc28":
        return _get_json(
            "https://1pc.cc/data/get/getForecastByType",
            params={"game": "jnd28", "type": "zh", "sf": "1"},
            headers={"referer": "https://1pc.cc/", "x-requested-with": "XMLHttpRequest"},
        )
    if site == "australia":
        return _get_text("https://gaga28.com/az28.php", headers={"referer": "https://gaga28.com/"})
    if site == "macao":
        return _get_json(
            "https://macao.zhifu.qpon/api/openApi/lottery/draw",
            params={"pageNum": str(page), "pageSize": str(page_size)},
            headers={"origin": "https://288.pet", "referer": "https://288.pet/"},
        )
    if site == "norway":
        return _get_json(
            "https://p17-qq-server.vqimpic.cc/v1/selfapi/history",
            params={"code": "nw28", "page": str(page), "page_size": str(page_size)},
            headers={"origin": "https://norzx.com", "referer": "https://norzx.com/"},
        )
    raise ValueError(f"unsupported site: {site}")


def _parse_pc28_history(payload: dict[str, Any]) -> list[HistoryRecord]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return []
    records: list[HistoryRecord] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        period = _str_val(item.get("qishu"))
        result_text = _str_val(item.get("kjcodestr") or item.get("number") or item.get("opennum"))
        numbers, total = _parse_numbers_and_sum(result_text)
        if len(numbers) != 3:
            continue
        if total is None:
            total = _int_or_none(item.get("kjcode"))
        records.append(_record("pc28", period=period, open_time=None, numbers=numbers, total=total, raw=item))
    return records


def _parse_macao_history(payload: dict[str, Any]) -> list[HistoryRecord]:
    rows = _deep_get(payload, "data.drawList")
    if not isinstance(rows, list):
        return []
    records: list[HistoryRecord] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        period = _str_val(item.get("qihao"))
        result_text = _str_val(item.get("number") or item.get("opennum"))
        numbers, total = _parse_numbers_and_sum(result_text)
        if len(numbers) != 3:
            continue
        if total is None:
            total = _int_or_none(item.get("sum"))
        records.append(
            _record(
                "macao",
                period=period,
                open_time=_parse_ts(item.get("opentime")),
                numbers=numbers,
                total=total,
                raw=item,
            )
        )
    return records


def _parse_norway_history(payload: dict[str, Any]) -> list[HistoryRecord]:
    rows = payload.get("result", [])
    if not isinstance(rows, list):
        return []
    records: list[HistoryRecord] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        result_json = _json_dict(item.get("ResultJSON"))
        ext_result = _json_dict(item.get("ExtResult"))
        raw_numbers = result_json.get("result") or ext_result.get("input")
        numbers = [int(value) for value in raw_numbers] if _is_number_list(raw_numbers) else []
        if len(numbers) != 3:
            continue
        records.append(
            _record(
                "norway",
                period=_str_val(item.get("PeriodNo")),
                open_time=_parse_ts(item.get("DrawTime")),
                numbers=numbers,
                total=_int_or_none(ext_result.get("sum")) if ext_result else sum(numbers),
                raw=item,
            )
        )
    return records


def _record(
    site: str,
    *,
    period: str,
    open_time: datetime | None,
    numbers: list[int],
    total: int | None,
    raw: object,
) -> HistoryRecord:
    return {
        "site": site,
        "period": period,
        "open_time": open_time,
        "numbers": numbers,
        "sum": total,
        "raw": raw,
    }


def _parse_numbers_and_sum(text: object) -> tuple[list[int], int | None]:
    value = html.unescape(_str_val(text))
    match = _RESULT_RE.search(value)
    if not match:
        return [], None
    numbers = [int(match.group("a")), int(match.group("b")), int(match.group("c"))]
    total = int(match.group("sum")) if match.group("sum") is not None else sum(numbers)
    return numbers, total


def _normalize_site(site: str) -> str:
    normalized = str(site or "").strip().lower()
    aliases = {"macau": "macao", "aust": "australia", "au": "australia", "pc": "pc28"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in _SITES:
        raise ValueError(f"unsupported site: {site}")
    return normalized


def _get_json(url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    text = _get_text(url, params=params, headers=headers)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected non-object JSON from {url}")
    return payload


def _get_text(url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> str:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request_headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=12) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


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


def _parse_unix_ts(value: object) -> datetime | None:
    try:
        ts = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    if ts > 100_000_000_000_000:
        ts //= 1_000_000
    elif ts > 10_000_000_000:
        ts //= 1000
    return datetime.fromtimestamp(ts)


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


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_number_list(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    try:
        [int(item) for item in value]
    except (TypeError, ValueError):
        return False
    return True


class _TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            self._current_row.append(" ".join("".join(self._current_cell).split()))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
            self._current_cell = None


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch normalized lottery history records.")
    parser.add_argument("site", choices=[*_SITES, "all"], help="site to fetch")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=20)
    args = parser.parse_args(argv)
    apply_saved_proxy_settings()

    payload: object
    if args.site == "all":
        payload = fetch_all_history_records(page=args.page, page_size=args.page_size)
    else:
        payload = fetch_history_records(args.site, page=args.page, page_size=args.page_size)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
