# DrawResultProvider — 历史开奖数据源设计

## 目标

实现 `DrawResultProvider` 协议，将 4 个站点的历史开奖数据抓取、解析、归一化并持久化到本地 SQLite，使 `AutoBetService` 的趋势跟踪策略能够查询历史数据并做出下注决策。

## 需求

### 功能需求

1. **数据抓取** — 支持 pc28 / macao / australia / norway 4 个站点，按站点类型调用对应的历史数据 API
2. **数据解析** — 从各站点 API 响应中提取期号、开奖结果、开奖时间
3. **结果归一化** — 将数值型结果转换为 大/小/单/双 标签，供策略引擎消费
4. **本地持久化** — SQLite 存储，`(site, period)` 联合主键，支持增量更新
5. **增量更新** — 启动时检查缓存；数据不足时（少于 `observation_window * 2` 期）从 API 补齐
6. **实现 DrawResultProvider 协议** — `get_recent_results(site, count)` 和 `get_result(site, period)`
7. **线程安全** — 读写操作线程安全，支持 GUI 线程和定时器线程并发访问

### 非功能需求

1. API 请求失败时返回已有缓存数据，不中断策略引擎
2. 数据库文件放在 StarTrace 用户数据目录（与 `settings.json` 同级）
3. 单次启动后最多只做一次全量 API 补齐

## 设计

### 文件

| 文件 | 职责 |
|------|------|
| `app/services/draw_result_store.py` | SQLite 存储、缓存管理、`DrawResultProvider` 实现 |
| `app/services/history_fetchers.py` | 4 站点 API 抓取器，返回原始 JSON |

### 修改文件

| 文件 | 变更 |
|------|------|
| `app/ui/main_window_data.py` | `_on_auto_bet_start` 中创建 `DrawResultStore`，注入 `service.set_result_provider()` |

### SQLite 表

```sql
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
```

### DrawResultStore 类

```python
class DrawResultStore(DrawResultProvider):
    """SQLite-backed historical draw result provider.

    实现 DrawResultProvider 协议。启动时自动检测缓存状态，
    必要时调用外部抓取器补齐数据。

    Usage:
        store = DrawResultStore(db_path, fetcher)
        store.ensure_data("pc28", min_count=20)
        results = store.get_recent_results("pc28", 10)
    """

    def __init__(self, db_path: str | Path, fetcher: "HistoryFetcher | None" = None)
    def ensure_data(self, site: str, min_count: int = 20) -> None
    def get_recent_results(self, site: str, count: int) -> list[DrawResult]    # Protocol
    def get_result(self, site: str, period: str) -> DrawResult | None           # Protocol
    def insert_results(self, site: str, results: list[DrawResult]) -> int       # returns count
```

### HistoryFetcher 类

```python
class HistoryFetcher:
    """Unified fetcher that dispatches to per-site parsers.

    Supports pc28, macao, australia, norway.
    """

    def __init__(self)
    def fetch(self, site: str, count: int) -> list[DrawResult]
    # Internal per-site methods:
    def _fetch_pc28(self, count: int) -> list[DrawResult]
    def _fetch_macao(self, count: int) -> list[DrawResult]
    def _fetch_australia(self, count: int) -> list[DrawResult]
    def _fetch_norway(self, count: int) -> list[DrawResult]
```

### 结果归一化

| 站点 | 数值范围 | 大/小 分界 | 单/双 规则 |
|------|----------|-----------|-----------|
| PC28 | 0–27 | ≤13=小, ≥14=大 | 偶数=双, 奇数=单 |
| 澳门 | 1–49 | ≤24=小, ≥25=大 | 偶数=双, 奇数=单 |
| 澳洲 | 1–36 | ≤18=小, ≥19=大 | 偶数=双, 奇数=单 |
| 挪威 | 0–27 | ≤13=小, ≥14=大 | 偶数=双, 奇数=单 |

归一化输出标签为组合形式：`大双`, `大单`, `小双`, `小单`。

### 数据流

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│ HistoryFetch │────▶│ DrawResultStore  │────▶│ AutoBet     │
│ er.fetch()   │     │ ensure_data()    │     │ Service     │
│              │     │ insert_results() │     │ _analyze()  │
│ API → list   │     │ SQLite ↔ DrawRes │     │ 趋势跟踪    │
│ [DrawResult] │     │ get_recent()     │     │             │
└──────────────┘     └──────────────────┘     └─────────────┘
```

### 集成点

在 `_on_auto_bet_start` 中：

```python
from app.services.draw_result_store import DrawResultStore
from app.services.history_fetchers import HistoryFetcher

store = DrawResultStore(
    db_path=user_data_dir() / "draw_results.db",
    fetcher=HistoryFetcher(),
)
store.ensure_data(config.site, min_count=config.observation_window * 2)
service.set_result_provider(store)
```

### 错误处理

- API 请求超时（8s）→ 返回已有缓存，不影响策略引擎运行
- API 返回格式异常 → log warning，返回空列表
- SQLite 写入失败 → log error，返回已有缓存
- 缓存数据不足 → 策略引擎 `_analyze` 返回 "历史数据不足"，不下注

### 站点 API 端点

| 站点 | 历史数据 API | 页码参数 |
|------|-------------|---------|
| PC28 | `https://1pc.cc/data/get/checkData?type=jnd28&sf=1&ms=zh` | 单次返回近期列表 |
| 澳门 | `https://macao.zhifu.qpon/api/openApi/lottery/draw?pageNum=1&pageSize=N` | pageNum/pageSize |
| 澳洲 | `https://gaga28.com/api/ajax2.php` (POST: action=beijing28) | 单次返回近期列表 |
| 挪威 | `https://p17-qq-server.vqimpic.cc/v1/selfapi/history?code=nw28&page=1&page_size=N` | page/page_size |
