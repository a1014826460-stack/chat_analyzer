from __future__ import annotations

from app.models.auto_bet import AutoBetRound, AutoBetRuntimeState, BetDecision, DrawResult, StrategyConfig, allowed_play_types_for_config
from app.services.auto_bet_service import AutoBetService
from datetime import datetime
import time


class Provider:
    def __init__(self, recent=None, by_period=None):
        self.recent = recent or []
        self.by_period = by_period or {}

    def get_recent_results(self, site: str, count: int):
        return list(self.recent[-count:])

    def get_result(self, site: str, period: str):
        return self.by_period.get(period)


def test_strategy_config_persists_mode_martingale_and_odds():
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="three_doors",
        play_types=["小单", "大双", "小双"],
        martingale_sequence=[100, 200, 400],
        odds={"小单": 3.68, "大": 1.98},
    )

    loaded = StrategyConfig.from_dict(cfg.to_dict())

    assert loaded.bet_mode == "three_doors"
    assert loaded.play_types == ["小单", "大双", "小双"]
    assert loaded.martingale_sequence == [100.0, 200.0, 400.0]
    assert loaded.odds["小单"] == 3.68
    assert loaded.odds["大"] == 1.98


def test_strategy_config_ignores_legacy_local_ai_credentials_and_clamps_lock_threshold():
    config = StrategyConfig.from_dict({
        "lock_threshold_sec": 5,
        "ai_provider": "anthropic",
        "ai_base_url": "https://ai.example",
        "ai_model": "legacy-model",
        "ai_api_key": "legacy-secret",
    })

    assert "ai_api_key" not in config.to_dict()
    assert "ai_base_url" not in config.to_dict()
    assert config.lock_threshold_sec == 20
    assert StrategyConfig.from_dict({"lock_threshold_sec": 90}).lock_threshold_sec == 60


def test_strategy_config_accepts_up_to_five_hundred_history_records():
    assert StrategyConfig.from_dict({"ai_history_count": 500}).ai_history_count == 500
    assert StrategyConfig.from_dict({"ai_history_count": 501}).ai_history_count == 500


def test_strategy_config_reports_all_automatic_bet_start_validation_errors():
    config = StrategyConfig(
        target_groups=[],
        play_types=[],
        odds={"大": 0},
    )

    assert config.start_validation_errors() == [
        "请至少选择一个目标群组",
        "请至少选择一个推荐玩法",
        "请填写全部玩法的有效赔率",
    ]


def test_auto_bet_service_does_not_require_local_ai_credentials():
    service = AutoBetService()
    service.apply_config(StrategyConfig(target_groups=["g1"]))

    assert service.start() is True
    assert service.is_running is True


def test_strategy_config_persists_martingale_strategy_type():
    cfg = StrategyConfig(strategy_type="martingale", bet_mode="size", play_types=["\u5927"], martingale_sequence=[100, 200])

    loaded = StrategyConfig.from_dict(cfg.to_dict())

    assert loaded.strategy_type == "martingale"
    assert loaded.bet_mode == "size"
    assert loaded.play_types == ["\u5927"]
    assert loaded.martingale_sequence == [100.0, 200.0]


def test_legacy_ai_strategy_migrates_to_flat_and_persists_risk_preferences():
    config = StrategyConfig.from_dict({
        "strategy_type": "ai",
        "ai_prefer_recommendation_on_conflict": True,
        "take_profit_limit": 500,
        "stop_loss_limit": -200,
    })

    assert config.strategy_type == "flat"
    assert config.ai_prefer_recommendation_on_conflict is True
    assert config.take_profit_limit == 500.0
    assert config.stop_loss_limit == 0.0
    assert StrategyConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


def test_ai_allowed_plays_are_exactly_the_user_checked_plays_regardless_of_mode():
    cfg = StrategyConfig(
        strategy_type="flat",
        bet_mode="size",
        play_types=["大", "单"],
    )

    assert allowed_play_types_for_config(cfg) == ["大", "单"]


def test_martingale_strategy_bets_selected_play_every_round_without_trend_trigger():
    svc = AutoBetService()
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        bet_mode="size",
        play_types=["\u5927"],
        target_groups=["207191791"],
        martingale_sequence=[100, 200, 400],
        trigger_threshold=99,
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 1

    decisions = svc._analyze_many(cfg, Provider(recent=[]))

    assert decisions == [BetDecision(True, "\u5927", 200.0, "207191791", "\u56fa\u5b9a\u500d\u6295")]


def test_martingale_strategy_bets_all_selected_doors_each_round():
    svc = AutoBetService()
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        bet_mode="three_doors",
        play_types=["\u5c0f\u5355", "\u5927\u53cc", "\u5c0f\u53cc"],
        target_groups=["207191791"],
        martingale_sequence=[100, 200, 400],
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 2

    decisions = svc._analyze_many(cfg, Provider(recent=[]))

    assert decisions == [
        BetDecision(True, "\u5c0f\u5355", 400.0, "207191791", "\u56fa\u5b9a\u500d\u6295"),
        BetDecision(True, "\u5927\u53cc", 400.0, "207191791", "\u56fa\u5b9a\u500d\u6295"),
        BetDecision(True, "\u5c0f\u53cc", 400.0, "207191791", "\u56fa\u5b9a\u500d\u6295"),
    ]


