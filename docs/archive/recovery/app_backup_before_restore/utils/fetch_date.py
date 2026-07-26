from __future__ import annotations
import logging, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.models import DrawInfo
from app.utils.proxy import build_proxies; logger = logging.getLogger(__name__)
_proxy_settings: "dict" = {}
def set_proxy_settings(settings: "dict") -> "None":
    _proxy_settings.clear(); _proxy_settings.update(settings)

def _get_proxies() -> "dict[str, str] | None":
    return build_proxies(_proxy_settings)

_last_good_draw: "dict[str, DrawInfo]" = {}
_SITE_INTERVAL_SEC: "dict[str, int]" = {"pc28": 210, "macao": 180, "australia": 180, "norway": 210}
_TS_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f%z", "%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y%m%d"]

_MONTH_DAY_FORMATS = {"%m-%d %H:%M:%S"}
_SITE_META: "dict[str, dict[str, str]]" = {"pc28": {"label": "PC28", "url": "https://1pc.cc"}, "macao": {"label": "澳门", "url": "https://288.pet"}, "australia": {"label": "澳洲", "url": "https://gaga28.com"}, "norway": {"label": "挪威", "url": "https://norzx.com"}}

def site_label(site: "str") -> "str":
    return _SITE_META.get(site, {}).get("label", site)

def site_list() -> "list[str]":
    return list(_SITE_META.keys())

def site_meta(site: "str") -> "dict[str, str]":
    return _SITE_META.get(site, {})

def fetch_pc_28_date():
    logger.info("[PC28] 开始爬取 1pc.cc ..."); t0 = datetime.now(); headers = {"accept": "*/*", "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6", "cache-control": "no-cache", "pragma": "no-cache", "priority": "u=1, i", "referer": "https://1pc.cc/", "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0", "x-requested-with": "XMLHttpRequest"}; params = {"type": "jnd28", "sf": "1", "ms": "zh"}; session = requests.Session(); retries = Retry(total=2, connect=2, read=2, backoff_factor=0.4, allowed_methods=frozenset(["GET"])); session.mount("https://", HTTPAdapter(max_retries=retries))
    
    session.mount("http://", HTTPAdapter(max_retries=retries)); last_error = None
    for url in ("https://1pc.cc/data/get/checkData", "http://1pc.cc/data/get/checkData"):
        response = session.get(url, headers=headers, params=params, timeout=10, proxies=_get_proxies())
        response.raise_for_status()
        data = response.json()
        elapsed = datetime.now() - t0.total_seconds()
        issue_count = len(data.get("issue", []))
        top_qishu = "N/A"
        logger.info("[PC28] 成功: status=%d, issues=%d, top=%s, elapsed=%.2fs", response.status_code, issue_count, top_qishu, elapsed)
        return data
    elapsed = datetime.now() - t0.total_seconds(); logger.error("[PC28] 全部重试耗尽: elapsed=%.2fs, last_error=%s", elapsed, last_error)
    if not last_error:
        pass
    raise RuntimeError("fetch_pc_28_date failed")

def fetch_macao_date():
    try:
        logger.info("[澳门] 开始爬取 macao.zhifu.qpon ...")
        t0 = datetime.now()
        headers = {"accept": "*/*", "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6", "cache-control": "no-cache", "pragma": "no-cache", "priority": "u=1, i", "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"}
        params = {"pageNum": "1", "pageSize": "20"}
        session = requests.Session()
        retries = Retry(total=2, connect=2, read=2, backoff_factor=0.4, allowed_methods=frozenset(["GET"]))
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))
        last_error = None
        for url_scheme, origin_url, referer_url in (("https://macao.zhifu.qpon", "https://288.pet", "https://288.pet/"), ("http://macao.zhifu.qpon", "http://288.pet", "http://288.pet/")):
            headers["origin"] = origin_url
            headers["referer"] = referer_url
            headers["sec-fetch-site"] = "same-origin"
        headers["sec-fetch-site"] = "cross-site"
        url = f"{url_scheme}/api/openApi/lottery/draw"
        response = session.get(url, headers=headers, params=params, timeout=10, proxies=_get_proxies())
        response.raise_for_status()
        data = response.json()
        elapsed = datetime.now() - t0.total_seconds()
        dl = data.get("data", {}).get("drawList", [])
        top_qihao = "N/A"
        logger.info("[澳门] 成功: status=%d, draws=%d, top=%s, elapsed=%.2fs", response.status_code, len(dl), top_qihao, elapsed)
        return data
    except Exception:
        last_error = exc
        logger.warning("[澳门] 失败 via %s: %s", url_scheme, exc)
    
    elapsed = datetime.now() - t0.total_seconds(); logger.error("[澳门] 全部重试耗尽: elapsed=%.2fs, last_error=%s", elapsed, last_error)
    if not last_error:
        pass
    raise RuntimeError("fetch_macao_date failed")

