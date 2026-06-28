# Auto Bet Bot Design

## Goal

Add an automated betting module to StarTrace that injects betting messages into the local Tencent Cloud IM SQLite database, allowing the WuQuan client to sync and send bets automatically. Use trend-following strategy based on historical lottery results.

## Scope

### In Scope

1. **Message injector** — construct and insert betting messages into `msg_0.db` (`message` table) with proper encryption (AES-ECB, key=`666888`)
2. **Strategy interface** — pluggable strategy API so multiple strategies can be implemented and swapped via config
3. **Trend-following strategy** — observe N recent draw results, trigger reverse bet when same result appears M consecutive times
4. **GUI panel** — new "自动下注" group box in the left sidebar with strategy config, start/stop, and run log
5. **Verification test** — a test script that validates DB injection actually triggers message sending through the WuQuan client
6. **Config persistence** — strategy parameters saved/loaded through existing `SettingsService`

### Out of Scope (deferred)

- Historical lottery result fetching and parsing (handled by a separate script; strategy receives data through a defined interface)
- Multiple simultaneous strategies running in parallel (single strategy per session)
- Automatic account switching
- Profit/loss tracking

## Requirements

### Functional

1. Message injector must construct messages matching the exact schema of the `message` table in Tencent Cloud IM's `msg_0.db`
2. Messages must be AES-ECB encrypted with key `666888` and Base64-encoded when stored (matching the encryption pattern observed in the existing codebase)
3. Injected messages must include correct `client_time` (milliseconds), `rand` (random ordering), `sid` (group/conversation ID), `sender` (user ID), and `element_descriptions` (JSON with message content)
4. Strategy engine receives draw results through a defined `DrawResultProvider` protocol interface — the actual historical data fetching is done by an external script
5. Trend-following strategy: configurable `observation_window` (number of recent draws to analyze), `trigger_threshold` (consecutive same-result count that triggers a reverse bet), `bet_amount`, and `play_type`
6. GUI panel must show: strategy selection dropdown, parameter inputs, start/stop toggle, and a scrolling run log
7. All strategy parameters must persist through `SettingsService`
8. The auto-bet panel must be hidden when no database is resolved (no active account)

### Non-Functional

1. DB injection must not corrupt the existing `msg_0.db` — use WAL-mode safe writes
2. Strategy engine must run on a background thread to avoid blocking the GUI
3. Run log must be capped to prevent memory issues (max ~500 lines)
4. Injection must respect the draw countdown: only place bets within the valid betting window (not after lock/cutoff)

## Design

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  app/models/auto_bet.py          — Data models               │
│  app/services/auto_bet_service.py — Strategy engine + sched  │
│  app/services/message_injector.py — DB message construction  │
│  app/ui/auto_bet_panel.py        — GUI panel                 │
│  tests/test_message_injector.py  — Injection verification    │
└──────────────────────────────────────────────────────────────┘
```

### Data Models (`app/models/auto_bet.py`)

```python
@dataclass
class DrawResult:
    """Single draw result from external script / API."""
    period: str           # e.g. "20250628001"
    site: str             # "pc28" | "macao" | "australia" | "norway"
    result: str           # "大" | "小" | "单" | "双" | numeric
    open_time: datetime

@dataclass
class BetDecision:
    """Output of strategy analysis."""
    should_bet: bool
    play_type: str        # "大" | "小" | "单" | "双" | ...
    amount: float
    group_id: str         # target group/conversation
    reason: str           # human-readable explanation

@dataclass
class StrategyConfig:
    """Strategy parameters, persisted via SettingsService."""
    strategy_type: str = "trend_following"
    enabled: bool = False
    observation_window: int = 10
    trigger_threshold: int = 3
    bet_amount: float = 10.0
    play_types: list[str] = field(default_factory=lambda: ["大", "小"])
    site: str = "pc28"
    target_groups: list[str] = field(default_factory=list)
    lock_threshold_sec: int = 15  # stop betting N seconds before draw

@dataclass
class InjectRecord:
    """Record of an injected message for the run log."""
    ts: datetime
    group_name: str
    play_type: str
    amount: float
    content: str
    success: bool
    error: str = ""
```

### Strategy Protocol (`app/services/auto_bet_service.py`)

```python
class DrawResultProvider(Protocol):
    """Protocol for providing historical draw results.
    External scripts implement this to feed data to the strategy engine."""
    def get_recent_results(self, site: str, count: int) -> list[DrawResult]: ...
    def get_result(self, site: str, period: str) -> DrawResult | None: ...
