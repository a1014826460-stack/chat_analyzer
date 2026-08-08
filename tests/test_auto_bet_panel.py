from __future__ import annotations


def test_auto_bet_requires_server_mode():
    from app.ui.auto_bet_panel import _auto_bet_available

    assert _auto_bet_available(server_mode_enabled=True, logged_in=True) is True
    assert _auto_bet_available(server_mode_enabled=False, logged_in=True) is False
    assert _auto_bet_available(server_mode_enabled=True, logged_in=False) is False


def test_strategy_payload_multi_type():
    from app.ui.auto_bet_panel import _strategy_payload

    payload = _strategy_payload(
        strategy_type="martingale", play_types=["大", "小"],
        observation_window=10, trigger_threshold=3, martingale_sequence=[10, 20, 40],
    )
    assert payload["strategy_type"] == "martingale"
    assert payload["play_types"] == ["大", "小"]
    assert payload["martingale_sequence"] == [10, 20, 40]


def test_beijing_time_conversion():
    from datetime import datetime
    from app.ui.auto_bet_panel import _beijing_time

    utc = datetime(2026, 8, 8, 6, 30, 0)  # 服务器 UTC
    assert _beijing_time(utc) == datetime(2026, 8, 8, 14, 30, 0)


def test_format_order_event_with_result():
    from app.ui.auto_bet_panel import _format_order_event

    line = _format_order_event({
        "period": "3467000", "play_type": "小单", "amount": 10,
        "strategy_type": "three_doors", "result": "win", "result_detail": "exact_hit",
    })
    assert "小单" in line and "three_doors" in line and "exact_hit" in line
