from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Protocol

from app.models.auto_bet import AutoBetRound, AutoBetRuntimeState, BetDecision, DrawResultProvider, InjectRecord, PendingAiBet, StrategyConfig


logger = logging.getLogger(__name__)


class BetMessageSender(Protocol):
    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool: ...


class AiRecommendationClient(Protocol):
    def recommend(self, config: StrategyConfig, results: list) -> object: ...


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
        self._bet_keys: set[tuple[str, str, str]] = set()
        self._group_names: dict[str, str] = {}
        self._runtime_state = AutoBetRuntimeState()
        self._rounds: list[AutoBetRound] = []
        self._ai_client: AiRecommendationClient | None = None
        self._ai_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-bet")
        self._ai_attempted_keys: set[tuple[str, str]] = set()
        self._ai_pending: dict[tuple[str, str], PendingAiBet] = {}
        self._ai_skipped_keys: set[tuple[str, str]] = set()
        self._on_ai_pending_updated: Callable[[PendingAiBet | None], None] | None = None

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
                ai_provider=self._config.ai_provider,
                ai_base_url=self._config.ai_base_url,
                ai_model=self._config.ai_model,
                ai_api_key=self._config.ai_api_key,
                ai_history_count=self._config.ai_history_count,
                ai_require_confirmation=self._config.ai_require_confirmation,
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

    def set_ai_client(self, client: AiRecommendationClient | None) -> None:
        with self._lock:
            self._ai_client = client

    def set_ai_pending_callback(self, callback: Callable[[PendingAiBet | None], None] | None) -> None:
        self._on_ai_pending_updated = callback

    def set_group_names(self, group_names: dict[str, str]) -> None:
        with self._lock:
            self._group_names = {str(k): str(v) for k, v in dict(group_names or {}).items() if str(k)}

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
            self._bet_keys.clear()
            self._ai_attempted_keys.clear()
            self._ai_pending.clear()
            self._ai_skipped_keys.clear()
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
            pending = list(self._ai_pending.values())
            self._ai_pending.clear()
        for suggestion in pending:
            self._notify_ai_pending(suggestion, visible=False)
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
            cfg = self._config
            injector = self._injector
            result_provider = self._result_provider
            within_bet_window = self._within_bet_window(
                countdown_sec,
                cfg.lock_threshold_sec,
                period_start_time=period_start_time,
                period_end_time=period_end_time,
                now=now,
            )

        if injector is None:
            return

        self._expire_ai_pending(site, current_period, countdown_sec, cfg.lock_threshold_sec, within_bet_window)

        if not within_bet_window:
            return

        if cfg.strategy_type == "ai":
            self._process_ai_period(site, current_period, cfg, injector, result_provider)
            return

        if result_provider is not None:
            self.settle_pending_rounds(result_provider)

        decisions = self._analyze_many(cfg, result_provider)
        active_decisions = [decision for decision in decisions if decision.should_bet]
        if not active_decisions:
            return

        with self._lock:
            processed_groups = {group_id for s, p, group_id in self._bet_keys if s == site and p == current_period}
        active_decisions = [decision for decision in active_decisions if decision.group_id not in processed_groups]
        if not active_decisions:
            return

        for group_id, group_decisions in self._group_decisions(active_decisions).items():
            self._execute_group(group_id, group_decisions, injector, site=site, period=current_period)

        with self._lock:
            for group_id in {decision.group_id for decision in active_decisions}:
                self._bet_keys.add((site, current_period, group_id))
            self._last_bet_period = current_period
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
        target_groups = list(cfg.target_groups or [])
        if not target_groups:
            return []

        if cfg.strategy_type == "martingale":
            return self._martingale_decisions(cfg, mode, amount, target_groups)

        if mode == "three_doors":
            doors = [play for play in cfg.play_types if play in {"\u5c0f\u5355", "\u5927\u53cc", "\u5c0f\u53cc", "\u5927\u5355"}]
            if len(doors) != 3:
                return []
            return [
                BetDecision(True, play, amount, group_id, "\u4e09\u95e8\u4e0b\u6ce8")
                for group_id in target_groups
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

        return [
            BetDecision(
                should_bet=True,
                play_type=opposite,
                amount=amount,
                group_id=group_id,
                reason=f"\u8fde\u7eed{consecutive}\u671f'{tail_result}'\u2192\u53cd\u5411'{opposite}'",
            )
            for group_id in target_groups
        ]


    def _martingale_decisions(self, cfg: StrategyConfig, mode: str, amount: float, target_groups: list[str]) -> list[BetDecision]:
        """Fixed martingale: bet selected play(s) every eligible round."""
        plays = self._allowed_play_types_for_mode(cfg, mode)
        if not plays:
            return []
        if mode == "three_doors" and len(plays) != 3:
            return []
        return [
            BetDecision(True, play, amount, group_id, "\u56fa\u5b9a\u500d\u6295")
            for group_id in target_groups
            for play in plays
        ]

    # ------------------------------------------------------------------
    # Strategy: AI Recommendation
    # ------------------------------------------------------------------

    def _process_ai_period(
        self,
        site: str,
        period: str,
        cfg: StrategyConfig,
        injector: BetMessageSender,
        result_provider: DrawResultProvider | None,
    ) -> None:
        if not period or result_provider is None:
            return
        key = (site, period)
        with self._lock:
            if key in self._ai_attempted_keys or key in self._ai_skipped_keys or key in self._ai_pending:
                return
            client = self._ai_client
            if client is None:
                self._ai_skipped_keys.add(key)
                missing_client = True
            else:
                self._ai_attempted_keys.add(key)
                missing_client = False
        if missing_client:
            self._add_ai_status_log(site, period, "AI 客户端未配置", success=False)
            return

        try:
            results = result_provider.get_recent_results(site, cfg.ai_history_count)
        except Exception as exc:
            with self._lock:
                self._ai_skipped_keys.add(key)
            self._add_ai_status_log(site, period, f"读取 AI 历史开奖失败: {exc}", success=False)
            return
        if not results:
            with self._lock:
                self._ai_skipped_keys.add(key)
            self._add_ai_status_log(site, period, "没有可用于 AI 分析的历史开奖记录", success=False)
            return

        future = self._ai_executor.submit(client.recommend, cfg, results)
        future.add_done_callback(
            lambda done, s=site, p=period, c=cfg, sender=injector: self._handle_ai_recommendation(s, p, c, sender, done)
        )

    def _handle_ai_recommendation(self, site: str, period: str, cfg: StrategyConfig, injector: BetMessageSender, future) -> None:
        key = (site, period)
        try:
            recommendation = future.result()
            play_type = str(getattr(recommendation, "play_type", "") or "").strip()
            reason = str(getattr(recommendation, "reason", "") or "").strip()
            from app.services.ai_bet_client import VALID_PLAY_TYPES

            if play_type not in VALID_PLAY_TYPES or not reason:
                raise ValueError("AI 建议缺少合法玩法或理由")
        except Exception as exc:
            with self._lock:
                self._ai_skipped_keys.add(key)
            self._add_ai_status_log(site, period, f"AI 建议失败: {exc}", success=False)
            return

        pending = PendingAiBet(
            site=site,
            period=period,
            play_type=play_type,
            amount=self._current_bet_amount(cfg),
            reason=reason,
            created_at=datetime.now(),
        )
        if cfg.ai_require_confirmation:
            with self._lock:
                if not self._running or key in self._ai_skipped_keys:
                    return
                self._ai_pending[key] = pending
            self._add_ai_status_log(site, period, f"AI 建议：{play_type}{self._format_amount(pending.amount)}；{reason}", success=True)
            self._notify_ai_pending(pending, visible=True)
            return

        if self._send_ai_bet(pending, cfg, injector):
            self._add_ai_status_log(site, period, f"AI 自动下注：{play_type}{self._format_amount(pending.amount)}；{reason}", success=True)

    def pending_ai_recommendation(self, site: str, period: str) -> PendingAiBet | None:
        with self._lock:
            return self._ai_pending.get((site, period))

    def confirm_ai_bet(self, site: str, period: str, *, within_bet_window: bool) -> bool:
        key = (site, period)
        with self._lock:
            pending = self._ai_pending.pop(key, None)
            cfg = self._config
            injector = self._injector
            if pending is None:
                return False
            if not within_bet_window or injector is None:
                self._ai_skipped_keys.add(key)
                expired = True
            else:
                expired = False
        self._notify_ai_pending(pending, visible=False)
        if expired:
            self._add_ai_status_log(site, period, "AI 建议已过封盘时间，跳过本期", success=False)
            return False
        sent = self._send_ai_bet(pending, cfg, injector)
        self._add_ai_status_log(
            site,
            period,
            f"{'AI 确认下注' if sent else 'AI 确认下注发送失败'}：{pending.play_type}{self._format_amount(pending.amount)}",
            success=sent,
        )
        return sent

    def skip_ai_bet(self, site: str, period: str, reason: str = "用户跳过本期") -> bool:
        key = (site, period)
        with self._lock:
            pending = self._ai_pending.pop(key, None)
            if pending is None:
                return False
            self._ai_skipped_keys.add(key)
        self._notify_ai_pending(pending, visible=False)
        self._add_ai_status_log(site, period, reason, success=True)
        return True

    def _expire_ai_pending(
        self,
        site: str,
        period: str,
        countdown_sec: int,
        lock_threshold_sec: int,
        within_bet_window: bool,
    ) -> None:
        if within_bet_window and countdown_sec > lock_threshold_sec:
            return
        pending = self.pending_ai_recommendation(site, period)
        if pending is not None:
            self.skip_ai_bet(site, period, "已到封盘阈值，自动跳过 AI 建议")

    def _send_ai_bet(self, pending: PendingAiBet, cfg: StrategyConfig, injector: BetMessageSender) -> bool:
        decisions = [
            BetDecision(True, pending.play_type, pending.amount, group_id, f"AI：{pending.reason}")
            for group_id in cfg.target_groups
        ]
        if not decisions:
            return False
        for group_id, group_decisions in self._group_decisions(decisions).items():
            self._execute_group(group_id, group_decisions, injector, site=pending.site, period=pending.period)
        with self._lock:
            for decision in decisions:
                self._bet_keys.add((pending.site, pending.period, decision.group_id))
        self._record_round(pending.site, pending.period, decisions)
        return True

    def _add_ai_status_log(self, site: str, period: str, content: str, *, success: bool) -> None:
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name="",
            play_type="",
            amount=0,
            content=content,
            success=success,
            site=site,
            period=period,
        ))

    def _notify_ai_pending(self, pending: PendingAiBet, *, visible: bool) -> None:
        callback = self._on_ai_pending_updated
        if callback is None:
            return
        try:
            callback(pending if visible else None)
        except Exception:
            logger.exception("AI pending callback failed")

    @staticmethod
    def _group_decisions(decisions: list[BetDecision]) -> dict[str, list[BetDecision]]:
        grouped: dict[str, list[BetDecision]] = {}
        for decision in decisions:
            grouped.setdefault(decision.group_id, []).append(decision)
        return grouped

    def _execute_group(
        self,
        group_id: str,
        decisions: list[BetDecision],
        injector: BetMessageSender | None = None,
        *,
        site: str = "",
        period: str = "",
    ) -> None:
        if not decisions:
            return
        if len(decisions) == 1 or injector is None or not hasattr(injector, "inject_text"):
            for decision in decisions:
                self._execute(decision, injector, site=site, period=period)
            return

        content = "".join(self._format_bet_text(decision.play_type, decision.amount) for decision in decisions)
        success = bool(injector.inject_text(group_id, content, is_group=True))
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name=self._display_group_name(group_id),
            play_type="/".join(decision.play_type for decision in decisions),
            amount=sum(float(decision.amount) for decision in decisions),
            content=content,
            success=success,
            error="" if success else "DB ????",
            site=site,
            period=period,
            group_id=group_id,
        ))

    def _execute(self, decision: BetDecision, injector: BetMessageSender | None = None, *, site: str = "", period: str = "") -> None:
        """Send the bet through the configured message sender."""
        if injector is None:
            self._add_log(InjectRecord(
                ts=datetime.now(),
                group_name=self._display_group_name(decision.group_id),
                play_type=decision.play_type,
                amount=decision.amount,
                content="",
                success=False,
                error="?????????",
                site=site,
                period=period,
                group_id=decision.group_id,
            ))
            return

        success = injector.inject_bet(decision.group_id, decision.play_type, decision.amount)
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name=self._display_group_name(decision.group_id),
            play_type=decision.play_type,
            amount=decision.amount,
            content=self._format_bet_text(decision.play_type, decision.amount),
            success=success,
            error="" if success else "DB ????",
            site=site,
            period=period,
            group_id=decision.group_id,
        ))


    def _display_group_name(self, group_id: str) -> str:
        group_id = str(group_id or "")
        with self._lock:
            return self._group_names.get(group_id, group_id)

    @staticmethod
    def _format_bet_text(play_type: str, amount: float) -> str:
        return f"{play_type}{AutoBetService._format_amount(amount)}"

    @staticmethod
    def _format_amount(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:.2f}"

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