def test_three_doors_uses_history_to_choose_three_doors_with_current_step_amount():
    svc = AutoBetService()
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="three_doors",
        ai_confidence_threshold=0,
        martingale_sequence=[100, 200, 400],
        target_groups=["207191791"],
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 1

    decisions = svc._analyze_many(cfg, Provider(recent=[
        DrawResult("1", "pc28", "小单"),
        DrawResult("2", "pc28", "大双"),
        DrawResult("3", "pc28", "大单"),
    ]))

    assert [(item.play_type, item.amount) for item in decisions] == [
        ("小单", 200.0), ("大双", 200.0), ("大单", 200.0),
    ]
    assert all("排除小双(0.0%)" in item.reason for item in decisions)


def test_three_doors_excludes_the_least_frequent_composite_result():
    svc = AutoBetService()
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="three_doors",
        target_groups=["207191791"],
        ai_history_count=20,
    )
    provider = Provider(recent=[
        DrawResult("1", "pc28", "大单"),
        DrawResult("2", "pc28", "大单"),
        DrawResult("3", "pc28", "大双"),
        DrawResult("4", "pc28", "小单"),
    ])

    decisions = svc._analyze_many(cfg, provider)

    assert [decision.play_type for decision in decisions] == ["小单", "大双", "大单"]
    assert all("排除小双(0.0%)" in decision.reason for decision in decisions)


def test_three_doors_uses_fixed_order_to_break_frequency_ties():
    svc = AutoBetService()
    cfg = StrategyConfig(
        site="pc28", bet_mode="three_doors", target_groups=["g1"], ai_confidence_threshold=0,
    )
    provider = Provider(recent=[
        DrawResult("1", "pc28", "大单"),
        DrawResult("2", "pc28", "大双"),
        DrawResult("3", "pc28", "小单"),
        DrawResult("4", "pc28", "小双"),
    ])

    decisions = svc._analyze_many(cfg, provider)

    assert [decision.play_type for decision in decisions] == ["大双", "小双", "大单"]
    assert all("排除小单(25.0%)" in decision.reason for decision in decisions)


def test_three_doors_skips_without_a_recognized_composite_history_result():
    svc = AutoBetService()
    cfg = StrategyConfig(site="pc28", bet_mode="three_doors", target_groups=["g1"])
    provider = Provider(recent=[DrawResult("1", "pc28", "未知")])

    assert svc._analyze_many(cfg, provider) == []


def test_three_doors_sends_all_retained_plays_when_any_probability_meets_threshold():
    service = AutoBetService()
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="three_doors",
        target_groups=["g1"],
        ai_history_count=20,
        ai_confidence_threshold=60,
    )
    provider = Provider(recent=[
        DrawResult("1", "pc28", "大单"),
        DrawResult("2", "pc28", "大单"),
        DrawResult("3", "pc28", "大单"),
        DrawResult("4", "pc28", "小单"),
    ])

    decisions = service._analyze_many(cfg, provider)

    assert [decision.play_type for decision in decisions] == ["小单", "小双", "大单"]
    assert all("阈值60%" in decision.reason for decision in decisions)


def test_three_doors_skips_when_no_retained_play_meets_confidence_threshold():
    service = AutoBetService()
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="three_doors",
        target_groups=["g1"],
        ai_history_count=20,
        ai_confidence_threshold=51,
    )
    provider = Provider(recent=[
        DrawResult("1", "pc28", "小单"),
        DrawResult("2", "pc28", "大双"),
        DrawResult("3", "pc28", "小双"),
        DrawResult("4", "pc28", "大单"),
    ])

    assert service._analyze_many(cfg, provider) == []


def test_two_door_mode_uses_current_step_amount_and_selected_allowed_play():
    provider = Provider(recent=[
        DrawResult(site="pc28", period="1", result="大"),
        DrawResult(site="pc28", period="2", result="大"),
        DrawResult(site="pc28", period="3", result="大"),
    ])
    svc = AutoBetService()
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="size",
        observation_window=3,
        trigger_threshold=3,
        play_types=["大", "小"],
        martingale_sequence=[100, 200, 400],
        target_groups=["207191791"],
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 2

    decisions = svc._analyze_many(cfg, provider)

    assert len(decisions) == 1
    assert decisions[0].should_bet is True
    assert decisions[0].play_type == "小"
    assert decisions[0].amount == 400.0


def test_settle_winning_round_resets_martingale_and_updates_profit():
    svc = AutoBetService()
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        martingale_sequence=[100, 200, 400],
        odds={"小单": 3.68, "大双": 3.68},
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 1
    svc._record_round("pc28", "1001", [
        BetDecision(True, "小单", 200, "207191791", "test"),
        BetDecision(True, "大双", 200, "207191791", "test"),
    ])

    settled = svc.settle_pending_rounds(Provider(by_period={"1001": DrawResult("1001", "pc28", "小单")}))
    state = svc.runtime_state

    assert settled == 1
    assert state.current_step == 0
    assert state.total_staked == 400
    assert state.total_payout == 736
    assert state.total_profit == 336
    assert state.win_rounds == 1
    assert state.lose_rounds == 0
    assert state.consecutive_losses == 0
    assert state.halted is False


def test_settle_losing_last_martingale_step_returns_to_first_step():
    svc = AutoBetService()
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        martingale_sequence=[100, 200],
        odds={"小单": 3.68},
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 1
    svc._record_round("pc28", "1002", [BetDecision(True, "小单", 200, "207191791", "test")])

    settled = svc.settle_pending_rounds(Provider(by_period={"1002": DrawResult("1002", "pc28", "大单")}))
    state = svc.runtime_state

    assert settled == 1
    assert state.current_step == 0
    assert state.total_staked == 200
    assert state.total_payout == 0
    assert state.total_profit == -200
    assert state.lose_rounds == 1
    assert state.consecutive_losses == 1
    assert state.halted is False


