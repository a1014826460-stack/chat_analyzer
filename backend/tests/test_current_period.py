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

    assert current.current_period == "3462279"
    assert current.period == "3462280"
    assert current.betting_deadline_at is not None
    assert int((current.betting_deadline_at - datetime.utcnow()).total_seconds()) in range(40, 43)


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

    assert current.current_period == "3463029"
    assert current.period == "3463030"
    assert current.betting_deadline_at is not None
    assert int((current.betting_deadline_at - datetime.utcnow()).total_seconds()) in range(126, 129)


def test_current_period_adapter_derives_macao_deadline_from_latest_open_time(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr(
        "server_api.workers.current_period._fetch_payload",
        lambda _site: {
            "data": {
                "drawList": [
                    {
                        "qihao": "1065638",
                        "opentime": "2026-08-04 05:51:00",
                        "opennum": "8,6,7",
                    }
                ]
            }
        },
    )

    current = fetch_current_period("macao")

    assert current.current_period == "1065638"
    assert current.period == "1065639"
    assert current.betting_deadline_at == datetime(2026, 8, 3, 21, 54, 0)


def test_current_period_adapter_uses_australia_next_countdown_seconds(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr(
        "server_api.workers.current_period._fetch_payload",
        lambda _site: {
            "qi": "202608030440",
            "next": {"qi": 202608030441, "sec": 122},
        },
    )

    current = fetch_current_period("australia")

    assert current.current_period == "202608030440"
    assert current.period == "202608030441"
    assert current.betting_deadline_at is not None
    assert int((current.betting_deadline_at - datetime.utcnow()).total_seconds()) in range(120, 123)


def test_current_period_adapter_uses_norway_next_periods_payload(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr(
        "server_api.workers.current_period._fetch_payload",
        lambda _site: {
            "lottery_data": [
                {
                    "expect": "260804100",
                    "nextexpect": "260804101",
                    "next": "1785794010",
                }
            ],
            "next_periods": {
                "PeriodNo": "260804101",
                "DrawTime": 1785794010,
            },
        },
    )

    current = fetch_current_period("norway")

    assert current.current_period == "260804100"
    assert current.period == "260804101"
    assert current.betting_deadline_at == datetime.utcfromtimestamp(1785794010)
