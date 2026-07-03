# DrawResultProvider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement DrawResultProvider with SQLite persistence and 4-site API history fetching, enabling the AutoBetService trend-following strategy to make real betting decisions.

**Architecture:** `HistoryFetcher` fetches raw JSON from 4 site APIs and parses into `DrawResult` objects. `DrawResultStore` persists them to SQLite (`draw_results.db`), handles result normalization (number → 大/小/单/双), and implements the `DrawResultProvider` protocol. Integrated into `_on_auto_bet_start` to feed `AutoBetService`.

**Tech Stack:** Python 3.x, SQLite3, urllib.request, requests (for API calls), existing StarTrace infrastructure

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/services/history_fetchers.py` | API fetching + response parsing per site |
| Create | `app/services/draw_result_store.py` | SQLite CRUD + normalization + DrawResultProvider impl |
| Modify | `app/ui/main_window_data.py:772-793` | Inject DrawResultStore into AutoBetService |

---

### Task 1: HistoryFetcher — 4-Site API Fetcher

**Files:**
- Create: `app/services/history_fetchers.py`

- [ ] **Step 1: Write the fetcher module**

```python
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any

from app.models.auto_bet import DrawResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize_result(site: str, raw_result: str) -> str:
    """Convert a raw numeric result to 大/小 + 单/双 label.

    Returns labels like '大双', '小单', etc.
    """
    try:
        num = int(raw_result)
    except (ValueError, TypeError):
        return raw_result  # already a label

    # Determine 大/小 based on site thresholds
    thresholds = {
        "pc28": (13,),      # 0-13=小, 14-27=大
        "macao": (24,),     # 1-24=小, 25-49=大
        "australia": (18,), # 1-18=小, 19-36=大
        "norway": (13,),    # 0-13=小, 14-27=大
    }
    thresh = thresholds.get(site, (13,))
    big_small = "大" if num > thresh[0] else "小"
    odd_even = "双" if num % 2 == 0 else "单"

    return f"{big_small}{odd_even}"


# ---------------------------------------------------------------------------
# HistoryFetcher
# ---------------------------------------------------------------------------