def test_runtime_state_tracks_current_and_maximum_win_loss_streaks():
    svc = AutoBetService()
    svc.apply_config(StrategyConfig(site="pc28", odds={"大": 2.0}))
    results = [("1001", "大单"), ("1002", "大双"), ("1003", "小单"), ("1004", "小双")]

    for period, outcome in results:
        svc._record_round("pc28", period, [BetDecision(True, "大", 10, "g1", "test")])
        assert svc.settle_pending_rounds(Provider(by_period={period: DrawResult(period, "pc28", outcome)})) == 1

    state = svc.runtime_state
    assert state.consecutive_wins == 0
    assert state.consecutive_losses == 2
    assert state.max_consecutive_wins == 2
    assert state.max_consecutive_losses == 2
    assert state.halt_reason == ""


def test_settle_round_waits_for_a_result_matching_its_site_and_period():
    svc = AutoBetService()
    svc.apply_config(StrategyConfig(site="pc28", odds={"大": 2.0}))
    svc._record_round("pc28", "1006", [BetDecision(True, "大", 10, "g1", "test")])

    settled = svc.settle_pending_rounds(Provider(by_period={
        "1006": DrawResult("1005", "macao", "大单"),
    }))

    state = svc.runtime_state
    assert settled == 0
    assert state.pending_staked == 10
    assert state.total_rounds == 0
    assert any("开奖结果不匹配" in record.content for record in svc.get_logs())


def test_settlement_log_includes_site_period_result_and_martingale_step_change():
    svc = AutoBetService()
    svc.apply_config(StrategyConfig(
        strategy_type="martingale", site="pc28", martingale_sequence=[10, 20], odds={"大": 2.0},
    ))
    svc._record_round("pc28", "1007", [BetDecision(True, "大", 10, "g1", "test")])

    assert svc.settle_pending_rounds(Provider(by_period={"1007": DrawResult("1007", "pc28", "大单")})) == 1

    record = [record for record in svc.get_logs() if record.content.startswith("结算：")][-1]
    assert record.site == "pc28"
    assert record.period == "1007"
    assert "实际 大单" in record.content
    assert "大10=命中" in record.content
    assert "倍投档位 1→1" in record.content


def test_flat_ai_loss_does_not_advance_or_halt_the_martingale_sequence():
    svc = AutoBetService()
    cfg = StrategyConfig(strategy_type="flat", site="pc28", martingale_sequence=[10, 20])
    svc.apply_config(cfg)
    svc._record_round("pc28", "1003", [BetDecision(True, "单", 10, "g1", "AI")])

    svc.settle_pending_rounds(Provider(by_period={"1003": DrawResult("1003", "pc28", "小双")}))

    state = svc.runtime_state
    assert state.current_step == 0
    assert state.consecutive_losses == 1
    assert state.halted is False
    assert state.total_profit == -10


def test_auto_bet_start_resets_previous_session_runtime_totals_and_rounds():
    svc = AutoBetService()
    svc._runtime_state = AutoBetRuntimeState(
        current_step=2,
        pending_staked=40,
        total_staked=70,
        total_payout=39.6,
        total_profit=-30.4,
        total_rounds=3,
        win_rounds=1,
        lose_rounds=2,
        consecutive_losses=2,
        halted=True,
        halt_reason="倍投已到最后一档，等待人工处理",
    )
    svc._rounds = [AutoBetRound("1004", "pc28", [BetDecision(True, "单", 40, "g1", "AI")])]

    svc.start()

    assert svc.runtime_state == AutoBetRuntimeState()
    assert svc._rounds == []


def test_runtime_statistics_separate_pending_stake_from_settled_profit():
    svc = AutoBetService()
    cfg = StrategyConfig(strategy_type="flat", site="pc28", odds={"单": 1.98})
    svc.apply_config(cfg)
    svc._record_round("pc28", "1005", [
        BetDecision(True, "单", 10, "g1", "AI"),
        BetDecision(True, "单", 10, "g2", "AI"),
    ])

    pending = svc.runtime_state
    assert pending.pending_staked == 20
    assert pending.total_staked == 0
    assert pending.total_profit == 0

    svc.settle_pending_rounds(Provider(by_period={"1005": DrawResult("1005", "pc28", "大单")}))

    settled = svc.runtime_state
    assert settled.pending_staked == 0
    assert settled.total_staked == 20
    assert settled.total_payout == 39.6
    assert settled.total_profit == 19.6


def test_halted_service_does_not_analyze_new_bets_until_manual_reset():
    svc = AutoBetService()
    cfg = StrategyConfig(site="pc28", bet_mode="three_doors", play_types=["小单", "大双", "小双"], target_groups=["207191791"])
    svc.apply_config(cfg)
    svc._runtime_state.halted = True
    svc._runtime_state.halt_reason = "等待人工处理"

    assert svc._analyze_many(cfg, Provider()) == []
    svc.reset_runtime_state()
    assert svc._runtime_state.halted is False


class Sender:
    def __init__(self):
        self.sent = []

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        self.sent.append((group_id, play_type, amount))
        return True


def _started_three_door_service():
    svc = AutoBetService()
    sender = Sender()
    svc.apply_config(StrategyConfig(
        strategy_type="flat",
        site="pc28",
        play_types=["小单"],
        target_groups=["207191791"],
    ))
    svc.set_injector(sender)
    svc.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小单")]))
    svc.set_ai_client(AiClient(play_type="小单"))
    svc.start()
    return svc, sender


