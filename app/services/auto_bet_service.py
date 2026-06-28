from __future__ import annotations

import logging
import threading
from datetime import datetime

from app.models.auto_bet import BetDecision, DrawResultProvider, InjectRecord, StrategyConfig
from app.services.message_injector import MessageInjector


logger = logging.getLogger(__name__)


class AutoBetService:
    """Strategy engine and scheduler for automated betting.

    Runs on a background thread. The GUI calls tick() on each countdown
    update; the service decides whether to place a bet.

    Historical draw results come from an external DrawResultProvider
    (implemented by a separate script that fetches/parses lottery APIs).
    """

    def __init__(self) -> None:
        self._config = StrategyConfig()
        self._injector: MessageInjector | None = None
        self._result_provider: DrawResultProvider | None = None
        self._running = False
        self._lock = threading.Lock()
        self._log: list[InjectRecord] = []
        self._max_log_lines = 500
        self._on_log_updated: callable | None = None
        self._last_bet_period = ""

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
            )

    def apply_config(self, config: StrategyConfig) -> None:
        with self._lock:
            self._config = config

    def set_injector(self, injector: MessageInjector | None) -> None:
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

    def tick(self, site: str, countdown_sec: int, current_period: str) -> None:
        """Evaluate strategy and place bets if conditions are met."""
        with self._lock:
            if not self._running:
                return
            if site != self._config.site:
                return
            if countdown_sec <= self._config.lock_threshold_sec:
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

        decision = self._analyze(cfg, result_provider)
        if not decision.should_bet:
            return

        self._execute(decision, injector)

    # ------------------------------------------------------------------
    # Strategy: Trend Following
    # ------------------------------------------------------------------

    def _analyze(self, cfg: StrategyConfig, result_provider: DrawResultProvider | None = None) -> BetDecision:
        """Run the trend-following strategy."""
        if result_provider is None:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无历史数据提供者")

        results = result_provider.get_recent_results(cfg.site, cfg.observation_window)
        if len(results) < cfg.trigger_threshold:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="历史数据不足")

        # Get the most recent results, ordered by period
        sorted_results = sorted(results, key=lambda r: r.period)[-cfg.observation_window:]

        if not sorted_results:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无数据")

        tail_result = sorted_results[-1].result
        consecutive = 0
        for r in reversed(sorted_results):
            if r.result == tail_result:
                consecutive += 1
            else:
                break

        if consecutive < cfg.trigger_threshold:
            return BetDecision(
                should_bet=False, play_type="", amount=0, group_id="",
                reason=f"连续{consecutive}期'{tail_result}'，未达阈值{cfg.trigger_threshold}",
            )

        # Reverse bet: bet on the opposite
        opposite = self._opposite_play(tail_result, cfg.play_types)
        if opposite is None:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无可用反向玩法")

        target_group = cfg.target_groups[0] if cfg.target_groups else ""

        return BetDecision(
            should_bet=True,
            play_type=opposite,
            amount=cfg.bet_amount,
            group_id=target_group,
            reason=f"连续{consecutive}期'{tail_result}'→反向'{opposite}'",
        )

    def _execute(self, decision: BetDecision, injector: MessageInjector | None = None) -> None:
        """Inject the bet into the database."""
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
    def _opposite_play(result: str, play_types: list[str]) -> str | None:
        """Given a result like '大', return the opposite play from the allowed list."""
        opposites = {"大": "小", "小": "大", "单": "双", "双": "单"}
        opposite = opposites.get(result)
        if opposite and opposite in play_types:
            return opposite
        for pt in play_types:
            if pt != result:
                return pt
        return None

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
