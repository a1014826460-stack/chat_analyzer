from __future__ import annotations

from datetime import datetime


def test_current_period_adapter_returns_pc28_dashboard_next_period_and_betting_deadline(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr(
        "server_api.workers.current_period._fetch_payload",
        lambda _site: {
            "countdown": 42,
            "recent_records": [
                {"draw_number": 3462279, "draw_date": "2026-07-27T22:49:00+08:00"}
            ],
        },
    )

    current = fetch_current_period("pc28")

    assert current.period == "3462280"
    assert current.betting_deadline_at is not None
    assert int((current.betting_deadline_at - datetime.now()).total_seconds()) in range(40, 43)


def test_current_period_adapter_returns_none_when_source_has_no_next_period(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr("server_api.workers.current_period._fetch_payload", lambda _site: {"issue": []})

    assert fetch_current_period("pc28") is None


def test_current_period_adapter_uses_pc28_dashboard_countdown_object_next_draw_number(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr(
        "server_api.workers.current_period._fetch_payload",
        lambda _site: {
            "recent_records": [
                {"draw_number": 3463029, "draw_date": "2026-07-29T19:40:00+08:00"}
            ],
            "countdown": {
                "countdown_seconds": 128,
                "next_draw_number": 3463030,
                "estimated_timestamp": 1785325405000,
            },
        },
    )

    current = fetch_current_period("pc28")

    assert current.period == "3463030"
    assert current.betting_deadline_at is not None
    assert int((current.betting_deadline_at - datetime.now()).total_seconds()) in range(126, 129)
