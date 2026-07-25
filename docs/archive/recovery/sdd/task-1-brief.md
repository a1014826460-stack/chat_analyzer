# Task 1: Data Models and Strategy Protocol

**Goal:** Create the data models file that all other auto-bet modules depend on.

**File to create:** `app/models/auto_bet.py`

## Requirements (from spec)

1. `DrawResult` dataclass — single draw result (period, site, result, open_time)
2. `BetDecision` dataclass — strategy output (should_bet, play_type, amount, group_id, reason)
3. `DrawResultProvider` Protocol — external historical data interface with `get_recent_results(site, count)` and `get_result(site, period)`
4. `StrategyConfig` dataclass — persistable config with `to_dict()` and `from_dict()` methods. Fields: strategy_type, enabled, site, target_groups, observation_window, trigger_threshold, bet_amount, play_types, lock_threshold_sec
5. `InjectRecord` dataclass — log record (ts, group_name, play_type, amount, content, success, error)
6. `_ensure_str_list` helper — converts list-ish values to `list[str]`

## Exact Code

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class DrawResult:
    """Single draw result fed into the strategy engine.

    Historical data fetching is handled by an external script;
    the strategy engine receives results through DrawResultProvider.
    """
    period: str           # e.g. "20250628001"
    site: str             # "pc28" | "macao" | "australia" | "norway"
    result: str           # "大" | "小" | "单" | "双" | numeric string
    open_time: datetime | None = None


@dataclass
class BetDecision:
    """Output of strategy analysis — a single betting instruction."""
    should_bet: bool
    play_type: str        # "大" | "小" | "单" | "双" | "大单" | ...
    amount: float
    group_id: str         # target group/conversation identifier (sid)
    reason: str           # human-readable explanation for the run log


@runtime_checkable
class DrawResultProvider(Protocol):
    """Protocol for providing historical draw results.

    External scripts implement this to feed data to the strategy engine.
    The actual HTTP fetching / parsing lives outside this module.
    """

    def get_recent_results(self, site: str, count: int) -> list[DrawResult]: ...

    def get_result(self, site: str, period: str) -> DrawResult | None: ...


@dataclass
class StrategyConfig:
    """Persistable strategy configuration, saved via SettingsService under key 'auto_bet'."""
    strategy_type: str = "trend_following"
    enabled: bool = False
    site: str = "pc28"
    target_groups: list[str] = field(default_factory=list)
    # Trend-following parameters
    observation_window: int = 10
    trigger_threshold: int = 3
    bet_amount: float = 10.0
    play_types: list[str] = field(default_factory=lambda: ["大", "小"])
    lock_threshold_sec: int = 15  # stop betting N seconds before draw cutoff

    def to_dict(self) -> dict:
        return {
            "strategy_type": self.strategy_type,
            "enabled": self.enabled,
            "site": self.site,
            "target_groups": self.target_groups,
            "observation_window": self.observation_window,
            "trigger_threshold": self.trigger_threshold,
            "bet_amount": self.bet_amount,
            "play_types": self.play_types,
            "lock_threshold_sec": self.lock_threshold_sec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyConfig":
        if not isinstance(data, dict):
            return cls()
        return cls(
            strategy_type=str(data.get("strategy_type", "trend_following")),
            enabled=bool(data.get("enabled", False)),
            site=str(data.get("site", "pc28")),
            target_groups=_ensure_str_list(data.get("target_groups")),
            observation_window=int(data.get("observation_window", 10)),
            trigger_threshold=int(data.get("trigger_threshold", 3)),
            bet_amount=float(data.get("bet_amount", 10.0)),
            play_types=_ensure_str_list(data.get("play_types", ["大", "小"])),
            lock_threshold_sec=int(data.get("lock_threshold_sec", 15)),
        )


def _ensure_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


@dataclass
class InjectRecord:
    """Record of an injected message for the run log display."""
    ts: datetime
    group_name: str
    play_type: str
    amount: float
    content: str
    success: bool
    error: str = ""
```

## Testing

After writing the file, verify it can be imported and the models work:

```bash
.\.venv\Scripts\python.exe -c "
from app.models.auto_bet import DrawResult, BetDecision, StrategyConfig, InjectRecord, DrawResultProvider, _ensure_str_list
# Test _ensure_str_list
assert _ensure_str_list(['a', 'b']) == ['a', 'b']
assert _ensure_str_list(None) == []
assert _ensure_str_list([1, 2]) == ['1', '2']
# Test StrategyConfig round-trip
cfg = StrategyConfig(site='pc28', bet_amount=50.0)
d = cfg.to_dict()
cfg2 = StrategyConfig.from_dict(d)
assert cfg2.site == 'pc28'
assert cfg2.bet_amount == 50.0
# Test from_dict with empty
cfg3 = StrategyConfig.from_dict({})
assert cfg3.strategy_type == 'trend_following'
# Test DrawResultProvider is a Protocol
assert isinstance(None, DrawResultProvider) == False
print('All model tests passed!')
"
```