class HistoryFetcher:
    """Fetches historical draw results from 4 lottery sites.

    Usage:
        fetcher = HistoryFetcher()
        results = fetcher.fetch("pc28", count=20)
    """

    _TIMEOUT = 10

    def __init__(self) -> None:
        self._session: dict[str, str] = {}  # reserved for cookies if needed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, site: str, count: int = 20) -> list[DrawResult]:
        """Fetch the most recent `count` results for `site`."""
        method = getattr(self, f"_fetch_{site}", None)
        if method is None:
            logger.warning("Unknown site: %s", site)
            return []
        try:
            raw_list = method(count)
            return self._parse_results(site, raw_list)[:count]
        except Exception as exc:
            logger.warning("Failed to fetch history for %s: %s", site, exc)
            return []

    # ------------------------------------------------------------------
    # Per-site fetchers — return raw API response data
    # ------------------------------------------------------------------

    def _fetch_pc28(self, count: int) -> list[dict[str, Any]]:
        """PC28 history from 1pc.cc checkData API (returns recent issue list)."""
        url = "https://1pc.cc/data/get/checkData"
        params = {"type": "jnd28", "sf": "1", "ms": "zh"}
        data = self._get_json(url, params=params, headers={
            "referer": "https://1pc.cc/",
            "x-requested-with": "XMLHttpRequest",
        })
        # Response: {"issue": [{"qishu": "20260704001", "time": "...",
        #                       "next": 1234567890, "kaijiang": "??"}]}
        issue_list = data.get("issue", [])
        if not isinstance(issue_list, list):
            return []
        return issue_list

    def _fetch_macao(self, count: int) -> list[dict[str, Any]]:
        """Macao history from zhifu.qpon API (paginated)."""
        url = "https://macao.zhifu.qpon/api/openApi/lottery/draw"
        pages = max(1, (count + 19) // 20)  # 20 per page
        all_items: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            data = self._get_json(url, params={
                "pageNum": str(page),
                "pageSize": "20",
            }, headers={
                "origin": "https://288.pet",
                "referer": "https://288.pet/",
            })
            draw_list = self._deep_get(data, "data.drawList")
            if isinstance(draw_list, list):
                all_items.extend(draw_list)
            if len(all_items) >= count:
                break
        return all_items

    def _fetch_australia(self, count: int) -> list[dict[str, Any]]:
        """Australia history from gaga28.com AJAX API."""
        url = "https://gaga28.com/api/ajax2.php"
        data = self._post_form(url, data={"action": "beijing28"}, headers={
            "origin": "https://gaga28.com",
            "referer": "https://gaga28.com/az28.php",
            "x-requested-with": "XMLHttpRequest",
        })
        # Response: {"kaijiang": {"kaijianghao": [{"qishu": "...", "haoma": "??", ...}]}}
        kj = self._deep_get(data, "kaijiang.kaijianghao")
        if isinstance(kj, list):
            return kj
        return []

    def _fetch_norway(self, count: int) -> list[dict[str, Any]]:
        """Norway history from vqimpic.cc API (paginated)."""
        url = "https://p17-qq-server.vqimpic.cc/v1/selfapi/history"
        pages = max(1, (count + 19) // 20)
        all_items: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            data = self._get_json(url, params={
                "code": "nw28",
                "page": str(page),
                "page_size": "20",
            }, headers={
                "origin": "https://norzx.com",
                "referer": "https://norzx.com/",
            })
            items = data.get("data", [])
            if isinstance(items, list):
                all_items.extend(items)
            if len(all_items) >= count:
                break
        return all_items

    # ------------------------------------------------------------------
    # Response parsing → list[DrawResult]
    # ------------------------------------------------------------------

    def _parse_results(
        self, site: str, raw_list: list[dict[str, Any]],
    ) -> list[DrawResult]:
        """Convert raw API dicts to DrawResult objects."""
        parsed: list[DrawResult] = []
        for item in raw_list:
            try:
                period, result_raw = self._extract_period_result(site, item)
                if not period or result_raw is None:
                    continue
                label = _normalize_result(site, str(result_raw))
                open_time = self._extract_time(site, item)
                parsed.append(DrawResult(
                    site=site,
                    period=period,
                    result=label,  # normalized label for strategy
                    open_time=open_time,
                ))
            except Exception:
                logger.debug("Failed to parse item: %s", item, exc_info=True)
        return parsed

    def _extract_period_result(
        self, site: str, item: dict[str, Any],
    ) -> tuple[str, object]:
        """Extract (period, result) from a raw item."""
        if site == "pc28":
            return str(item.get("qishu", "")), item.get("kaijiang")
        elif site == "macao":
            return str(item.get("qihao", "")), item.get("openCode")
        elif site == "australia":
            return str(item.get("qishu", "")), item.get("haoma")
        elif site == "norway":
            return str(item.get("expect", "")), item.get("opencode")
        return "", None

    def _extract_time(
        self, site: str, item: dict[str, Any],
    ) -> datetime | None:
        """Extract open_time from a raw item."""
        ts_str = None
        if site == "pc28":
            ts_str = item.get("time")
        elif site == "macao":
            ts_str = item.get("opentime")
        elif site == "australia":
            ts_str = item.get("kaijiang_date") or item.get("time")
        elif site == "norway":
            ts_str = item.get("opentime")

        if ts_str is None:
            return None

        if isinstance(ts_str, (int, float)):
            return self._parse_ts(ts_str)

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return datetime.strptime(str(ts_str), fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_ts(value: object) -> datetime | None:
        ts = int(float(str(value)))
        if ts <= 0:
            return None
        if ts > 100_000_000_000_000:
            ts //= 1_000_000
        elif ts > 10_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get_json(
        self, url: str, *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self._request_json(url, data=None, headers=headers)

    def _post_form(
        self, url: str, *,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req_headers = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if headers:
            req_headers.update(headers)
        return self._request_json(url, data=encoded, headers=req_headers)

    @staticmethod
    def _request_json(
        url: str,
        data: bytes | None,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        request_headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "cache-control": "no-cache",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if headers:
            request_headers.update(headers)

        req = urllib.request.Request(
            url, data=data, headers=request_headers,
            method="POST" if data else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=HistoryFetcher._TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"HTTP error for {url}: {exc}") from exc

        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected payload from {url}")
        return payload

    @staticmethod
    def _deep_get(obj: Any, path: str) -> Any:
        for key in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key)
            elif isinstance(obj, list) and key.isdigit():
                obj = obj[int(key)]
            else:
                return None
        return obj
```

- [ ] **Step 2: Run import and normalization tests**

```bash
.\.venv\Scripts\python.exe -c "
from app.services.history_fetchers import _normalize_result, HistoryFetcher

# Test normalization
assert _normalize_result('pc28', '0') == '小双'
assert _normalize_result('pc28', '13') == '小单'
assert _normalize_result('pc28', '14') == '大双'
assert _normalize_result('pc28', '27') == '大单'
assert _normalize_result('macao', '1') == '小单'
assert _normalize_result('macao', '24') == '小双'
assert _normalize_result('macao', '25') == '大单'
assert _normalize_result('macao', '49') == '大单'
assert _normalize_result('australia', '18') == '小双'
assert _normalize_result('australia', '19') == '大单'
assert _normalize_result('australia', '36') == '大双'
assert _normalize_result('norway', '0') == '小双'
assert _normalize_result('norway', '13') == '小单'
assert _normalize_result('norway', '14') == '大双'
assert _normalize_result('norway', '27') == '大单'
# Already a label
assert _normalize_result('pc28', '大') == '大'
print('All normalization tests passed!')
print('HistoryFetcher import OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/services/history_fetchers.py
git commit -m "feat: add HistoryFetcher with 4-site API support and result normalization"
```

---

### Task 2: DrawResultStore — SQLite Persistence + DrawResultProvider

**Files:**
- Create: `app/services/draw_result_store.py`

- [ ] **Step 1: Write the store module**

```python
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from app.models.auto_bet import DrawResult, DrawResultProvider
from app.services.history_fetchers import HistoryFetcher

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS draw_results (
    site         TEXT NOT NULL,
    period       TEXT NOT NULL,
    result       TEXT NOT NULL,
    result_label TEXT,
    open_time    TEXT,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (site, period)
);
CREATE INDEX IF NOT EXISTS idx_draw_results_site_period
    ON draw_results(site, period DESC);
"""


class DrawResultStore(DrawResultProvider):
    """SQLite-backed historical draw result store.

    Implements the DrawResultProvider protocol.  On first access for a
    site, it checks whether the cache has enough data; if not, it
    fetches from the HistoryFetcher and persists the results.
    """

    _MIN_CACHE = 20  # minimum records before fetching

    def __init__(
        self,
        db_path: str | Path,
        fetcher: HistoryFetcher | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._fetcher = fetcher or HistoryFetcher()
        self._lock = threading.Lock()
        self._ensured: set[str] = set()
        self._init_db()

    # ------------------------------------------------------------------
    # DrawResultProvider protocol
    # ------------------------------------------------------------------

    def get_recent_results(self, site: str, count: int) -> list[DrawResult]:
        """Return the most recent `count` results for `site`."""
        self._ensure_site(site, count * 2)
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT site, period, result, result_label, open_time "
                    "FROM draw_results WHERE site = ? "
                    "ORDER BY period DESC LIMIT ?",
                    (site, count),
                ).fetchall()
            finally:
                con.close()

        results = []
        for row in rows:
            open_time = None
            if row["open_time"]:
                try:
                    open_time = datetime.fromisoformat(row["open_time"])
                except (ValueError, TypeError):
                    pass
            results.append(DrawResult(
                site=row["site"],
                period=row["period"],
                result=row["result_label"] or row["result"],
                open_time=open_time,
            ))
        # Return oldest-first for the strategy engine
        results.reverse()
        return results

    def get_result(self, site: str, period: str) -> DrawResult | None:
        """Return a single result by site + period, or None."""
        self._ensure_site(site, 0)
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            con.row_factory = sqlite3.Row
            try:
                row = con.execute(
                    "SELECT site, period, result, result_label, open_time "
                    "FROM draw_results WHERE site = ? AND period = ?",
                    (site, period),
                ).fetchone()
            finally:
                con.close()

        if row is None:
            return None
        open_time = None
        if row["open_time"]:
            try:
                open_time = datetime.fromisoformat(row["open_time"])
            except (ValueError, TypeError):
                pass
        return DrawResult(
            site=row["site"],
            period=row["period"],
            result=row["result_label"] or row["result"],
            open_time=open_time,
        )

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _ensure_site(self, site: str, min_count: int) -> None:
        """Ensure we have at least `min_count` results cached for `site`."""
        if site in self._ensured:
            return

        current_count = self._count(site)
        need = max(min_count, self._MIN_CACHE)
        if current_count >= need:
            self._ensured.add(site)
            return

        logger.info(
            "Cache miss for %s: have %d, need %d — fetching from API",
            site, current_count, need,
        )
        results = self._fetcher.fetch(site, count=need)
        if results:
            self.insert_results(site, results)
            logger.info("Fetched %d results for %s", len(results), site)

        self._ensured.add(site)

    def _count(self, site: str) -> int:
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                row = con.execute(
                    "SELECT COUNT(*) FROM draw_results WHERE site = ?", (site,),
                ).fetchone()
                return int(row[0] if row else 0)
            finally:
                con.close()

    def insert_results(self, site: str, results: list[DrawResult]) -> int:
        """Insert or replace draw results. Returns count inserted."""
        now = datetime.now().isoformat()
        inserted = 0
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                for r in results:
                    con.execute(
                        "INSERT OR REPLACE INTO draw_results "
                        "(site, period, result, result_label, open_time, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            site,
                            r.period,
                            r.result,
                            r.result,  # already normalized by fetcher
                            r.open_time.isoformat() if r.open_time else None,
                            now,
                        ),
                    )
                    inserted += 1
                con.commit()
            finally:
                con.close()
        return inserted

    def clear_site(self, site: str) -> None:
        """Remove all cached results for a site."""
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                con.execute("DELETE FROM draw_results WHERE site = ?", (site,))
                con.commit()
            finally:
                con.close()
        self._ensured.discard(site)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._db_path))
        try:
            con.executescript(_DDL)
            con.commit()
        finally:
            con.close()
```

- [ ] **Step 2: Run store tests**

```bash
.\.venv\Scripts\python.exe -c "
import tempfile, os
from pathlib import Path
from datetime import datetime
from app.services.draw_result_store import DrawResultStore
from app.models.auto_bet import DrawResult

# Test with temp DB
tmp = Path(tempfile.mkdtemp()) / 'test_draw_results.db'
store = DrawResultStore(db_path=tmp, fetcher=None)

# Test insert + get
store.insert_results('pc28', [
    DrawResult(site='pc28', period='2026001', result='大单', open_time=datetime.now()),
    DrawResult(site='pc28', period='2026002', result='小双', open_time=datetime.now()),
    DrawResult(site='pc28', period='2026003', result='大双', open_time=datetime.now()),
])

# Test get_recent_results
results = store.get_recent_results('pc28', 2)
assert len(results) == 2
assert results[0].period == '2026002'  # last 2, oldest first
assert results[1].period == '2026003'

# Test get_result
r = store.get_result('pc28', '2026001')
assert r is not None
assert r.result == '大单'

# Test missing
assert store.get_result('pc28', '9999999') is None

# Cleanup
store.clear_site('pc28')
assert len(store.get_recent_results('pc28', 10)) == 0
os.unlink(tmp)

print('All DrawResultStore tests passed!')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/services/draw_result_store.py
git commit -m "feat: add DrawResultStore with SQLite persistence and DrawResultProvider impl"
```

---

### Task 2.5: Fix _opposite_play for Composite Labels

**Files:**
- Modify: `app/services/auto_bet_service.py:207-217`

- [ ] **Step 1: Update _opposite_play to handle composite labels**

The normalization returns labels like "大双", "小单".  The current
`_opposite_play` only handles individual labels ("大"↔"小", "单"↔"双").
We need to extend it for composites.

Read `app/services/auto_bet_service.py`.  Replace the `_opposite_play` method:

```python
    @staticmethod
    def _opposite_play(result: str, play_types: list[str]) -> str | None:
        """Given a result like '大双', return the opposite play.

        Handles both individual ('大'→'小') and composite ('大双'→'小单')
        labels by inverting both 大/小 and 单/双 components.
        """
        # Composite-label opposites
        composites = {
            "大双": "小单", "小单": "大双",
            "大单": "小双", "小双": "大单",
        }
        composite_opposite = composites.get(result)
        if composite_opposite and composite_opposite in play_types:
            return composite_opposite

        # Individual-label opposites
        singles = {"大": "小", "小": "大", "单": "双", "双": "单"}
        single_opposite = singles.get(result)
        if single_opposite and single_opposite in play_types:
            return single_opposite

        # Fallback: any other play type
        for pt in play_types:
            if pt != result:
                return pt
        return None
```

- [ ] **Step 2: Test**

```bash
.\.venv\Scripts\python.exe -c "
from app.services.auto_bet_service import AutoBetService
# Composite labels
assert AutoBetService._opposite_play('大双', ['大双','小单','大单','小双']) == '小单'
assert AutoBetService._opposite_play('小单', ['大双','小单']) == '大双'
assert AutoBetService._opposite_play('大单', ['大双','小双','大单']) == '小双'
# Individual labels still work
assert AutoBetService._opposite_play('大', ['大','小']) == '小'
assert AutoBetService._opposite_play('小', ['大','小']) == '大'
# Fallback
assert AutoBetService._opposite_play('大双', ['大','小']) == '大'
print('_opposite_play composite tests passed!')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/services/auto_bet_service.py
git commit -m "fix: extend _opposite_play to handle composite result labels"
```

---

### Task 3: Integration — Wire into Main Window

**Files:**
- Modify: `app/ui/main_window_data.py:772-793`

- [ ] **Step 1: Update _on_auto_bet_start to create and inject DrawResultStore**

In `app/ui/main_window_data.py`, find `_on_auto_bet_start`. After the
`injector.startup()` call succeeds and the `service.set_injector(injector)`
line, insert the following block before `service.start()`:

```python
        # --- Create historical data provider ---
        from app.services.draw_result_store import DrawResultStore
        from app.services.history_fetchers import HistoryFetcher
        from app.utils.pathing import user_data_dir

        store = DrawResultStore(
            db_path=Path(user_data_dir()) / "draw_results.db",
            fetcher=HistoryFetcher(),
        )
        # Pre-fetch data for the configured site using the service's
        # current config (already applied by _on_auto_bet_config_changed).
        svc_cfg = service.config
        store._ensure_site(svc_cfg.site, svc_cfg.observation_window * 2)
        service.set_result_provider(store)
```

The complete updated `_on_auto_bet_start` should now look like (after the
`MessageInjector` creation and startup):

```python
        injector = MessageInjector(...)
        if not injector.startup():
            ...

        service.set_injector(injector)

        # --- Create historical data provider ---
        from app.services.draw_result_store import DrawResultStore
        from app.services.history_fetchers import HistoryFetcher
        from app.utils.pathing import user_data_dir

        store = DrawResultStore(
            db_path=Path(user_data_dir()) / "draw_results.db",
            fetcher=HistoryFetcher(),
        )
        svc_cfg = service.config
        store._ensure_site(svc_cfg.site, svc_cfg.observation_window * 2)
        service.set_result_provider(store)

        service.start()
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.start()
```

- [ ] **Step 2: Verify imports**

```bash
.\.venv\Scripts\python.exe -c "
from app.services.draw_result_store import DrawResultStore
from app.services.history_fetchers import HistoryFetcher
from app.models.auto_bet import StrategyConfig, DrawResult
from app.utils.pathing import user_data_dir
from pathlib import Path
print('All imports OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/ui/main_window_data.py
git commit -m "feat: inject DrawResultStore into AutoBetService on start"
```

---

### Task 4: End-to-End Verification

**Files:**
- Manual verification (no new files)

- [ ] **Step 1: Test the full pipeline**

```bash
.\.venv\Scripts\python.exe -c "
import json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from app.services.history_fetchers import HistoryFetcher
from app.services.draw_result_store import DrawResultStore
from app.services.auto_bet_service import AutoBetService
from app.services.message_injector import MessageInjector
from app.models.auto_bet import StrategyConfig
from pathlib import Path
from app.utils.pathing import user_data_dir

# 1. Fetch real history data
fetcher = HistoryFetcher()
results = fetcher.fetch('pc28', count=20)
print(f'Fetched {len(results)} results for pc28')
if results:
    print(f'  First: period={results[0].period} result={results[0].result}')
    print(f'  Last:  period={results[-1].period} result={results[-1].result}')

# 2. Store and retrieve
store = DrawResultStore(
    db_path=Path(user_data_dir()) / 'draw_results.db',
    fetcher=fetcher,
)
store.insert_results('pc28', results)
cached = store.get_recent_results('pc28', 10)
print(f'Cached: {len(cached)} results')

# 3. Wire into strategy engine
svc = AutoBetService()
svc.set_result_provider(store)
cfg = StrategyConfig(site='pc28', observation_window=10, trigger_threshold=3)
svc.apply_config(cfg)
svc.start()

# 4. Test tick (without real injector — should log decision reason)
svc.tick('pc28', 60, 'dummy_period')
logs = svc.get_logs()
print(f'Strategy logs: {len(logs)}')
for log in logs[-5:]:
    print(f'  [{log.ts}] {log.content}')

svc.stop()
print('E2E verification completed!')
"
```

- [ ] **Step 2: Commit final fixes if any**

```bash
git add -A
git commit -m "chore: final integration fixes for draw result provider"
```
