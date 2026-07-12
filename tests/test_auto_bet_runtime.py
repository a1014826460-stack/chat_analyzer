from __future__ import annotations

from app.models.auto_bet import AutoBetRuntimeState, BetDecision, DrawResult, StrategyConfig
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


def test_strategy_config_persists_martingale_strategy_type():
    cfg = StrategyConfig(strategy_type="martingale", bet_mode="size", play_types=["\u5927"], martingale_sequence=[100, 200])

    loaded = StrategyConfig.from_dict(cfg.to_dict())

    assert loaded.strategy_type == "martingale"
    assert loaded.bet_mode == "size"
    assert loaded.play_types == ["\u5927"]
    assert loaded.martingale_sequence == [100.0, 200.0]


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


def test_tick_deduplicates_by_site_period_and_group_not_period_only():
    svc = AutoBetService()
    sender = Sender()
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        bet_mode="size",
        play_types=["?"],
        target_groups=["g1", "g2"],
        martingale_sequence=[100],
    )
    svc.apply_config(cfg)
    svc.set_injector(sender)
    svc.start()

    kwargs = dict(
        countdown_sec=120,
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 1, 0),
    )
    svc.tick("pc28", current_period="20260705001", **kwargs)
    svc.tick("pc28", current_period="20260705001", **kwargs)

    assert sender.sent == [("g1", "?", 100.0), ("g2", "?", 100.0)]


def test_inject_log_records_site_period_and_group_name_when_available():
    svc = AutoBetService()
    sender = Sender()
    svc.set_injector(sender)
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        bet_mode="size",
        play_types=["?"],
        target_groups=["g1"],
        martingale_sequence=[100],
    )
    svc.apply_config(cfg)
    svc.set_group_names({"g1": "???"})
    svc.start()

    svc.tick(
        "pc28",
        120,
        "20260705001",
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 1, 0),
    )

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
    cfg = StrategyConfig(
        strategy_type="martingale",
        site="pc28",
        bet_mode="size",
        play_types=["\u5927", "\u5c0f"],
        target_groups=["g1", "g2"],
        martingale_sequence=[100],
    )
    svc.apply_config(cfg)
    svc.set_group_names({"g1": "\u4e00\u7fa4", "g2": "\u4e00\u7fa4"})
    svc.set_injector(sender)
    svc.start()

    svc.tick(
        "pc28",
        120,
        "20260705001",
        period_start_time=datetime(2026, 7, 5, 12, 0, 0),
        period_end_time=datetime(2026, 7, 5, 12, 3, 0),
        now=datetime(2026, 7, 5, 12, 1, 0),
    )

    assert sender.sent_text == [
        ("g1", "\u5927100\u5c0f100", True),
        ("g2", "\u5927100\u5c0f100", True),
    ]
    records = [r for r in svc.get_logs() if r.group_id in {"g1", "g2"}]
    assert [(r.group_name, r.content) for r in records] == [("\u4e00\u7fa4", "\u5927100\u5c0f100"), ("\u4e00\u7fa4", "\u5927100\u5c0f100")]


class AiClient:
    def __init__(self, play_type: str = "\u5927", reason: str = "\u6d4b\u8bd5\u5efa\u8bae") -> None:
        self.play_type = play_type
        self.reason = reason
        self.calls = []

    def recommend(self, config, results):
        from app.services.ai_bet_client import AiRecommendation

        self.calls.append((config.site, list(results)))
        return AiRecommendation(play_type=self.play_type, reason=self.reason)


def _wait_until(condition, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _started_ai_service(*, require_confirmation: bool):
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


def test_ai_strategy_does_not_repeat_a_group_already_bet_by_another_strategy():
    service, sender, _client = _started_ai_service(require_confirmation=False)
    service._bet_keys.add(("pc28", "1001", "g1"))

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 1)
    assert sender.sent == [("g2", "\u5927", 100.0)]


def test_ai_status_log_includes_site_period_and_target_group_names():
    service, sender, _client = _started_ai_service(require_confirmation=False)
    service.set_group_names({"g1": "\u7fa4A", "g2": "\u7fa4B"})

    _ai_tick(service)

    assert _wait_until(lambda: len(sender.sent) == 2)
    log = [record for record in service.get_logs() if record.content.startswith("AI \u81ea\u52a8\u4e0b\u6ce8")][-1]
    assert log.site == "pc28"
    assert log.period == "1001"
    assert log.group_name == "\u7fa4A, \u7fa4B"