def test_tick_before_period_start_plus_30_seconds_does_not_bet():
    svc, sender = _started_three_door_service()

    svc.tick(
        "pc28",
        151,
        "20260705001",
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 0, 29),
    )

    assert sender.sent == []


def test_tick_inside_start_plus_30_to_end_minus_30_window_bets():
    svc, sender = _started_three_door_service()

    svc.tick(
        "pc28",
        150,
        "20260705001",
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 0, 30),
    )

    assert _wait_until(lambda: sender.sent == [("207191791", "小单", 10.0)])


def test_tick_after_period_end_minus_30_seconds_does_not_bet():
    svc, sender = _started_three_door_service()

    svc.tick(
        "pc28",
        29,
        "20260705001",
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 2, 31),
    )

    assert sender.sent == []



def test_martingale_strategy_creates_decisions_for_all_target_groups():
    svc = AutoBetService()
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        bet_mode="size",
        play_types=["[0m"],
        target_groups=["g1", "g2"],
        martingale_sequence=[100],
    )
    cfg.play_types = ["?"]

    decisions = svc._analyze_many(cfg, Provider(recent=[]))

    assert [(d.group_id, d.play_type, d.amount) for d in decisions] == [
        ("g1", "?", 100.0),
        ("g2", "?", 100.0),
    ]


def test_tick_places_dynamic_three_doors_without_calling_ai_and_excludes_target_history():
    service = AutoBetService()
    sender = Sender()
    client = AiClient()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", bet_mode="three_doors", target_groups=["g1"],
        ai_history_count=20, ai_confidence_threshold=0,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[
        DrawResult("998", "pc28", "小单"),
        DrawResult("999", "pc28", "大双"),
        DrawResult("1000", "pc28", "大单"),
        DrawResult("1001", "pc28", "小双"),
    ]))
    service.set_ai_client(client)
    service.start()

    _ai_tick(service)

    assert sender.sent == [("g1", "小单", 10.0), ("g1", "大双", 10.0), ("g1", "大单", 10.0)]
    assert client.calls == []


def test_dynamic_three_doors_refreshes_history_then_logs_settlement_for_the_bet_period():
    class RefreshingProvider(Provider):
        def __init__(self):
            super().__init__(recent=[
                DrawResult("998", "pc28", "小单"),
                DrawResult("999", "pc28", "大双"),
                DrawResult("1000", "pc28", "大单"),
            ])
            self.refresh_calls = []

        def refresh_recent_results(self, site: str, count: int):
            self.refresh_calls.append((site, count))
            if not any(result.period == "1001" for result in self.recent):
                self.recent.append(DrawResult("1001", "pc28", "小双"))
            self.by_period["1001"] = DrawResult("1001", "pc28", "小双")
            return 1

    service = AutoBetService()
    sender = Sender()
    provider = RefreshingProvider()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", bet_mode="three_doors", target_groups=["g1"],
        ai_history_count=20, ai_confidence_threshold=0,
    ))
    service.set_injector(sender)
    service.set_result_provider(provider)
    service.start()

    _ai_tick(service)
    service.tick("pc28", 120, "1002")

    assert provider.refresh_calls == [("pc28", 21), ("pc28", 21)]
    settlement = [record for record in service.get_logs() if record.period == "1001" and record.content.startswith("结算：")]
    assert len(settlement) == 1
    assert "实际 小双" in settlement[0].content


def test_tick_deduplicates_by_site_period_and_group_not_period_only():
    svc = AutoBetService()
    sender = Sender()
    cfg = StrategyConfig(
        strategy_type="flat",
        site="pc28",
        bet_mode="size",
        play_types=["大"],
        target_groups=["g1", "g2"],
        bet_amount=100,
    )
    svc.apply_config(cfg)
    svc.set_injector(sender)
    svc.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小单")]))
    svc.set_ai_client(AiClient(play_type="大"))
    svc.start()

    kwargs = dict(
        countdown_sec=120,
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 1, 0),
    )
    svc.tick("pc28", current_period="20260705001", **kwargs)
    svc.tick("pc28", current_period="20260705001", **kwargs)

    assert _wait_until(lambda: sender.sent == [("g1", "大", 100.0), ("g2", "大", 100.0)])


def test_restart_does_not_resend_a_persisted_site_period_group(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    sender = Sender()
    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    store.record_sent_groups("pc28", "1001", ["g1"])
    service = AutoBetService()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1", "g2"], bet_amount=100,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小单")]))
    service.set_ai_client(AiClient(play_type="大"))
    service.set_ai_prediction_store(store)

    service.start()
    _ai_tick(service)

    assert _wait_until(lambda: sender.sent == [("g2", "大", 100.0)])
    assert store.sent_group_ids("pc28", "1001") == {"g1", "g2"}


