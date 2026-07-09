from __future__ import annotations

from app.models.auto_bet import AutoBetRuntimeState, BetDecision, DrawResult, StrategyConfig
from app.services.auto_bet_service import AutoBetService
from datetime import datetime


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


def test_three_doors_analyze_bets_selected_three_doors_with_current_step_amount():
    svc = AutoBetService()
    cfg = StrategyConfig(
        site="pc28",
        bet_mode="three_doors",
        play_types=["小单", "大双", "小双"],
        martingale_sequence=[100, 200, 400],
        target_groups=["207191791"],
    )
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 1

    decisions = svc._analyze_many(cfg, Provider())

    assert decisions == [
        BetDecision(True, "小单", 200.0, "207191791", "三门下注"),
        BetDecision(True, "大双", 200.0, "207191791", "三门下注"),
        BetDecision(True, "小双", 200.0, "207191791", "三门下注"),
    ]


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


def test_settle_losing_last_martingale_step_halts_until_manual_reset():
    svc = AutoBetService()
    cfg = StrategyConfig(site="pc28", martingale_sequence=[100, 200], odds={"小单": 3.68})
    svc.apply_config(cfg)
    svc._runtime_state.current_step = 1
    svc._record_round("pc28", "1002", [BetDecision(True, "小单", 200, "207191791", "test")])

    settled = svc.settle_pending_rounds(Provider(by_period={"1002": DrawResult("1002", "pc28", "大单")}))
    state = svc.runtime_state

    assert settled == 1
    assert state.current_step == 1
    assert state.total_staked == 200
    assert state.total_payout == 0
    assert state.total_profit == -200
    assert state.lose_rounds == 1
    assert state.consecutive_losses == 1
    assert state.halted is True
    assert "最后一档" in state.halt_reason


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
        site="pc28",
        bet_mode="three_doors",
        play_types=["小单", "大双", "小双"],
        target_groups=["207191791"],
    ))
    svc.set_injector(sender)
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

    assert sender.sent == [
        ("207191791", "小单", 10.0),
        ("207191791", "大双", 10.0),
        ("207191791", "小双", 10.0),
    ]


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