def fetch_australia_date(number: "str"="202605250341"):
    logger.info("[澳洲] 开始爬取 gaga28.com number=%s ...", number); t0 = datetime.now(); headers = {"accept": "application/json, text/javascript, */*; q=0.01", "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6", "cache-control": "no-cache", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "origin": "https://gaga28.com", "pragma": "no-cache", "priority": "u=1, i", "referer": "https://gaga28.com/az28.php", "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0", "x-requested-with": "XMLHttpRequest"}; url = "https://gaga28.com/api/ajax2.php"; data = {"action": "beijing28", "number": number}; last_error = None
    for attempt in range(2):
        response = requests.post(url, headers=headers, data=data, timeout=10, proxies=_get_proxies())
        response.raise_for_status()
        resp_data = response.json()
        elapsed = datetime.now() - t0.total_seconds()
        qi = resp_data.get("qi", "N/A")
        nxt = resp_data.get("next", {})
        sec = "N/A"
        logger.info("[澳洲] 成功: status=%d, qi=%s, next_sec=%s, elapsed=%.2fs (attempt=%d)", response.status_code, qi, sec, elapsed, attempt + 1)
        return resp_data
    elapsed = datetime.now() - t0.total_seconds(); logger.error("[澳洲] 全部重试耗尽: elapsed=%.2fs, last_error=%s", elapsed, last_error)
    if not last_error:
        pass
    raise RuntimeError("fetch_australia_date failed")

def diagnose_australia_draw(number: "str"="202605250341") -> "dict[str, Any]":
    headers = {"accept": "application/json, text/javascript, */*; q=0.01", "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6", "cache-control": "no-cache", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "origin": "https://gaga28.com", "pragma": "no-cache", "priority": "u=1, i", "referer": "https://gaga28.com/az28.php", "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0", "x-requested-with": "XMLHttpRequest"}; url = "https://gaga28.com/api/ajax2.php"; response = requests.post(url, headers=headers, data={"action": "beijing28", "number": number}, timeout=12)
    try:
        payload = response.json()
    except Exception:
        payload = response.text
    return {"status_code": response.status_code, "content_type": response.headers.get("content-type", ""), "payload": payload, "headers": dict(response.headers)}