def test_restart_restores_an_unsettled_round_and_its_original_odds(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    first = AutoBetService()
    first.apply_config(StrategyConfig(
        strategy_type="martingale", site="pc28", martingale_sequence=[10, 20], odds={"大": 2.0},
    ))
    first._runtime_state.current_step = 1
    first.set_ai_prediction_store(store)
    first._record_round("pc28", "1008", [BetDecision(True, "大", 20, "g1", "test")])

    restarted = AutoBetService()
    restarted.apply_config(StrategyConfig(strategy_type="flat", site="pc28", odds={"大": 1.0}))
    restarted.set_ai_prediction_store(store)
    restarted.start()

    assert restarted.runtime_state.pending_staked == 20
    assert restarted.runtime_state.current_step == 1
    assert restarted.settle_pending_rounds(Provider(by_period={"1008": DrawResult("1008", "pc28", "大单")})) == 1
    assert restarted.runtime_state.total_payout == 40
    assert restarted.runtime_state.total_profit == 20
    assert restarted.runtime_state.current_step == 0


def test_restart_restores_the_next_martingale_step_after_a_losing_round(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    first = AutoBetService()
    first.apply_config(StrategyConfig(
        strategy_type="martingale", site="pc28", martingale_sequence=[10, 20], odds={"大": 2.0},
    ))
    first.set_ai_prediction_store(store)
    first._record_round("pc28", "1009", [BetDecision(True, "大", 10, "g1", "test")])

    restarted = AutoBetService()
    restarted.apply_config(StrategyConfig(
        strategy_type="martingale", site="pc28", martingale_sequence=[10, 20], odds={"大": 2.0},
    ))
    restarted.set_ai_prediction_store(store)
    restarted.start()

    assert restarted.settle_pending_rounds(Provider(by_period={"1009": DrawResult("1009", "pc28", "小单")})) == 1
    assert restarted.runtime_state.current_step == 1


def test_martingale_runtime_tracks_the_highest_actual_amount_with_context():
    service = AutoBetService()
    service.apply_config(StrategyConfig(
        strategy_type="martingale", site="pc28", martingale_sequence=[10, 20, 40],
    ))
    service._runtime_state.current_step = 2

    service._record_round("pc28", "1010", [BetDecision(True, "大", 40, "g1", "test")])

    state = service.runtime_state
    assert state.martingale_peak_step == 2
    assert state.martingale_peak_amount == 40
    assert state.martingale_peak_site == "pc28"
    assert state.martingale_peak_period == "1010"
    assert state.martingale_peak_at is not None


def test_non_martingale_round_does_not_record_a_martingale_peak():
    service = AutoBetService()
    service.apply_config(StrategyConfig(strategy_type="flat", site="pc28"))

    service._record_round("pc28", "1011", [BetDecision(True, "大", 100, "g1", "test")])

    state = service.runtime_state
    assert state.martingale_peak_amount == 0
    assert state.martingale_peak_period == ""


def test_inject_log_records_site_period_and_group_name_when_available():
    svc = AutoBetService()
    sender = Sender()
    svc.set_injector(sender)
    svc.set_group_names({"g1": "???"})

    svc._execute(BetDecision(True, "?", 100, "g1", "test"), sender, site="pc28", period="20260705001")

    record = [r for r in svc.get_logs() if r.play_type][-1]
    assert record.group_name == "???"
    assert record.site == "pc28"
    assert record.period == "20260705001"
    assert record.content == "?100"



class TextSender:
    def __init__(self):
        self.sent_text = []

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        raise AssertionError("combined betting should use inject_text")

    def inject_text(self, target_id: str, text: str, *, is_group: bool = True) -> bool:
        self.sent_text.append((target_id, text, is_group))
        return True


def test_tick_combines_multiple_play_types_into_one_message_per_group():
    svc = AutoBetService()
    sender = TextSender()
    svc.set_group_names({"g1": "一群", "g2": "一群"})

    for group_id in ("g1", "g2"):
        svc._execute_group(
            group_id,
            [
                BetDecision(True, "大", 100.0, group_id, "test"),
                BetDecision(True, "小", 100.0, group_id, "test"),
            ],
            sender,
            site="pc28",
            period="20260705001",
        )

    assert sender.sent_text == [
        ("g1", "大100小100", True),
        ("g2", "大100小100", True),
    ]
    records = [r for r in svc.get_logs() if r.group_id in {"g1", "g2"}]
    assert [(r.group_name, r.content) for r in records] == [("一群", "大100小100"), ("一群", "大100小100")]



class AiClient:
    def __init__(
        self,
        play_type: str = "\u5927",
        reason: str = "\u6d4b\u8bd5\u5efa\u8bae",
        *,
        action: str = "bet",
        confidence: int = 80,
    ) -> None:
        self.play_type = play_type
        self.reason = reason
        self.action = action
        self.confidence = confidence
        self.calls = []

    def recommend(self, config, results, quant_context=None, performance_context=None, retry_notifier=None):
        from app.models.auto_bet import AiRecommendation

        self.calls.append((config.site, list(results), quant_context, performance_context))
        return AiRecommendation(
            action=self.action,
            play_type=self.play_type,
            confidence=self.confidence,
            quant_rationale="测试量化依据",
            reason=self.reason,
        )


class RetryingAiClient(AiClient):
    def recommend(self, config, results, quant_context=None, performance_context=None, retry_notifier=None):
        if retry_notifier is not None:
            retry_notifier(1, 2, "<urlopen error simulated TLS EOF>")
        return super().recommend(config, results, quant_context, performance_context, retry_notifier)


def _wait_until(condition, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _started_ai_service(*, require_confirmation: bool, confidence_threshold: int = 45):
    service = AutoBetService()
    sender = Sender()
    client = AiClient()
    service.apply_config(StrategyConfig(
        strategy_type="ai",
        site="pc28",
        target_groups=["g1", "g2"],
        bet_amount=100,
        ai_history_count=50,
        ai_require_confirmation=require_confirmation,
        ai_confidence_threshold=confidence_threshold,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "\u5927\u5355")]))
    service.set_ai_client(client)
    service.start()
    return service, sender, client


def _ai_tick(service, *, countdown: int = 120, now: datetime | None = None):
    current = now or datetime(2026, 7, 10, 12, 1)
    service.tick(
        "pc28",
        countdown,
        "1001",
        period_start_time=datetime(2026, 7, 10, 12, 0),
        period_end_time=datetime(2026, 7, 10, 12, 3),
        now=current,
    )


def test_ai_strategy_generates_one_pending_suggestion_per_site_period():
    service, _sender, client = _started_ai_service(require_confirmation=True)

    _ai_tick(service)
    assert _wait_until(lambda: service.pending_ai_recommendation("pc28", "1001") is not None)
    _ai_tick(service)

    assert len(client.calls) == 1
    pending = service.pending_ai_recommendation("pc28", "1001")
    assert pending.play_type == "\u5927"
    assert pending.amount == 100
    assert pending.reason == "\u6d4b\u8bd5\u5efa\u8bae"


def test_confirming_ai_suggestion_sends_same_bet_to_every_target_group():
    service, sender, _client = _started_ai_service(require_confirmation=True)

    _ai_tick(service)
    assert _wait_until(lambda: service.pending_ai_recommendation("pc28", "1001") is not None)

    assert service.confirm_ai_bet("pc28", "1001", within_bet_window=True) is True
    assert sender.sent == [("g1", "\u5927", 100.0), ("g2", "\u5927", 100.0)]
    assert service.pending_ai_recommendation("pc28", "1001") is None


def test_skipping_ai_suggestion_keeps_the_period_from_sending():
    service, sender, _client = _started_ai_service(require_confirmation=True)

    _ai_tick(service)
    assert _wait_until(lambda: service.pending_ai_recommendation("pc28", "1001") is not None)

    assert service.skip_ai_bet("pc28", "1001") is True
    assert sender.sent == []
    assert service.pending_ai_recommendation("pc28", "1001") is None


def test_ai_confirmation_timeout_skips_without_sending():
    service, sender, _client = _started_ai_service(require_confirmation=True)

    _ai_tick(service)
    assert _wait_until(lambda: service.pending_ai_recommendation("pc28", "1001") is not None)
    _ai_tick(service, countdown=10, now=datetime(2026, 7, 10, 12, 2, 31))

    assert sender.sent == []
    assert service.pending_ai_recommendation("pc28", "1001") is None


def test_ai_strategy_auto_sends_after_one_valid_suggestion_when_confirmation_is_disabled():
    service, sender, client = _started_ai_service(require_confirmation=False)

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 2)
    assert sender.sent == [("g1", "\u5927", 100.0), ("g2", "\u5927", 100.0)]
    assert len(client.calls) == 1


