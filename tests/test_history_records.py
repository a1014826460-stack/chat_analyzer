from __future__ import annotations

from datetime import datetime

from app.utils.history_records import apply_saved_proxy_settings, parse_australia_history_html, parse_history_records


def test_parse_pc28_history_skips_unopened_rows_and_normalizes_records():
    payload = {
        "data": [
            {"qishu": "3452648", "kjcode": "---", "kjcodestr": "---"},
            {"qishu": "3452647", "kjcode": "15", "kjcodestr": "3+5+7=15"},
        ]
    }

    records = parse_history_records("pc28", payload)

    assert records == [
        {
            "site": "pc28",
            "period": "3452647",
            "open_time": None,
            "numbers": [3, 5, 7],
            "sum": 15,
            "raw": {"qishu": "3452647", "kjcode": "15", "kjcodestr": "3+5+7=15"},
        }
    ]


def test_parse_macao_history_normalizes_draw_list():
    payload = {
        "data": {
            "drawList": [
                {
                    "qihao": "1050636",
                    "opentime": "2026-07-03 23:45:00",
                    "opennum": "4+4+3",
                    "sum": 11,
                    "number": "4+4+3=11",
                }
            ]
        }
    }

    records = parse_history_records("macao", payload)

    assert records[0]["site"] == "macao"
    assert records[0]["period"] == "1050636"
    assert records[0]["open_time"] == datetime(2026, 7, 3, 23, 45, 0)
    assert records[0]["numbers"] == [4, 4, 3]
    assert records[0]["sum"] == 11
    assert records[0]["raw"] is payload["data"]["drawList"][0]


def test_parse_norway_history_reads_result_json_and_draw_time():
    raw = {
        "PeriodNo": "260703407",
        "DrawTime": 1783093470,
        "ResultJSON": '{"result": [1, 2, 8]}',
        "ExtResult": '{"sum": 11}',
    }
    payload = {"result": [raw]}

    records = parse_history_records("norway", payload)

    assert records[0]["site"] == "norway"
    assert records[0]["period"] == "260703407"
    assert records[0]["open_time"] == datetime.fromtimestamp(1783093470)
    assert records[0]["numbers"] == [1, 2, 8]
    assert records[0]["sum"] == 11
    assert records[0]["raw"] is raw


def test_parse_australia_history_html_extracts_table_rows():
    html = """
    <table>
      <thead><tr><th>期数</th><th>时间</th><th>结果</th></tr></thead>
      <tbody>
        <tr><td>202607030319</td><td>07-03 23:47:00</td><td>7+2+4=13</td></tr>
        <tr><td>202607030318</td><td>07-03 23:44:00</td><td>3+4+3=10</td></tr>
      </tbody>
    </table>
    """

    records = parse_australia_history_html(html)

    assert records[0]["site"] == "australia"
    assert records[0]["period"] == "202607030319"
    assert records[0]["open_time"] == datetime(datetime.now().year, 7, 3, 23, 47, 0)
    assert records[0]["numbers"] == [7, 2, 4]
    assert records[0]["sum"] == 13
    assert records[0]["raw"] == {
        "period": "202607030319",
        "open_time": "07-03 23:47:00",
        "result": "7+2+4=13",
    }
    assert records[1]["numbers"] == [3, 4, 3]
    assert records[1]["sum"] == 10


def test_parse_australia_history_html_ignores_non_draw_tables():
    html = """
    <table><tr><td>广告</td><td>不是时间</td><td>不是结果</td></tr></table>
    <table><tr><td>202607030317</td><td>07-03 23:41:00</td><td>4+2+3=9</td></tr></table>
    """

    records = parse_history_records("australia", html)

    assert len(records) == 1
    assert records[0]["period"] == "202607030317"
    assert records[0]["numbers"] == [4, 2, 3]
    assert records[0]["sum"] == 9


def test_history_records_applies_the_saved_application_proxy(monkeypatch):
    captured = {}

    class SettingsService:
        def load(self):
            return {
                "proxy_enabled": True,
                "proxy_http": "http://127.0.0.1:7890",
                "proxy_https": "http://127.0.0.1:7891",
            }

    monkeypatch.setattr("app.services.settings_service.SettingsService", SettingsService)
    monkeypatch.setattr(
        "app.utils.fetch_date.set_proxy_settings",
        lambda settings: captured.update(settings),
    )

    apply_saved_proxy_settings()

    assert captured == {
        "proxy_enabled": True,
        "proxy_http": "http://127.0.0.1:7890",
        "proxy_https": "http://127.0.0.1:7891",
    }
