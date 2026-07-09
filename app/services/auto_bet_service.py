from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Protocol

from app.models.auto_bet import AutoBetRound, AutoBetRuntimeState, BetDecision, DrawResultProvider, InjectRecord, StrategyConfig


logger = logging.getLogger(__name__)


class BetMessageSender(Protocol):
    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool: ...


class AutoBetService:
    """Strategy engine and scheduler for automated betting.

    Runs on a background thread. The GUI calls tick() on each countdown
    update; the service decides whether to place a bet.

    Historical draw results come from an external DrawResultProvider
    (implemented by a separate script that fetches/parses lottery APIs).
        """

    def __init__(self) -> None:
        self._config = StrategyConfig()
        self._injector: BetMessageSender | None = None
        self._result_provider: DrawResultProvider | None = None
        self._running = False
        self._lock = threading.Lock()
        self._log: list[InjectRecord] = []
        self._max_log_lines = 500
        self._on_log_updated: callable | None = None
        self._last_bet_period = ""
        self._runtime_state = AutoBetRuntimeState()
        self._rounds: list[AutoBetRound] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def config(self) -> StrategyConfig:
        with self._lock:
            return StrategyConfig(
                strategy_type=self._config.strategy_type,
                enabled=self._config.enabled,
                site=self._config.site,
                target_groups=list(self._config.target_groups),
                observation_window=self._config.observation_window,
                trigger_threshold=self._config.trigger_threshold,
                bet_amount=self._config.bet_amount,
                play_types=list(self._config.play_types),
                lock_threshold_sec=self._config.lock_threshold_sec,
                bet_mode=self._config.bet_mode,
                martingale_sequence=list(self._config.martingale_sequence),
                odds=dict(self._config.odds),
            )

    def apply_config(self, config: StrategyConfig) -> None:
        with self._lock:
            self._config = config

    def set_injector(self, injector: BetMessageSender | None) -> None:
        with self._lock:
            self._injector = injector

    def set_result_provider(self, provider: DrawResultProvider | None) -> None:
        with self._lock:
            self._result_provider = provider

    def set_log_callback(self, callback: callable | None) -> None:
        """Set callback(record: InjectRecord) for GUI log updates."""
        self._on_log_updated = callback

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self._running = True
            self._last_bet_period = ""
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name="",
            play_type="",
            amount=0,
            content="策略引擎已启动",
            success=True,
        ))

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name="",
            play_type="",
            amount=0,
            content="策略引擎已停止",
            success=True,
        ))

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # ------------------------------------------------------------------
    # Main tick — called by GUI on each countdown update
    # ------------------------------------------------------------------

    def tick(
        self,
        site: str,
        countdown_sec: int,
        current_period: str,
        *,
        period_start_time: datetime | None = None,
        period_end_time: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        """Evaluate strategy and place bets if conditions are met."""
        with self._lock:
            if not self._running:
                return
            if site != self._config.site:
                return
            if not self._within_bet_window(
                countdown_sec,
                self._config.lock_threshold_sec,
                period_start_time=period_start_time,
                period_end_time=period_end_time,
                now=now,
            ):
                return
            if self._last_bet_period == current_period:
                return
            # Mark this period as processed under lock to prevent race
            self._last_bet_period = current_period
            cfg = self._config
            injector = self._injector
            result_provider = self._result_provider

        if injector is None:
            return

        if result_provider is not None:
            self.settle_pending_rounds(result_provider)

        decisions = self._analyze_many(cfg, result_provider)
        active_decisions = [decision for decision in decisions if decision.should_bet]
        if not active_decisions:
            return

        for decision in active_decisions:
            self._execute(decision, injector)
        self._record_round(site, current_period, active_decisions)

    # ------------------------------------------------------------------
    # Strategy: Trend Following
    # ------------------------------------------------------------------

    def _analyze(self, cfg: StrategyConfig, result_provider: DrawResultProvider | None = None) -> BetDecision:
        """Run the trend-following strategy."""
        decisions = self._analyze_many(cfg, result_provider)
        if decisions:
            return decisions[0]
        if self._runtime_state.halted:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason=self._runtime_state.halt_reason)
        return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无可用下注决策")

    def _analyze_many(self, cfg: StrategyConfig, result_provider: DrawResultProvider | None = None) -> list[BetDecision]:
        """Run the configured strategy and return one or more betting decisions."""
        if self._runtime_state.halted:
            return []

        mode = self._effective_bet_mode(cfg)
        amount = self._current_bet_amount(cfg)
        target_group = cfg.target_groups[0] if cfg.target_groups else ""
        if mode == "three_doors":
            doors = [play for play in cfg.play_types if play in {"小单", "大双", "小双", "大单"}]
            if len(doors) != 3:
                return []
            return [
                BetDecision(True, play, amount, target_group, "三门下注")
                for play in doors
            ]

        if result_provider is None:
            return []

        results = result_provider.get_recent_results(cfg.site, cfg.observation_window)
        if len(results) < cfg.trigger_threshold:
            return []

        # Get the most recent results, ordered by period
        sorted_results = sorted(results, key=lambda r: r.period)[-cfg.observation_window:]

        if not sorted_results:
            return []

        tail_result = self._result_for_mode(sorted_results[-1].result, mode)
        consecutive = 0
        for r in reversed(sorted_results):
            if self._result_for_mode(r.result, mode) == tail_result:
                consecutive += 1
            else:
                break

        if consecutive < cfg.trigger_threshold:
            return []

        # Reverse bet: bet on the opposite
        opposite = self._opposite_play(tail_result, self._allowed_play_types_for_mode(cfg, mode))
        if opposite is None:
            return []

        return [BetDecision(
            should_bet=True,
            play_type=opposite,
            amount=amount,
            group_id=target_group,
            reason=f"连续{consecutive}期'{tail_result}'→反向'{opposite}'",
        )]

    def _execute(self, decision: BetDecision, injector: BetMessageSender | None = None) -> None:
        """Send the bet through the configured message sender."""
        if injector is None:
            self._add_log(InjectRecord(
                ts=datetime.now(), group_name=decision.group_id,
                play_type=decision.play_type, amount=decision.amount,
                content="", success=False, error="消息注入器未初始化",
            ))
            return

        success = injector.inject_bet(decision.group_id, decision.play_type, decision.amount)
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name=decision.group_id,
            play_type=decision.play_type,
            amount=decision.amount,
            content=f"{decision.play_type} {decision.amount}",
            success=success,
            error="" if success else "DB 注入失败",
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _within_bet_window(
        countdown_sec: int,
        lock_threshold_sec: int,
        *,
        period_start_time: datetime | None = None,
        period_end_time: datetime | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Return True only during start+30s through end-30s.

        When period boundaries are unavailable, keep the legacy countdown
        cutoff as a fallback so older callers continue to work.
        """
        if period_start_time is None or period_end_time is None:
            return countdown_sec > lock_threshold_sec

        current = now or datetime.now(tz=period_start_time.tzinfo)
        window_start = period_start_time + timedelta(seconds=30)
        window_end = period_end_time - timedelta(seconds=30)
        return window_start <= current <= window_end

    @staticmethod
    def _opposite_play(result: str, play_types: list[str]) -> str | None:
        """Given a result like '大双', return the opposite play from the allowed list."""
        opposites = {
            "大双": "小单",
            "小单": "大双",
            "大单": "小双",
            "小双": "大单",
            "大": "小",
            "小": "大",
            "单": "双",
            "双": "单",
        }
        opposite = opposites.get(result)
        if opposite and opposite in play_types:
            return opposite
        for pt in play_types:
            if pt != result:
                return pt
        return None

    @property
    def runtime_state(self) -> AutoBetRuntimeState:
        with self._lock:
            return AutoBetRuntimeState(**self._runtime_state.__dict__)

    def reset_runtime_state(self) -> None:
        with self._lock:
            self._runtime_state = AutoBetRuntimeState()
            self._rounds = []

    def settle_pending_rounds(self, result_provider: DrawResultProvider) -> int:
        settled = 0
        cfg = self.config
        for round_info in list(self._rounds):
            if round_info.settled:
                continue
            result = result_provider.get_result(round_info.site, round_info.period)
            if result is None:
                continue
            self._settle_round(round_info, result.result, cfg)
            settled += 1
        return settled

    def _record_round(self, site: str, period: str, bets: list[BetDecision]) -> None:
        if not period or not bets:
            return
        self._rounds.append(AutoBetRound(period=period, site=site, bets=list(bets)))

    def _settle_round(self, round_info: AutoBetRound, result: str, cfg: StrategyConfig) -> None:
        if round_info.settled:
            return
        staked = sum(float(bet.amount) for bet in round_info.bets)
        payout = 0.0
        for bet in round_info.bets:
            if self._bet_wins(bet.play_type, result):
                payout += float(bet.amount) * float(cfg.odds.get(bet.play_type, 1.0))
        profit = payout - staked

        round_info.settled = True
        round_info.result = result
        round_info.payout = payout
        round_info.profit = profit

        with self._lock:
            state = self._runtime_state
            state.total_staked += staked
            state.total_payout += payout
            state.total_profit += profit
            state.total_rounds += 1
            if profit > 0:
                state.win_rounds += 1
                state.consecutive_losses = 0
                state.current_step = 0
            else:
                state.lose_rounds += 1
                state.consecutive_losses += 1
                if state.current_step >= len(cfg.martingale_sequence) - 1:
                    state.halted = True
                    state.halt_reason = "倍投已到最后一档，等待人工处理"
                else:
                    state.current_step += 1

    def _current_bet_amount(self, cfg: StrategyConfig) -> float:
        sequence = cfg.martingale_sequence or [cfg.bet_amount]
        index = min(max(self._runtime_state.current_step, 0), len(sequence) - 1)
        return float(sequence[index])

    def _allowed_play_types_for_mode(self, cfg: StrategyConfig, mode: str | None = None) -> list[str]:
        mode = mode or self._effective_bet_mode(cfg)
        mode_allowed = {
            "size": {"大", "小"},
            "parity": {"单", "双"},
            "small_odd_big_even": {"小单", "大双"},
            "small_even_big_odd": {"小双", "大单"},
            "three_doors": {"小单", "大双", "小双", "大单"},
        }.get(mode, set(cfg.play_types))
        return [play for play in cfg.play_types if play in mode_allowed]

    @staticmethod
    def _effective_bet_mode(cfg: StrategyConfig) -> str:
        """Keep legacy configs working when play_types imply a non-size mode."""
        plays = set(cfg.play_types)
        if cfg.bet_mode == "size" and not (plays & {"大", "小"}):
            return "custom"
        if cfg.bet_mode == "parity" and not (plays & {"单", "双"}):
            return "custom"
        return cfg.bet_mode

    @staticmethod
    def _result_for_mode(result: str, mode: str) -> str:
        if mode == "size":
            if "大" in result:
                return "大"
            if "小" in result:
                return "小"
        if mode == "parity":
            if "单" in result:
                return "单"
            if "双" in result:
                return "双"
        return result

    @staticmethod
    def _bet_wins(play_type: str, result: str) -> bool:
        if play_type == result:
            return True
        if play_type in {"大", "小", "单", "双"}:
            return play_type in result
        return False

    def _add_log(self, record: InjectRecord) -> None:
        with self._lock:
            self._log.append(record)
            if len(self._log) > self._max_log_lines:
                self._log = self._log[-self._max_log_lines:]
        if self._on_log_updated:
            try:
                self._on_log_updated(record)
            except Exception:
                logger.exception("Log callback failed")

    def get_logs(self) -> list[InjectRecord]:
        with self._lock:
            return list(self._log)

    def clear_logs(self) -> None:
        with self._lock:
            self._log.clear()
