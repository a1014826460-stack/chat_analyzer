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


@dataclass(frozen=True)
class PendingAiBet:
    """A validated AI suggestion awaiting optional user confirmation."""
    site: str
    period: str
    play_type: str
    amount: float
    reason: str
    created_at: datetime


DEFAULT_ODDS: dict[str, float] = {
    "大": 1.98,
    "小": 1.98,
    "单": 1.98,
    "双": 1.98,
    "小单": 3.68,
    "大双": 3.68,
    "小双": 4.28,
    "大单": 4.28,
}


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
    bet_mode: str = "size"
    martingale_sequence: list[float] = field(default_factory=list)
    odds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ODDS))
    ai_provider: str = "openai_compatible"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""
    ai_history_count: int = 50
    ai_require_confirmation: bool = False

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
            "bet_mode": self.bet_mode,
            "martingale_sequence": self.martingale_sequence,
            "odds": self.odds,
            "ai_provider": self.ai_provider,
            "ai_base_url": self.ai_base_url,
            "ai_model": self.ai_model,
            "ai_api_key": self.ai_api_key,
            "ai_history_count": self.ai_history_count,
            "ai_require_confirmation": self.ai_require_confirmation,
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
            bet_mode=str(data.get("bet_mode", "size")),
            martingale_sequence=_ensure_float_list(data.get("martingale_sequence"), default=[]),
            odds=_ensure_odds(data.get("odds")),
            ai_provider=_ensure_ai_provider(data.get("ai_provider")),
            ai_base_url=str(data.get("ai_base_url", "") or "").strip(),
            ai_model=str(data.get("ai_model", "") or "").strip(),
            ai_api_key=str(data.get("ai_api_key", "") or "").strip(),
            ai_history_count=_ensure_ai_history_count(data.get("ai_history_count")),
            ai_require_confirmation=bool(data.get("ai_require_confirmation", False)),
        )


def _ensure_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _ensure_float_list(value: object, default: list[float] | None = None) -> list[float]:
    result: list[float] = []
    if isinstance(value, list):
        iterable = value
    elif isinstance(value, str):
        iterable = value.replace(",", "-").split("-")
    else:
        iterable = []
    for item in iterable:
        try:
            amount = float(str(item).strip())
        except (TypeError, ValueError):
            continue
        if amount > 0:
            result.append(amount)
    if result:
        return result
    return list(default or [10.0])


def _ensure_odds(value: object) -> dict[str, float]:
    odds = dict(DEFAULT_ODDS)
    if isinstance(value, dict):
        for key, raw in value.items():
            name = str(key).strip()
            if not name:
                continue
            try:
                number = float(str(raw).strip())
            except (TypeError, ValueError):
                continue
            if number > 0:
                odds[name] = number
    return odds


def _ensure_ai_provider(value: object) -> str:
    provider = str(value or "openai_compatible").strip()
    return provider if provider in {"openai_compatible", "anthropic"} else "openai_compatible"


def _ensure_ai_history_count(value: object) -> int:
    try:
        return min(200, max(20, int(value)))
    except (TypeError, ValueError):
        return 50


@dataclass
class AutoBetRuntimeState:
    current_step: int = 0
    total_staked: float = 0.0
    total_payout: float = 0.0
    total_profit: float = 0.0
    total_rounds: int = 0
    win_rounds: int = 0
    lose_rounds: int = 0
    consecutive_losses: int = 0
    halted: bool = False
    halt_reason: str = ""


@dataclass
class AutoBetRound:
    period: str
    site: str
    bets: list[BetDecision]
    settled: bool = False
    result: str = ""
    payout: float = 0.0
    profit: float = 0.0


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
    site: str = ""
    period: str = ""
    group_id: str = ""
