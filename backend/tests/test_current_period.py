from __future__ import annotations

from datetime import datetime


def test_current_period_adapter_returns_official_next_period_and_betting_deadline(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr(
        "server_api.workers.current_period._fetch_payload",
        lambda _site: {"issue": [{"qishu": "20260726001", "next": "1785012300000"}]},
    )

    current = fetch_current_period("pc28")

    assert current.period == "20260726002"
    assert current.betting_deadline_at == datetime.fromtimestamp(1785012300)


def test_current_period_adapter_returns_none_when_source_has_no_next_period(monkeypatch):
    from server_api.workers.current_period import fetch_current_period

    monkeypatch.setattr("server_api.workers.current_period._fetch_payload", lambda _site: {"issue": []})

    assert fetch_current_period("pc28") is None