def test_ai_network_retry_is_shown_in_the_auto_bet_log():
    service, sender, _client = _started_ai_service(require_confirmation=False)
    service.set_ai_client(RetryingAiClient())

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 2)
    retry_log = next(record for record in service.get_logs() if "AI 请求重试（第 1/2 次）" in record.content)
    assert retry_log.site == "pc28"
    assert retry_log.period == "1001"
    assert "TLS EOF" in retry_log.content


def test_ai_strategy_does_not_repeat_a_group_already_bet_by_another_strategy():
    service, sender, _client = _started_ai_service(require_confirmation=False)
    service._bet_keys.add(("pc28", "1001", "g1"))

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 1)
    assert sender.sent == [("g2", "\u5927", 100.0)]


def test_ai_never_sends_a_play_outside_the_selected_mode_and_allowed_plays():
    svc = AutoBetService()
    sender = Sender()
    svc.apply_config(StrategyConfig(
        strategy_type="flat",
        site="pc28",
        bet_mode="parity",
        play_types=["单", "双"],
        target_groups=["g1"],
        ai_history_count=50,
        ai_confidence_threshold=45,
    ))
    svc.set_injector(sender)
    svc.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小双")]))
    svc.set_ai_client(AiClient(play_type="大单", confidence=80))
    svc.start()

    _ai_tick(svc)

    assert _wait_until(lambda: any("不在当前允许玩法" in record.content for record in svc.get_logs()))
    assert sender.sent == []


def test_ai_status_log_includes_site_period_and_target_group_names():
    service, sender, _client = _started_ai_service(require_confirmation=False)
    service.set_group_names({"g1": "\u7fa4A", "g2": "\u7fa4B"})

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 2)
    log = [record for record in service.get_logs() if record.content.startswith("AI \u81ea\u52a8\u4e0b\u6ce8")][-1]
    assert log.site == "pc28"
    assert log.period == "1001"
    assert log.group_name == "\u7fa4A, \u7fa4B"


def test_ai_period_refreshes_history_settles_previous_prediction_and_passes_feedback(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    class RefreshingProvider(Provider):
        def __init__(self):
            super().__init__(
                recent=[DrawResult("1000", "pc28", "大单")],
                by_period={"999": DrawResult("999", "pc28", "大双")},
            )
            self.refresh_calls = []

        def refresh_recent_results(self, site: str, count: int):
            self.refresh_calls.append((site, count))
            return 1

    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    store.record_prediction(
        site="pc28", period="999", action="bet", play_type="大", confidence=80,
        quant_rationale="test", reason="test", model="model", sent=True, status="sent",
    )
    service = AutoBetService()
    sender = Sender()
    client = AiClient()
    provider = RefreshingProvider()
    service.apply_config(StrategyConfig(
        strategy_type="ai", site="pc28", target_groups=["g1"], ai_history_count=50,
        ai_accuracy_window=20,
    ))
    service.set_injector(sender)
    service.set_result_provider(provider)
    service.set_ai_client(client)
    service.set_ai_prediction_store(store)
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: len(client.calls) == 1)
    assert provider.refresh_calls == [("pc28", 51)]
    _site, _history, quant_context, performance_context = client.calls[0]
    assert quant_context["sample_size"] == 1
    assert performance_context["overall"]["direction_accuracy"] == 1.0
    assert set(performance_context) == {"overall", "short", "recent_predictions"}


