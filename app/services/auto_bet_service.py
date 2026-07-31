from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from app.models.auto_bet import AutoBetRound, AutoBetRuntimeState, BetDecision, DrawResultProvider, InjectRecord, PendingAiBet, StrategyConfig, allowed_play_types_for_config
from app.services.frequency_probability_analysis import FrequencyProbabilityAnalysis, FrequencyProbabilityAnalyzer


logger = logging.getLogger(__name__)


THREE_DOOR_PLAYS = ("\u5c0f\u5355", "\u5927\u53cc", "\u5c0f\u53cc", "\u5927\u5355")


class BetMessageSender(Protocol):
    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool: ...


class AiRecommendationClient(Protocol):
    def recommend(
        self,
        config: StrategyConfig,
        results: list,
        quant_context: dict[str, Any] | None = None,
        performance_context: dict[str, Any] | None = None,
        retry_notifier: Callable[[int, int, str], None] | None = None,
    ) -> object: ...


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
        self._ai_prediction_store = None
        self._ai_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-bet")
        self._ai_attempted_keys: set[tuple[str, str]] = set()
        self._ai_pending: dict[tuple[str, str], PendingAiBet] = {}
        self._ai_skipped_keys: set[tuple[str, str]] = set()
        self._ai_waiting_keys: set[tuple[str, str]] = set()
        self._on_ai_pending_updated: Callable[[PendingAiBet | None], None] | None = None
        self._frequency_analyzer = FrequencyProbabilityAnalyzer()
        self._frequency_analysis: FrequencyProbabilityAnalysis | None = None

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
                ai_confidence_threshold=self._config.ai_confidence_threshold,
                ai_accuracy_window=self._config.ai_accuracy_window,
                ai_prefer_recommendation_on_conflict=self._config.ai_prefer_recommendation_on_conflict,
                take_profit_limit=self._config.take_profit_limit,
                stop_loss_limit=self._config.stop_loss_limit,
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

    @property
    def frequency_analysis(self) -> FrequencyProbabilityAnalysis | None:
        with self._lock:
            return self._frequency_analysis

    def refresh_frequency_analysis(
        self, site: str | None = None, *, target_period: str = ""
    ) -> FrequencyProbabilityAnalysis | None:
        with self._lock:
            cfg = self._config
            provider = self._result_provider
        active_site = str(site or cfg.site).strip()
        if provider is None or not active_site:
            return None
        analysis = self._frequency_analyzer.analyze(
            active_site,
            provider.get_recent_results(active_site, cfg.ai_history_count + 1),
            history_count=cfg.ai_history_count,
            confidence_threshold=cfg.ai_confidence_threshold,
            target_period=target_period,
        )
        with self._lock:
            self._frequency_analysis = analysis
        return analysis

    def set_ai_client(self, client: AiRecommendationClient | None) -> None:
        with self._lock:
            self._ai_client = client

    def set_ai_prediction_store(self, store) -> None:
        with self._lock:
            self._ai_prediction_store = store

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

    def start(self) -> bool:
        with self._lock:
            # Direct service callers using a real AI client receive the same
            # credential guard as the UI; test/dry-run clients remain usable.
            from app.services.ai_bet_client import AiBetClient

            if isinstance(self._ai_client, AiBetClient) and self._config.start_validation_errors():
                self._running = False
                return False
            self._running = True
            self._runtime_state = AutoBetRuntimeState()
            self._rounds = []
            self._last_bet_period = ""
            self._bet_keys.clear()
            prediction_store = self._ai_prediction_store
        self._restore_persisted_bet_keys(prediction_store)
        self._restore_pending_rounds(prediction_store)
        with self._lock:
            self._ai_attempted_keys.clear()
            self._ai_pending.clear()
            self._ai_skipped_keys.clear()
            self._ai_waiting_keys.clear()
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name="",
            play_type="",
            amount=0,
            content="策略引擎已启动",
            success=True,
        ))
        return True

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

    def shutdown(self) -> None:
        """Release the AI worker so a closed desktop process cannot linger."""
        self.stop()
        self._ai_executor.shutdown(wait=False, cancel_futures=True)

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
            if cfg.strategy_type in {"flat", "martingale", "trend_following", "ai"} and current_period:
                self._log_ai_waiting_for_window(site, current_period, countdown_sec)
            return

        # Every executable period first refreshes the selected site's history.
        # This keeps settlement and strategy/AI analysis on the same latest data.
        refreshed = self._refresh_history_before_bet(site, cfg, result_provider)
        if result_provider is not None and refreshed <= 0:
            self._add_ai_status_log(
                site,
                current_period,
                "最新开奖记录刷新失败或无新增数据，本期使用本地缓存分析",
                success=False,
            )

        if self._effective_bet_mode(cfg) == "three_doors":
            self._process_three_doors_period(site, current_period, cfg, injector, result_provider)
            return

        if cfg.strategy_type in {"flat", "martingale", "trend_following", "ai"}:
            if not self._ai_strategy_is_eligible(site, current_period, cfg, result_provider):
                return
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
        self._record_persisted_bet_keys(site, current_period, [
            decision.group_id for decision in active_decisions
        ])
        self._record_round(site, current_period, active_decisions)

    @staticmethod
    def _refresh_history_before_bet(
        site: str,
        cfg: StrategyConfig,
        result_provider: DrawResultProvider | None,
    ) -> int:
        if result_provider is None:
            return 0
        refresh = getattr(result_provider, "refresh_recent_results", None)
        if not callable(refresh):
            return 0
        return int(refresh(site, cfg.ai_history_count + 1) or 0)

    # ------------------------------------------------------------------
    # Strategy: Trend Following
    # ------------------------------------------------------------------

    def _process_three_doors_period(
        self,
        site: str,
        period: str,
        cfg: StrategyConfig,
        injector: BetMessageSender,
        result_provider: DrawResultProvider | None,
    ) -> None:
        if not period or result_provider is None:
            return
        self.settle_pending_rounds(result_provider)
        analysis = self.refresh_frequency_analysis(site, target_period=period)
        if analysis is None or len(analysis.selected_plays) != 3 or not analysis.should_bet:
            reason = analysis.reason if analysis is not None else "没有可用的复合玩法历史记录"
            self._add_ai_status_log(site, period, f"三门下注跳过：{reason}", success=False)
            return
        doors = list(analysis.selected_plays)
        amount = self._current_bet_amount(cfg) if cfg.strategy_type == "martingale" else float(cfg.bet_amount)
        reason = f"三门历史频率：{analysis.reason}"
        decisions = [
            BetDecision(True, play, amount, group_id, reason)
            for group_id in cfg.target_groups
            for play in doors
        ]
        with self._lock:
            processed_groups = {group_id for s, p, group_id in self._bet_keys if s == site and p == period}
        decisions = [decision for decision in decisions if decision.group_id not in processed_groups]
        if not decisions:
            return
        sent_decisions: list[BetDecision] = []
        for group_id, group_decisions in self._group_decisions(decisions).items():
            if self._execute_group(group_id, group_decisions, injector, site=site, period=period):
                sent_decisions.extend(group_decisions)
        if not sent_decisions:
            return
        with self._lock:
            for group_id in {decision.group_id for decision in sent_decisions}:
                self._bet_keys.add((site, period, group_id))
            self._last_bet_period = period
        self._record_persisted_bet_keys(site, period, [decision.group_id for decision in sent_decisions])
        self._record_round(site, period, sent_decisions)
        self._add_ai_status_log(
            site,
            period,
            f"三门自动下注：{'、'.join(doors)}；{reason}",
            success=True,
        )

    def _ai_strategy_is_eligible(
        self,
        site: str,
        period: str,
        cfg: StrategyConfig,
        result_provider: DrawResultProvider | None,
    ) -> bool:
        if cfg.strategy_type != "trend_following":
            return True
        if result_provider is None:
            self._add_ai_status_log(site, period, "趋势条件未满足：没有历史开奖记录", success=False)
            return False
        results = result_provider.get_recent_results(site, cfg.observation_window)
        if len(results) < cfg.trigger_threshold:
            self._add_ai_status_log(site, period, "趋势条件未满足：历史样本不足", success=True)
            return False
        mode = self._effective_bet_mode(cfg)
        ordered = sorted(results, key=lambda result: result.period)[-cfg.observation_window:]
        tail_result = self._result_for_mode(ordered[-1].result, mode)
        consecutive = 0
        for result in reversed(ordered):
            if self._result_for_mode(result.result, mode) != tail_result:
                break
            consecutive += 1
        if consecutive >= cfg.trigger_threshold:
            return True
        self._add_ai_status_log(
            site,
            period,
            f"趋势条件未满足：最近 {tail_result} 连续 {consecutive} 期，阈值 {cfg.trigger_threshold} 期",
            success=True,
        )
        return False

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
            analysis = self._analyze_frequency(cfg, result_provider)
            if analysis is None or len(analysis.selected_plays) != 3 or not analysis.should_bet:
                return []
            return [
                BetDecision(
                    True,
                    play,
                    amount,
                    group_id,
                    f"\u4e09\u95e8\u5386\u53f2\u9891\u7387：{analysis.reason}",
                )
                for group_id in target_groups
                for play in analysis.selected_plays
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
        return [
            BetDecision(True, play, amount, group_id, "\u56fa\u5b9a\u500d\u6295")
            for group_id in target_groups
            for play in plays
        ]

    def _analyze_frequency(
        self,
        cfg: StrategyConfig,
        result_provider: DrawResultProvider | None,
        *,
        target_period: str = "",
    ) -> FrequencyProbabilityAnalysis | None:
        if result_provider is None:
            return None
        results = result_provider.get_recent_results(cfg.site, cfg.ai_history_count + 1)
        return self._frequency_analyzer.analyze(
            cfg.site,
            results,
            history_count=cfg.ai_history_count,
            confidence_threshold=cfg.ai_confidence_threshold,
            target_period=target_period,
        )

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
            history_fetch_count = cfg.ai_history_count + 1
            self._settle_ai_predictions(result_provider, site)
            self.settle_pending_rounds(result_provider)
            unfiltered_results = result_provider.get_recent_results(site, history_fetch_count)
            eligible_results = [
                result for result in unfiltered_results
                if self._history_period_precedes_target(result.period, period)
            ]
            excluded_count = len(unfiltered_results) - len(eligible_results)
            results = eligible_results[-cfg.ai_history_count:]
            if excluded_count:
                self._add_ai_status_log(
                    site,
                    period,
                    f"AI 历史过滤：已排除 {excluded_count} 条期号大于等于目标期 {period} 的开奖记录",
                    success=True,
                )
        except Exception as exc:
            with self._lock:
                self._ai_skipped_keys.add(key)
            self._record_ai_failure(site, period, cfg, f"读取 AI 历史开奖失败: {exc}")
            self._add_ai_status_log(site, period, f"读取 AI 历史开奖失败: {exc}", success=False)
            return
        if not results:
            with self._lock:
                self._ai_skipped_keys.add(key)
            self._record_ai_failure(site, period, cfg, "没有可用于 AI 分析的历史开奖记录")
            self._add_ai_status_log(site, period, "没有可用于 AI 分析的历史开奖记录", success=False)
            return

        from app.services.ai_quant_analysis import build_quant_context

        quant_context = build_quant_context(results)
        store = self._ai_prediction_store
        performance_context = (
            store.performance_context(site, cfg.ai_accuracy_window)
            if store is not None else {}
        )
        history_snapshot = [
            {"period": str(result.period), "result": str(result.result)}
            for result in results
        ]
        self._add_ai_status_log(site, period, "AI 正在分析", success=True)
        future = self._ai_executor.submit(
            self._recommend_with_retry_logging,
            client,
            site,
            period,
            cfg,
            results,
            quant_context,
            performance_context,
        )
        future.add_done_callback(
            lambda done, s=site, p=period, c=cfg, sender=injector, h=history_snapshot, q=quant_context:
            self._handle_ai_recommendation(s, p, c, sender, done, h, q)
        )

    def _recommend_with_retry_logging(
        self,
        client: AiRecommendationClient,
        site: str,
        period: str,
        cfg: StrategyConfig,
        results: list,
        quant_context: dict[str, Any],
        performance_context: dict[str, Any],
    ) -> object:
        def on_retry(attempt: int, maximum: int, error: str) -> None:
            self._add_ai_status_log(
                site,
                period,
                f"AI 请求重试（第 {attempt}/{maximum} 次）：{error}",
                success=False,
            )

        return client.recommend(
            cfg,
            results,
            quant_context,
            performance_context,
            retry_notifier=on_retry,
        )

    def _log_ai_waiting_for_window(self, site: str, period: str, countdown_sec: int) -> None:
        key = (site, period)
        with self._lock:
            if key in self._ai_waiting_keys:
                return
            self._ai_waiting_keys.add(key)
        self._add_ai_status_log(
            site,
            period,
            f"AI 等待下注时窗：当前倒计时 {max(0, int(countdown_sec))} 秒",
            success=True,
        )

    def _handle_ai_recommendation(
        self,
        site: str,
        period: str,
        cfg: StrategyConfig,
        injector: BetMessageSender,
        future,
        history_snapshot: list[dict[str, str]],
        quant_snapshot: dict[str, Any],
    ) -> None:
        key = (site, period)
        try:
            recommendation = future.result()
            action = str(getattr(recommendation, "action", "") or "").strip().lower()
            play_type = str(getattr(recommendation, "play_type", "") or "").strip()
            reason = str(getattr(recommendation, "reason", "") or "").strip()
            quant_rationale = str(getattr(recommendation, "quant_rationale", "") or "").strip()
            confidence = int(getattr(recommendation, "confidence", 0))
            from app.services.ai_bet_client import VALID_PLAY_TYPES

            if action not in {"bet", "skip"} or not reason or not quant_rationale:
                raise ValueError("AI 建议缺少合法动作、量化依据或理由")
            if action == "bet" and play_type not in VALID_PLAY_TYPES:
                raise ValueError("AI 建议缺少合法玩法")
            if action == "bet" and play_type not in allowed_play_types_for_config(cfg):
                allowed_text = "、".join(allowed_play_types_for_config(cfg)) or "无"
                raise ValueError(f"AI 建议玩法不在当前允许玩法：{play_type}（允许：{allowed_text}）")
        except Exception as exc:
            with self._lock:
                self._ai_skipped_keys.add(key)
            self._record_ai_failure(site, period, cfg, str(exc), history_snapshot, quant_snapshot)
            self._add_ai_status_log(site, period, f"AI 建议失败: {exc}", success=False)
            return

        status = "ai_skip" if action == "skip" else (
            "low_confidence" if confidence < cfg.ai_confidence_threshold else "recommended"
        )
        store = self._ai_prediction_store
        if store is not None:
            store.record_prediction(
                site=site,
                period=period,
                action=action,
                play_type=play_type,
                confidence=confidence,
                quant_rationale=quant_rationale,
                reason=reason,
                model=cfg.ai_model,
                history_snapshot=history_snapshot,
                quant_snapshot=quant_snapshot,
                status=status,
            )
        if status != "recommended":
            with self._lock:
                self._ai_skipped_keys.add(key)
            if status == "ai_skip":
                message = f"AI 跳过本期（置信度 {confidence}/100）：{quant_rationale}；{reason}"
            else:
                message = (
                    f"AI 置信度 {confidence}/100 低于阈值 {cfg.ai_confidence_threshold}/100，"
                    f"跳过本期：{quant_rationale}；{reason}"
                )
            self._add_ai_status_log(site, period, message, success=True)
            return

        with self._lock:
            if not self._running or key in self._ai_skipped_keys:
                if store is not None:
                    store.update_status(site, period, "stopped")
                return

        pending = PendingAiBet(
            site=site,
            period=period,
            play_type=play_type,
            amount=self._ai_bet_amount(cfg),
            reason=reason,
            created_at=datetime.now(),
            confidence=confidence,
            quant_rationale=quant_rationale,
            has_play_conflict=False,
            recommended_plays=tuple(cfg.play_types),
        )
        if cfg.ai_require_confirmation:
            with self._lock:
                if not self._running or key in self._ai_skipped_keys:
                    return
            self._ai_pending[key] = pending
            conflict_text = (
                f"；与推荐玩法 {', '.join(pending.recommended_plays) or '无'} 冲突，请确认"
                if pending.has_play_conflict else ""
            )
            self._add_ai_status_log(
                site, period,
                f"AI 建议：{play_type}{self._format_amount(pending.amount)}；"
                f"置信度 {confidence}/100；{quant_rationale}；{reason}{conflict_text}",
                success=True,
            )
            self._notify_ai_pending(pending, visible=True)
            return

        if self._send_ai_bet(pending, cfg, injector):
            self._add_ai_status_log(
                site, period,
                f"AI 自动下注：{play_type}{self._format_amount(pending.amount)}；"
                f"置信度 {confidence}/100；{quant_rationale}；{reason}",
                success=True,
            )

    @staticmethod
    def _history_period_precedes_target(history_period: object, target_period: object) -> bool:
        history_text = str(history_period or "").strip()
        target_text = str(target_period or "").strip()
        if not history_text.isdigit() or not target_text.isdigit():
            return False
        return int(history_text) < int(target_text)

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
            if self._ai_prediction_store is not None:
                self._ai_prediction_store.update_status(site, period, "expired")
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
        if self._ai_prediction_store is not None:
            self._ai_prediction_store.update_status(site, period, "user_skip")
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
        with self._lock:
            already_sent_groups = {
                group_id
                for site, period, group_id in self._bet_keys
                if site == pending.site and period == pending.period
            }
            prediction_store = self._ai_prediction_store
        if prediction_store is not None:
            try:
                already_sent_groups.update(prediction_store.sent_group_ids(pending.site, pending.period))
            except Exception:
                logger.exception("Unable to restore automatic-bet duplicate keys")
        decisions = [
            BetDecision(True, pending.play_type, pending.amount, group_id, f"AI：{pending.reason}")
            for group_id in cfg.target_groups
            if group_id not in already_sent_groups
        ]
        if not decisions:
            self._add_ai_status_log(
                pending.site,
                pending.period,
                "AI 建议未发送：所有目标群组均已在本期下注",
                success=True,
            )
            return False
        sent_decisions: list[BetDecision] = []
        for group_id, group_decisions in self._group_decisions(decisions).items():
            if self._execute_group(group_id, group_decisions, injector, site=pending.site, period=pending.period):
                sent_decisions.extend(group_decisions)
        with self._lock:
            for decision in sent_decisions:
                self._bet_keys.add((pending.site, pending.period, decision.group_id))
        self._record_persisted_bet_keys(pending.site, pending.period, [
            decision.group_id for decision in sent_decisions
        ])
        if sent_decisions:
            self._record_round(pending.site, pending.period, sent_decisions)
            if self._ai_prediction_store is not None:
                self._ai_prediction_store.mark_sent(pending.site, pending.period)
            return True
        if self._ai_prediction_store is not None:
            self._ai_prediction_store.update_status(pending.site, pending.period, "send_failed")
        return False

    def _settle_ai_predictions(self, result_provider: DrawResultProvider, site: str) -> int:
        store = self._ai_prediction_store
        if store is None:
            return 0
        settled = 0
        for prediction in store.pending_sent_records(site):
            result = result_provider.get_result(prediction.site, prediction.period)
            if result is None:
                continue
            if str(result.site) != prediction.site or str(result.period) != prediction.period:
                self._add_log(InjectRecord(
                    ts=datetime.now(),
                    group_name="",
                    play_type="",
                    amount=0,
                    content=(
                        "AI 预测结算等待：开奖结果不匹配，"
                        f"待结算 {prediction.site} {prediction.period}，"
                        f"返回 {result.site} {result.period}"
                    ),
                    success=False,
                    site=prediction.site,
                    period=prediction.period,
                ))
                continue
            if store.settle(prediction.site, prediction.period, result.result):
                settled += 1
        return settled

    def _record_ai_failure(
        self,
        site: str,
        period: str,
        cfg: StrategyConfig,
        reason: str,
        history_snapshot: list[dict[str, str]] | None = None,
        quant_snapshot: dict[str, Any] | None = None,
    ) -> None:
        store = self._ai_prediction_store
        if store is None:
            return
        store.record_prediction(
            site=site,
            period=period,
            action="error",
            reason=reason,
            model=cfg.ai_model,
            history_snapshot=history_snapshot,
            quant_snapshot=quant_snapshot,
            status="failed",
        )

    def _add_ai_status_log(self, site: str, period: str, content: str, *, success: bool) -> None:
        group_names = [self._display_group_name(group_id) for group_id in self._config.target_groups]
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name=", ".join(name for name in group_names if name),
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
    ) -> bool:
        if not decisions:
            return False
        if len(decisions) == 1 or injector is None or not hasattr(injector, "inject_text"):
            return all(
                self._execute(decision, injector, site=site, period=period)
                for decision in decisions
            )

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
        return success

    def _execute(self, decision: BetDecision, injector: BetMessageSender | None = None, *, site: str = "", period: str = "") -> bool:
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
            return False

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
        return bool(success)


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

    def _restore_persisted_bet_keys(self, prediction_store) -> None:
        if prediction_store is None:
            return
        try:
            keys = prediction_store.all_sent_group_keys()
        except Exception:
            logger.exception("Unable to load automatic-bet duplicate keys")
            return
        with self._lock:
            self._bet_keys.update(keys)

    def _record_persisted_bet_keys(self, site: str, period: str, group_ids: list[str]) -> None:
        store = self._ai_prediction_store
        if store is None:
            return
        try:
            store.record_sent_groups(site, period, group_ids)
        except Exception:
            logger.exception("Unable to persist automatic-bet duplicate keys")

    def _restore_pending_rounds(self, prediction_store) -> None:
        if prediction_store is None:
            return
        try:
            records = prediction_store.pending_round_records()
        except Exception:
            logger.exception("Unable to load unsettled automatic-bet rounds")
            return
        restored_rounds: list[AutoBetRound] = []
        pending_staked = 0.0
        latest_martingale_step: int | None = None
        for record in records:
            bets: list[BetDecision] = []
            for item in record.bets:
                if not isinstance(item, dict):
                    continue
                play_type = str(item.get("play_type", ""))
                group_id = str(item.get("group_id", ""))
                if not play_type or not group_id:
                    continue
                try:
                    amount = float(item.get("amount", 0))
                except (TypeError, ValueError):
                    continue
                bets.append(BetDecision(
                    should_bet=True,
                    play_type=play_type,
                    amount=amount,
                    group_id=group_id,
                    reason=str(item.get("reason", "")),
                ))
            if not bets:
                continue
            restored_rounds.append(AutoBetRound(
                period=record.period,
                site=record.site,
                bets=bets,
                strategy_type=record.strategy_type,
                martingale_step=record.martingale_step,
                odds=dict(record.odds),
            ))
            pending_staked += sum(float(bet.amount) for bet in bets)
            if record.strategy_type == "martingale" and record.site == self.config.site:
                latest_martingale_step = record.martingale_step
        if not restored_rounds:
            return
        with self._lock:
            self._rounds.extend(restored_rounds)
            self._runtime_state.pending_staked += pending_staked
            if latest_martingale_step is not None:
                self._runtime_state.current_step = latest_martingale_step

    def _record_persisted_pending_round(self, round_info: AutoBetRound) -> None:
        store = self._ai_prediction_store
        if store is None:
            return
        try:
            store.record_pending_round(
                site=round_info.site,
                period=round_info.period,
                bets=[
                    {
                        "play_type": bet.play_type,
                        "amount": float(bet.amount),
                        "group_id": bet.group_id,
                        "reason": bet.reason,
                    }
                    for bet in round_info.bets
                ],
                strategy_type=round_info.strategy_type,
                martingale_step=round_info.martingale_step,
                odds=round_info.odds,
            )
        except Exception:
            logger.exception("Unable to persist unsettled automatic-bet round")

    def _settle_persisted_pending_round(self, site: str, period: str) -> None:
        store = self._ai_prediction_store
        if store is None:
            return
        try:
            store.settle_pending_round(site, period)
        except Exception:
            logger.exception("Unable to mark automatic-bet round as settled")

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
        for round_info in list(self._rounds):
            if round_info.settled:
                continue
            result = result_provider.get_result(round_info.site, round_info.period)
            if result is None:
                continue
            if str(result.site) != str(round_info.site) or str(result.period) != str(round_info.period):
                self._add_log(InjectRecord(
                    ts=datetime.now(),
                    group_name="",
                    play_type="",
                    amount=0,
                    content=(
                        "结算等待：开奖结果不匹配，"
                        f"待结算 {round_info.site} {round_info.period}，"
                        f"返回 {result.site} {result.period}"
                    ),
                    success=False,
                    site=round_info.site,
                    period=round_info.period,
                ))
                continue
            self._settle_round(round_info, result.result)
            settled += 1
        return settled

    def _record_round(self, site: str, period: str, bets: list[BetDecision]) -> None:
        if not period or not bets:
            return
        cfg = self.config
        round_info = AutoBetRound(
            period=period,
            site=site,
            bets=list(bets),
            strategy_type=cfg.strategy_type,
            martingale_step=self.runtime_state.current_step,
            odds=dict(cfg.odds),
        )
        with self._lock:
            self._rounds.append(round_info)
            state = self._runtime_state
            state.pending_staked += sum(float(bet.amount) for bet in bets)
            peak_amount = max(float(bet.amount) for bet in bets)
            if cfg.strategy_type == "martingale" and peak_amount > state.martingale_peak_amount:
                state.martingale_peak_step = round_info.martingale_step
                state.martingale_peak_amount = peak_amount
                state.martingale_peak_site = site
                state.martingale_peak_period = period
                state.martingale_peak_at = datetime.now()
        self._record_persisted_pending_round(round_info)

    def _settle_round(self, round_info: AutoBetRound, result: str) -> None:
        if round_info.settled:
            return
        cfg = self.config
        strategy_type = round_info.strategy_type or cfg.strategy_type
        odds = round_info.odds or cfg.odds
        staked = sum(float(bet.amount) for bet in round_info.bets)
        payout = 0.0
        outcomes: list[str] = []
        for bet in round_info.bets:
            won = self._bet_wins(bet.play_type, result)
            outcomes.append(
                f"{bet.play_type}{self._format_amount(bet.amount)}={'命中' if won else '未中'}"
            )
            if won:
                payout += float(bet.amount) * float(odds.get(bet.play_type, 1.0))
        profit = payout - staked

        round_info.settled = True
        round_info.result = result
        round_info.payout = payout
        round_info.profit = profit

        step_before = 0
        step_after = 0
        with self._lock:
            state = self._runtime_state
            step_before = state.current_step
            state.pending_staked = max(0.0, state.pending_staked - staked)
            state.total_staked += staked
            state.total_payout += payout
            state.total_profit += profit
            state.total_rounds += 1
            if profit > 0:
                state.win_rounds += 1
                state.consecutive_wins += 1
                state.consecutive_losses = 0
                state.max_consecutive_wins = max(state.max_consecutive_wins, state.consecutive_wins)
                if strategy_type == "martingale":
                    state.current_step = 0
            else:
                state.lose_rounds += 1
                state.consecutive_losses += 1
                state.consecutive_wins = 0
                state.max_consecutive_losses = max(state.max_consecutive_losses, state.consecutive_losses)
                if strategy_type == "martingale":
                    sequence = cfg.martingale_sequence or [cfg.bet_amount]
                    if round_info.martingale_step >= len(sequence) - 1:
                        state.current_step = 0
                    else:
                        state.current_step = round_info.martingale_step + 1
            self._apply_risk_limits(state, cfg)
            step_after = state.current_step
        self._settle_persisted_pending_round(round_info.site, round_info.period)
        group_names = ", ".join(
            self._display_group_name(bet.group_id) for bet in round_info.bets
        )
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name=group_names,
            play_type="/".join(bet.play_type for bet in round_info.bets),
            amount=staked,
            content=(
                f"结算：实际 {result}；{'、'.join(outcomes)}；"
                f"派彩 {payout:.2f}；本期盈亏 {profit:.2f}；"
                f"累计盈亏 {self.runtime_state.total_profit:.2f}；"
                f"倍投档位 {step_before + 1}→{step_after + 1}"
            ),
            success=profit > 0,
            site=round_info.site,
            period=round_info.period,
        ))

    @staticmethod
    def _apply_risk_limits(state: AutoBetRuntimeState, cfg: StrategyConfig) -> None:
        if cfg.take_profit_limit > 0 and state.total_profit >= cfg.take_profit_limit:
            state.halted = True
            state.halt_reason = (
                f"已触发止盈线 {cfg.take_profit_limit:.2f}，当前净盈亏 {state.total_profit:.2f}"
            )
        elif cfg.stop_loss_limit > 0 and state.total_profit <= -cfg.stop_loss_limit:
            state.halted = True
            state.halt_reason = (
                f"已触发止损线 {cfg.stop_loss_limit:.2f}，当前净盈亏 {state.total_profit:.2f}"
            )

    def _current_bet_amount(self, cfg: StrategyConfig) -> float:
        sequence = cfg.martingale_sequence or [cfg.bet_amount]
        index = min(max(self._runtime_state.current_step, 0), len(sequence) - 1)
        return float(sequence[index])

    def _ai_bet_amount(self, cfg: StrategyConfig) -> float:
        if cfg.strategy_type != "martingale":
            return float(cfg.bet_amount)
        return self._current_bet_amount(cfg)

    def _allowed_play_types_for_mode(self, cfg: StrategyConfig, mode: str | None = None) -> list[str]:
        if mode is None or mode == cfg.bet_mode:
            return allowed_play_types_for_config(cfg)
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