```

### Message Injector (`app/services/message_injector.py`)

Core class: `MessageInjector`

- `__init__(msg_db: Path, sender_id: str, sender_name: str)` — initialize with resolved DB path and user identity
- `inject_bet(group_id: str, content: str) -> bool` — construct and insert a betting message
- `_build_element_descriptions(content: str) -> str` — build JSON element with content field
- `_encrypt_content(plain: str) -> str` — AES-ECB encrypt + Base64 encode (optional, only if the group's messages are encrypted)
- `_next_rand() -> int` — generate ordering rand value

### Trend-Following Strategy

Logic:
1. Receive N most recent draw results from `DrawResultProvider`
2. Count consecutive occurrences of the same result (e.g., how many "大" in a row)
3. If consecutive count >= `trigger_threshold`, signal a reverse bet
4. Also check: are we still within the betting window? (countdown > `lock_threshold_sec`)

```
Example (observation_window=5, trigger_threshold=3, bet_amount=100):
  Last 5 draws: [大, 大, 大, 小, 大]
  Consecutive "大" at tail: 1 → no trigger
  Last 5 draws: [小, 大, 大, 大, 大]
  Consecutive "大" at tail: 4 >= 3 → trigger → bet "小 100"
```

### GUI Panel (`app/ui/auto_bet_panel.py`)

```ascii
┌─ 自动下注 ──────────────────────────┐
│ 策略: [趋势跟踪 ▼]                  │
│ 站点: [pc28 ▼]                      │
│ 目标群组: [☑ 炸金花 ☑ 华尔街 ...]   │
│ 观察窗口: [10] 期                   │
│ 触发阈值: [3] 次连续                │
│ 下注金额: [100.00]                  │
│ 玩法选择: [☑ 大 ☑ 小 ☐ 单 ☐ 双]   │
│ 封盘提前: [15] 秒停止              │
│                                     │
│ [▶ 启动]  [■ 停止]                 │
│ ┌─ 运行日志 ──────────────────────┐ │
│ │ 18:30:15 趋势跟踪已启动          │ │
│ │ 18:30:20 检测到连续3期"大"      │ │
│ │ 18:30:20 → 下注 "小 100"        │ │
│ │ 18:30:20 ✓ 消息已注入           │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

### Integration Points

- **SettingsService**: load/save `StrategyConfig` under key `"auto_bet"`
- **AccountResolver**: reuses `ResolvedDatabase.accid` for sender_id, `ResolvedDatabase.msg_db` for injection target
- **fetch_date.py**: reuses `DrawInfo` for countdown/period tracking; `extract_draw_info()` for current draw state
- **main_window.py**: add `auto_bet_panel` to left sidebar below block_box, wire signals
- **main_window_data.py**: connect `_load_data` / `_resolve_database` flow to auto_bet panel enable/disable

### Test Script (`tests/test_message_injector.py`)

A standalone verification script:
1. Accept account name as argument
2. Use `AccountResolver` to locate `msg_0.db`
3. Read current max `client_time` and `rand` from `message` table
4. Insert a test message with `client_time = now_ms`, `rand = max_rand + 1`
5. Print the inserted row
6. Wait 30 seconds
7. Check if the message appears in the WuQuan client (manual verification step)
8. Report whether the message was synced

## Files to Create

| File | Purpose |
|------|---------|
| `app/models/auto_bet.py` | Data models: DrawResult, BetDecision, StrategyConfig, InjectRecord |
| `app/services/message_injector.py` | SQLite message construction and injection |
| `app/services/auto_bet_service.py` | Strategy engine, scheduler, DrawResultProvider protocol |
| `app/ui/auto_bet_panel.py` | PySide6 GUI panel widget |
| `tests/test_message_injector.py` | DB injection verification script |

## Files to Modify

| File | Change |
|------|--------|
| `app/ui/main_window.py` | Import and instantiate AutoBetPanel, add to layout, wire signals |
| `app/ui/main_window_layout.py` | Add auto_bet panel to left sidebar layout |
| `app/ui/main_window_data.py` | Connect DB resolution to auto_bet panel enable/disable |
| `app/services/settings_service.py` | Add `auto_bet` key to defaults if needed |

## Open Questions

1. **Does the Tencent Cloud IM SDK pick up locally-inserted DB rows and sync them?** — This is the primary unknown. The test script (`test_message_injector.py`) is designed to answer this. If the answer is no, we fall back to UI automation (pyautogui/win32gui to paste and send in WuQuan window).

2. **Are messages encrypted differently per group?** — The current analysis shows AES-ECB with key `666888`. The test script should verify this by comparing injected encrypted messages with naturally-occurring ones.

## Fallback Plan

If DB injection does not trigger SDK sync:
- Replace `MessageInjector.inject_bet()` with a `UIAutomationSender` that:
  1. Finds the WuQuan window by title/class
  2. Activates it
  3. Uses `pyautogui` or `win32gui` to type the bet message and press Enter
  4. The `auto_bet_service.py` strategy engine interface remains unchanged