def test_each_betting_window_refreshes_history_before_trend_eligibility():
    class RefreshingProvider(Provider):
        def __init__(self):
            super().__init__(recent=[
                DrawResult("998", "pc28", "小单"),
                DrawResult("999", "pc28", "小单"),
                DrawResult("1000", "pc28", "小单"),
            ])
            self.refresh_calls = []

        def refresh_recent_results(self, site: str, count: int):
            self.refresh_calls.append((site, count))
            return 1

    service = AutoBetService()
    sender = Sender()
    provider = RefreshingProvider()
    service.apply_config(StrategyConfig(
        strategy_type="trend_following", site="pc28", target_groups=["g1"],
        observation_window=3, trigger_threshold=3, ai_history_count=50,
    ))
    service.set_injector(sender)
    service.set_result_provider(provider)
    service.set_ai_client(AiClient())
    service.start()

    _ai_tick(service)

    assert provider.refresh_calls == [("pc28", 51)]


def test_ai_history_excludes_the_target_period_and_future_periods():
    service = AutoBetService()
    sender = Sender()
    client = AiClient(play_type="大")
    provider = Provider(recent=[
        DrawResult("998", "pc28", "小单"),
        DrawResult("999", "pc28", "大双"),
        DrawResult("1000", "pc28", "小双"),
        DrawResult("1001", "pc28", "大单"),
        DrawResult("1002", "pc28", "小单"),
    ])
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"], ai_history_count=50,
    ))
    service.set_injector(sender)
    service.set_result_provider(provider)
    service.set_ai_client(client)
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: len(client.calls) == 1)
    assert [result.period for result in client.calls[0][1]] == ["998", "999", "1000"]
    assert client.calls[0][2]["sample_size"] == 3
    assert any("已排除 2 条" in record.content for record in service.get_logs())


def test_ai_prediction_settlement_rejects_a_mismatched_site_or_period(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    store.record_prediction(
        site="pc28", period="999", action="bet", play_type="大", confidence=80,
        quant_rationale="test", reason="test", model="model", sent=True, status="sent",
    )
    service = AutoBetService()
    provider = Provider(by_period={"999": DrawResult("998", "macao", "大单")})

    service.set_ai_prediction_store(store)

    assert service._settle_ai_predictions(provider, "pc28") == 0
    assert store.recent_records("pc28", 1)[0].actual_result == ""
    assert any("AI 预测结算等待" in record.content for record in service.get_logs())


def test_ai_low_confidence_is_persisted_and_skipped_without_sending(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    service, sender, _client = _started_ai_service(require_confirmation=False, confidence_threshold=65)
    client = AiClient(confidence=64)
    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    service.set_ai_client(client)
    service.set_ai_prediction_store(store)

    _ai_tick(service)

    assert _wait_until(lambda: bool(store.recent_records("pc28", 1)))
    assert sender.sent == []
    record = store.recent_records("pc28", 1)[0]
    assert record.status == "low_confidence"
    assert record.sent is False


def test_ai_explicit_skip_is_persisted_without_sending(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    service, sender, _client = _started_ai_service(require_confirmation=False)
    client = AiClient(play_type="", action="skip", confidence=35)
    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    service.set_ai_client(client)
    service.set_ai_prediction_store(store)

    _ai_tick(service)

    assert _wait_until(lambda: bool(store.recent_records("pc28", 1)))
    assert sender.sent == []
    assert store.recent_records("pc28", 1)[0].status == "ai_skip"


def test_ai_failed_send_is_not_marked_as_sent(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    class FailingSender(Sender):
        def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
            return False

    service = AutoBetService()
    store = AiPredictionStore(tmp_path / "ai_predictions.db")
    service.apply_config(StrategyConfig(
        strategy_type="ai", site="pc28", target_groups=["g1"], ai_history_count=50,
        ai_require_confirmation=False,
    ))
    service.set_injector(FailingSender())
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "大单")]))
    service.set_ai_client(AiClient())
    service.set_ai_prediction_store(store)
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: bool(store.recent_records("pc28", 1)))
    record = store.recent_records("pc28", 1)[0]
    assert record.sent is False
    assert record.status == "send_failed"


def test_ai_callback_does_not_send_after_service_stops(tmp_path):
    from concurrent.futures import Future
    from app.models.auto_bet import AiRecommendation
    from app.services.ai_prediction_store import AiPredictionStore

    service, sender, _client = _started_ai_service(require_confirmation=False)
    service.set_ai_prediction_store(AiPredictionStore(tmp_path / "ai_predictions.db"))
    service.stop()
    future = Future()
    future.set_result(AiRecommendation(
        action="bet", play_type="大", confidence=80,
        quant_rationale="测试依据", reason="测试建议",
    ))

    service._handle_ai_recommendation(
        "pc28", "1001", service.config, sender, future,
        [{"period": "1", "result": "大单"}], {"sample_size": 1},
    )

    assert sender.sent == []