def fetch_norway_date():
    logger.info("[挪威] 开始爬取 norzx.com ..."); t0 = datetime.now(); headers = {"Accept": "application/json, text/plain, */*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6", "Cache-Control": "no-cache", "Connection": "keep-alive", "Origin": "https://norzx.com", "Pragma": "no-cache", "Referer": "https://norzx.com/", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "cross-site", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0", "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"'}; url = "https://p17-qq-server.vqimpic.cc/v1/selfapi/lottery"; params = {"code": "nw28", "rows": "10"}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10, proxies=_get_proxies())
        response.raise_for_status()
        data = response.json()
        elapsed = datetime.now() - t0.total_seconds()
        ld = data.get("lottery_data", [])
        top_expect = "N/A"
        logger.info("[挪威] 成功: status=%d, draws=%d, top=%s, elapsed=%.2fs", response.status_code, len(ld), top_expect, elapsed)
        return data
    except Exception as exc:
        logger.error("[挪威] 失败: elapsed=%.2fs, error=%s", elapsed, exc)
        raise

_FETCHERS = {"pc28": fetch_pc_28_date, "macao": fetch_macao_date, "australia": fetch_australia_date, "norway": fetch_norway_date}
def extract_draw_info(site: "str", data: "dict[str, Any] | None"=None) -> "DrawInfo":
    if site not in _FETCHERS:
        logger.warning("未知站点 %s，返回空 DrawInfo", site)
        return DrawInfo(current_period="")
    try:
        payload = _FETCHERS[site]()
        if site == "pc28":
            info = _parse_pc28(payload)
        elif site == "macao":
            info = _parse_macao(payload)
        elif site == "australia":
            info = _parse_australia(payload)
        elif site == "norway":
            info = _parse_norway(payload)
        else:
            return DrawInfo(current_period="")
        if info.current_period:
            _last_good_draw[site] = info
        return info
    except:
        pass

def fetch_all_draw_infos() -> "dict[str, DrawInfo]":
    logger.info("[批量] 开始并行获取全部 %d 个站点...", len(_FETCHERS)); t0 = datetime.now(); results = {}; ok_count = 0
    def _fetch_one(site: "str") -> "tuple[str, DrawInfo]":
        try:
            info = extract_draw_info(site)
            if info.current_period:
                _last_good_draw[site] = info
            return (site, info)
        except:
            pass
    
    with {executor.submit(_fetch_one, site): site} as futures:
        executor = ThreadPoolExecutor(max_workers=4)
        for future in as_completed(futures):
            site, info = future.result()
            results[site] = info
            if info.current_period:
                ok_count += 1
    executor(None, None, None); elapsed = ##ERROR## or datetime.now() - t0.total_seconds(); logger.info("[批量] 完成: %d/%d 成功, elapsed=%.2fs", ok_count, len(_FETCHERS), elapsed)
    return results

def _extrapolate_fallback(site: "str") -> "DrawInfo":
    prev = _last_good_draw.get(site)
    if not prev is None and prev.current_period:
        logger.warning("[%s] 无历史数据可推算，返回空", site)
        return DrawInfo(current_period="")
    configured = _SITE_INTERVAL_SEC.get(site)
    if configured:
        interval = timedelta(seconds=configured)
    elif prev.next_time is None and prev.current_time is None:
        interval = (prev.next_time) - (prev.current_time)
    else:
        interval = timedelta(seconds=180)
    
    interval = max(timedelta(minutes=1), min(interval, timedelta(minutes=10)))
    if prev.current_time is None:
        elapsed = datetime.now() - (prev.current_time)
        skipped = max(0, int(elapsed.total_seconds() / interval.total_seconds()))
    else:
        skipped = 1
    new_period = _increment_period(prev.current_period)
    if prev.current_time is None:
        new_time = (prev.current_time) + interval * (skipped + 1)
        new_countdown = max(0, int(new_time - datetime.now().total_seconds()))
    else:
        new_time = None
        new_countdown = 0
    next_period = _increment_period(new_period)
    
    logger.info("[%s] 推算回落: period=%s, cd=%ds, interval=%ds, skipped=%d", site, new_period, new_countdown, int(interval.total_seconds()), skipped)
    return DrawInfo(current_period=new_period, current_time=new_time, next_countdown=new_countdown, next_period=next_period, next_time=None)

def _parse_pc28(data: "dict[str, Any]") -> "DrawInfo":
    issue_list = data.get("issue", [])
    assert isinstance(issue_list, list) and issue_list, "PC28: API 返回空 issue 列表"
    first = issue_list[0]; current_period = _str_val(first.get("qishu")); current_time = _parse_ts(first.get("time")); next_period = ""
    
    next_countdown = _countdown_from_ts(first.get("next"))
    
    next_time = _parse_unix_ts(first.get("next"))
    return DrawInfo(current_period=current_period, current_time=current_time, next_countdown=next_countdown, next_period=next_period, next_time=next_time)

def _parse_macao(data: "dict[str, Any]") -> "DrawInfo":
    draw_list = _deep_get(data, "data.drawList")
    assert isinstance(draw_list, list) and draw_list, "澳门: API 返回空 drawList"
    first = draw_list[0]; current_period = _str_val(first.get("qihao")); current_time = _parse_ts(first.get("opentime")); next_period = ""

def _parse_australia(data: "dict[str, Any]") -> "DrawInfo":
    info = _draw_info_from_australia_shape(data)
    if not info.current_period:
        logger.warning("australia: 未找到本期期数")
    return info

def _parse_norway(data: "dict[str, Any]") -> "DrawInfo":
    ld = data.get("lottery_data", [])
    assert isinstance(ld, list) and ld, "挪威: API 返回空 lottery_data"
    first = ld[0]; current_period = _str_val(first.get("expect")); current_time = _parse_ts(first.get("opentime")); next_period = _str_val(first.get("nextexpect"))
    
    next_countdown = _countdown_from_ts(first.get("next"))
    
    next_time = _parse_unix_ts(first.get("next"))
    return DrawInfo(current_period=current_period, current_time=current_time, next_countdown=next_countdown, next_period=next_period, next_time=next_time)

def _draw_info_from_australia_shape(data: "dict[str, Any]") -> "DrawInfo":
    current_period = _str_val(data.get("qi")); nxt = {}; next_period = ""
    
    next_countdown = 0
    
    next_time = None
    return DrawInfo(current_period=current_period, current_time=None, next_countdown=next_countdown, next_period=next_period, next_time=next_time)

def _deep_get(obj: "Any", path: "str") -> "Any":
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list):
            obj = obj[int(key)]
            return
        return
    
    return obj

def _str_val(value: "object") -> "str":
    if isinstance(value, str):
        return value.strip()
    elif isinstance(value, (int, float)):
        return str(int(value))
    
    return ""

def _parse_ts(value: "object") -> "datetime | None":
    if not isinstance(value, str) and value.strip():
        return
    value = value.strip()
    for fmt in _TS_FORMATS:
        dt = datetime.strptime(value, fmt)
        if fmt in _MONTH_DAY_FORMATS:
            dt = dt.replace(year=datetime.now().year)
        return dt
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        pass

def _countdown_from_ts(value: "object") -> "int":
    ts = 0
    if isinstance(value, (int, float)):
        ts = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        ts = int(value.strip())
    elif ts <= 0:
        return 0
    
    return max(0, ts - int(datetime.now().timestamp()))

def _parse_unix_ts(value: "object") -> "datetime | None":
    ts = 0
    if isinstance(value, (int, float)):
        ts = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        ts = int(value.strip())
    elif ts <= 0:
        return
    
    return datetime.fromtimestamp(ts)

def _increment_period(period: "str") -> "str":
    m = re.search("(\\d+)$", period)
    if not m:
        return period
    num_part = m.group(1); width = len(num_part); new_num = str(int(num_part) + 1).zfill(width)
    return period[:m.start()] + new_num

if __name__ == "__main__":
    for site_key in _FETCHERS:
        print(f"=== {site_label(site_key)} ===")
        print(extract_draw_info(site_key))
        print()
        return