def test_ai_refresh_failure_uses_cache_and_logs_data_freshness(tmp_path):
    from app.services.ai_prediction_store import AiPredictionStore

    class StaleProvider(Provider):
        def refresh_recent_results(self, site: str, count: int):
            return 0

    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="ai", site="pc28", target_groups=["g1"], ai_history_count=50,
    ))
    service.set_injector(sender)
    service.set_result_provider(StaleProvider(recent=[DrawResult("1", "pc28", "大单")]))
    service.set_ai_client(AiClient())
    service.set_ai_prediction_store(AiPredictionStore(tmp_path / "ai_predictions.db"))
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 1)
    assert any("本地缓存" in record.content for record in service.get_logs())


def test_ai_strategy_logs_its_current_period_when_waiting_for_bet_window():
    service, _sender, client = _started_ai_service(require_confirmation=False)
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1", "g2"], bet_amount=100,
    ))

    _ai_tick(service, now=datetime(2026, 7, 10, 12, 0, 10))

    assert client.calls == []
    records = [record for record in service.get_logs() if "AI 等待下注时窗" in record.content]
    assert len(records) == 1
    assert records[0].site == "pc28"
    assert records[0].period == "1001"


def test_flat_strategy_uses_ai_play_with_the_fixed_amount():
    service = AutoBetService()
    sender = Sender()
    client = AiClient(play_type="小")
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"], bet_amount=88,
        play_types=["小", "双"],
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "大单")]))
    service.set_ai_client(client)
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: sender.sent == [("g1", "小", 88.0)])
    assert any("AI 正在分析" in record.content for record in service.get_logs())


def test_flat_strategy_ignores_a_saved_martingale_sequence_for_its_amount():
    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"], bet_amount=88,
        martingale_sequence=[100, 200], play_types=["小", "双"],
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "大单")]))
    service.set_ai_client(AiClient(play_type="小"))
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: sender.sent == [("g1", "小", 88.0)])


def test_martingale_strategy_uses_ai_play_with_the_current_sequence_amount():
    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="martingale", site="pc28", target_groups=["g1"],
        martingale_sequence=[100, 200],
    ))
    service._runtime_state.current_step = 1
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "大单")]))
    service.set_ai_client(AiClient(play_type="大"))
    service.start()
    service._runtime_state.current_step = 1

    _ai_tick(service)

    assert _wait_until(lambda: sender.sent == [("g1", "大", 200.0)])


def test_trend_strategy_only_calls_ai_after_the_configured_streak_trigger():
    service = AutoBetService()
    sender = Sender()
    client = AiClient()
    service.apply_config(StrategyConfig(
        strategy_type="trend_following", site="pc28", target_groups=["g1"],
        observation_window=3, trigger_threshold=3,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[
        DrawResult("1", "pc28", "大单"),
        DrawResult("2", "pc28", "小双"),
        DrawResult("3", "pc28", "大单"),
    ]))
    service.set_ai_client(client)
    service.start()

    _ai_tick(service)

    assert client.calls == []
    assert sender.sent == []
    assert any("趋势条件未满足" in record.content for record in service.get_logs())


def test_exactly_selected_ai_play_sends_without_confirmation():
    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"],
        play_types=["大", "单"], ai_require_confirmation=False,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小双")]))
    service.set_ai_client(AiClient(play_type="大"))
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: sender.sent == [("g1", "大", 10.0)])


def test_ai_play_outside_the_selected_plays_is_rejected_without_a_confirmation_panel():
    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"],
        play_types=["小"], ai_require_confirmation=False,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小双")]))
    service.set_ai_client(AiClient(play_type="大单"))
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: any("不在当前允许玩法" in record.content for record in service.get_logs()))
    assert service.pending_ai_recommendation("pc28", "1001") is None
    assert sender.sent == []


def test_ai_preference_cannot_override_the_strict_selected_play_constraint():
    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"],
        play_types=["小"], ai_prefer_recommendation_on_conflict=True,
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小双")]))
    service.set_ai_client(AiClient(play_type="大单"))
    service.start()

    _ai_tick(service)

    assert _wait_until(lambda: any("不在当前允许玩法" in record.content for record in service.get_logs()))
    assert sender.sent == []


def test_take_profit_halts_after_a_settled_winning_round():
    service = AutoBetService()
    service.apply_config(StrategyConfig(
        site="pc28", take_profit_limit=90, odds={"大": 2.0},
    ))
    service._record_round("pc28", "1001", [BetDecision(True, "大", 100, "g1", "test")])

    assert service.settle_pending_rounds(Provider(by_period={"1001": DrawResult("1001", "pc28", "大单")})) == 1

    state = service.runtime_state
    assert state.halted is True
    assert state.halt_reason == "已触发止盈线 90.00，当前净盈亏 100.00"


def test_stop_loss_halts_after_a_settled_losing_round():
    service = AutoBetService()
    service.apply_config(StrategyConfig(site="pc28", stop_loss_limit=100, odds={"大": 2.0}))
    service._record_round("pc28", "1001", [BetDecision(True, "大", 100, "g1", "test")])

    service.settle_pending_rounds(Provider(by_period={"1001": DrawResult("1001", "pc28", "小双")}))

    state = service.runtime_state
    assert state.halted is True
    assert state.halt_reason == "已触发止损线 100.00，当前净盈亏 -100.00"


def test_mandatory_ai_mode_does_not_fall_back_to_manual_bets_when_unconfigured():
    service = AutoBetService()
    sender = Sender()
    service.apply_config(StrategyConfig(
        strategy_type="flat", site="pc28", target_groups=["g1"], play_types=["大"],
    ))
    service.set_injector(sender)
    service.set_result_provider(Provider(recent=[DrawResult("1", "pc28", "小单")]))
    service.start()

    _ai_tick(service)

    assert sender.sent == []
    assert any("客户端未配置" in record.content for record in service.get_logs())
