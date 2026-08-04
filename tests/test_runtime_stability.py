from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


def test_settings_service_debounces_bursts_and_flushes_the_latest_snapshot(tmp_path):
    from app.services.settings_service import SettingsService

    writes: list[dict] = []

    class Store:
        def save(self, payload):
            writes.append(dict(payload))

    service = SettingsService(debounce_seconds=60)
    service.store = Store()

    service.save({"revision": 1})
    service.save({"revision": 2})
    service.save({"revision": 3})

    assert writes == []
    service.flush()
    assert writes == [{"revision": 3}]


def test_settings_service_snapshots_nested_values_before_returning_to_the_ui_thread():
    from app.services.settings_service import SettingsService

    writes: list[dict] = []

    class Store:
        def save(self, payload):
            writes.append(payload)

    service = SettingsService(debounce_seconds=60)
    service.store = Store()
    payload = {"groups": ["before"]}
    service.save(payload)
    payload["groups"].append("after")
    service.flush()

    assert writes == [{"groups": ["before"]}]


def test_raw_chat_history_is_bounded_and_uses_an_incremental_dedupe_index():
    from app.models import ChatMessage
    from app.ui.main_window_actions import MainWindowActionsMixin

    class Window(MainWindowActionsMixin):
        raw_chat_history_limit = 3

    window = Window()
    window.raw_chat_messages = []
    base = datetime(2026, 7, 26, 12, 0)
    messages = [
        ChatMessage(ts=base + timedelta(seconds=index), group="g", username="u", sender_id="id", content=str(index))
        for index in range(5)
    ]

    window._record_raw_chat_messages(messages[:3])
    initial_index = window._raw_chat_message_keys
    window._record_raw_chat_messages(messages[2:])

    assert window._raw_chat_message_keys is initial_index
    assert [message.content for message in window.raw_chat_messages] == ["2", "3", "4"]
    assert len(window._raw_chat_message_keys) == 3


def test_server_pending_poll_is_submitted_to_background_worker_once_until_completed():
    from app.ui.main_window_data import MainWindowDataMixin

    submitted = []

    class Worker:
        def submit(self, callback):
            submitted.append(callback)
            return SimpleNamespace(add_done_callback=lambda _: None)

    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(),
        server_api_client=SimpleNamespace(is_authenticated=True, pending_bets=lambda: []),
        _worker=Worker(),
        _server_pending_poll_in_progress=False,
    )

    MainWindowDataMixin._refresh_server_pending_bet(window)
    MainWindowDataMixin._refresh_server_pending_bet(window)

    assert len(submitted) == 1


def test_server_pending_poll_skips_worker_when_server_session_is_not_authenticated():
    from app.ui.main_window_data import MainWindowDataMixin

    submitted = []

    class Worker:
        def submit(self, callback):
            submitted.append(callback)

    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(),
        server_api_client=SimpleNamespace(is_authenticated=False),
        _worker=Worker(),
        _server_pending_poll_in_progress=False,
    )

    MainWindowDataMixin._refresh_server_pending_bet(window)

    assert submitted == []
    assert window._server_pending_poll_in_progress is False


def test_server_event_poll_appends_each_new_event_once_to_the_run_log():
    from app.ui.main_window_data import MainWindowDataMixin

    appended = []

    class Worker:
        def submit(self, callback):
            return SimpleNamespace(add_done_callback=lambda _: None)

    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(append_log=appended.append),
        server_api_client=SimpleNamespace(is_authenticated=True),
        _worker=Worker(),
        _server_event_poll_in_progress=False,
        _server_event_cursor=0,
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 3, "site": "pc28", "period": "1001", "event_type": "ai_skip", "message": "AI 跳过"},
        {"id": 4, "site": "pc28", "period": "1002", "event_type": "ai_execute", "message": "AI 执行"},
    ]})
    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 4, "site": "pc28", "period": "1002", "event_type": "ai_execute", "message": "AI 执行"},
    ]})

    assert [record.content for record in appended] == ["AI 跳过", "AI 执行"]
    assert window._server_event_cursor == 4


def test_server_strategy_save_is_coalesced_and_never_calls_http_from_the_ui_handler():
    from app.ui.main_window_data import MainWindowDataMixin

    submitted = []
    saved = []

    class Worker:
        def submit(self, callback):
            submitted.append(callback)
            return SimpleNamespace(add_done_callback=lambda _: None)

    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(_group_names={"g1": "测试一群"}),
        _worker=Worker(),
        server_api_client=SimpleNamespace(save_strategy=lambda payload: saved.append(payload)),
        _server_strategy_save_in_progress=False,
        server_strategy_debounce_seconds=60,
    )

    MainWindowDataMixin._schedule_server_strategy_save(window, {"history_count": 50, "target_groups": ["g1"]})
    MainWindowDataMixin._schedule_server_strategy_save(window, {"history_count": 100, "target_groups": ["g1"]})

    assert len(submitted) == 0
    assert saved == []
    MainWindowDataMixin._submit_pending_server_strategy_save(window)
    assert len(submitted) == 1
    submitted[0]()
    assert saved == [{"history_count": 100, "target_groups": ["g1"], "target_group_names": {"g1": "测试一群"}}]


def test_server_auto_bet_stop_persists_disabled_strategy_and_reverts_ui_on_failure():
    from app.models.auto_bet import StrategyConfig
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    panel = SimpleNamespace(
        get_config=lambda: StrategyConfig(
            site="pc28",
            target_groups=["g1"],
            ai_history_count=100,
            ai_confidence_threshold=65,
            ai_require_confirmation=True,
            bet_amount=88,
        ),
        set_running=lambda value: calls.append(("running", value)),
    )
    timer = SimpleNamespace(
        start=lambda: calls.append("timer-start"),
        stop=lambda: calls.append("timer-stop"),
    )
    window = SimpleNamespace(
        auto_bet_panel=panel,
        _auto_bet_timer=timer,
        _schedule_server_strategy_save=lambda payload: calls.append(("save", payload)),
    )

    MainWindowDataMixin._on_auto_bet_stop(window)

    assert calls == [
        ("save", {
            "enabled": False,
            "site": "pc28",
            "target_groups": ["g1"],
            "history_count": 100,
            "confidence_threshold": 65,
            "require_confirmation": True,
            "bet_amount": 88,
        }),
        ("running", False),
        "timer-stop",
    ]
    assert window._server_strategy_stop_pending is True

    MainWindowDataMixin._handle_server_strategy_save_ready(window, {
        "ok": True,
        "payload": {"enabled": True},
    })
    assert window._server_strategy_stop_pending is True

    MainWindowDataMixin._handle_server_strategy_save_ready(window, {
        "error": RuntimeError("offline"),
        "payload": {"enabled": False},
    })

    assert calls[-2:] == [("running", True), "timer-start"]
    assert window._server_strategy_stop_pending is False


def test_local_ai_credentials_are_removed_from_saved_auto_bet_settings():
    from app.ui.main_window_data import MainWindowDataMixin

    saved_snapshots = []
    window = SimpleNamespace(
        settings={
            "auto_bet": {
                "site": "pc28",
                "ai_provider": "anthropic",
                "ai_base_url": "https://ai.example",
                "ai_model": "legacy-model",
                "ai_api_key": "legacy-secret",
                "ai_history_count": 100,
            }
        },
        settings_service=SimpleNamespace(save=lambda value: saved_snapshots.append(value.copy())),
    )

    assert MainWindowDataMixin._remove_local_ai_credentials_from_settings(window) is True
    assert window.settings["auto_bet"] == {"site": "pc28", "ai_history_count": 100}
    assert saved_snapshots == [window.settings]
    assert MainWindowDataMixin._remove_local_ai_credentials_from_settings(window) is False
    assert len(saved_snapshots) == 1


def test_server_confirm_is_submitted_to_a_background_worker_instead_of_blocking_ui():
    from app.ui.main_window_data import MainWindowDataMixin

    submitted = []
    confirmed = []

    class Worker:
        def submit(self, callback):
            submitted.append(callback)
            return SimpleNamespace(add_done_callback=lambda _: None)

    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(server_pending_bet_id=17),
        _worker=Worker(),
        server_api_client=SimpleNamespace(confirm_bet=lambda order_id: confirmed.append(order_id)),
        _server_order_action_in_progress=False,
    )

    MainWindowDataMixin._confirm_server_pending_bet(window)

    assert len(submitted) == 1
    assert confirmed == []


def test_auto_bet_service_shutdown_releases_its_background_executor():
    from app.services.auto_bet_service import AutoBetService

    service = AutoBetService()
    service.shutdown()

    with pytest.raises(RuntimeError):
        service._ai_executor.submit(lambda: None)


def test_stability_simulation_keeps_chat_history_and_settings_writes_bounded():
    from app.models import ChatMessage
    from app.services.settings_service import SettingsService
    from app.ui.main_window_actions import MainWindowActionsMixin

    class Store:
        def __init__(self) -> None:
            self.writes: list[dict] = []

        def save(self, payload) -> None:
            self.writes.append(dict(payload))

    class Window(MainWindowActionsMixin):
        raw_chat_history_limit = 200

    store = Store()
    settings = SettingsService(debounce_seconds=60)
    settings.store = store
    window = Window()
    window.raw_chat_messages = []
    base = datetime(2026, 7, 26, 12, 0)

    for index in range(10_000):
        window._record_raw_chat_messages([
            ChatMessage(
                ts=base + timedelta(seconds=index), group="g", username="u", sender_id="id", content=str(index)
            )
        ])
        settings.save({"revision": index})

    settings.flush()

    assert len(window.raw_chat_messages) == 200
    assert len(window._raw_chat_message_keys) == 200
    assert store.writes == [{"revision": 9_999}]


def test_server_mode_tick_rebootstraps_when_session_token_was_cleared():
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []

    class Client:
        is_authenticated = False

    class Settings:
        enabled = True

    class Window(MainWindowDataMixin):
        server_mode_settings = Settings()
        server_api_client = Client()

        def _bootstrap_server_mode(self):
            calls.append("bootstrap")
            self.server_api_client.is_authenticated = True

        def _refresh_server_pending_bet(self):
            calls.append("pending")

        def _refresh_server_betting_events(self):
            calls.append("events")

    Window()._on_auto_bet_tick()

    assert calls == ["bootstrap", "pending", "events"]


def test_server_event_handler_suppresses_duplicate_strategy_decisions_in_one_payload():
    from app.ui.main_window_data import MainWindowDataMixin

    appended = []
    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(append_log=appended.append),
        _server_event_poll_in_progress=True,
        _server_event_cursor=0,
        _server_event_seen_keys=set(),
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 1, "site": "pc28", "period": "1001", "event_type": "frequency_skip", "message": "频率未达"},
        {"id": 2, "site": "pc28", "period": "1001", "event_type": "frequency_skip", "message": "频率未达"},
        {"id": 3, "site": "pc28", "period": "1001", "event_type": "sent", "message": "WSS 已发送 A"},
        {"id": 4, "site": "pc28", "period": "1001", "event_type": "sent", "message": "WSS 已发送 B"},
    ]})

    assert [record.content for record in appended] == ["频率未达", "WSS 已发送 A", "WSS 已发送 B"]
    assert window._server_event_cursor == 4


def test_starting_server_auto_bet_initializes_event_cursor_to_latest_before_polling():
    from app.ui.main_window_data import MainWindowDataMixin

    records = []
    calls = []

    class Panel:
        def get_config(self):
            from app.models.auto_bet import StrategyConfig
            return StrategyConfig(site="pc28", target_groups=["group"], bet_amount=10)

        def set_running(self, running):
            self.running = running

        def append_log(self, record):
            records.append(record)

    class Client:
        def latest_betting_event_id(self):
            calls.append("latest")
            return 128

    window = SimpleNamespace(
        auto_bet_panel=Panel(),
        server_api_client=Client(),
        _schedule_server_strategy_save=lambda payload: calls.append("save"),
        _refresh_server_pending_bet=lambda: calls.append("pending"),
        _refresh_server_betting_events=lambda: calls.append("events"),
        _auto_bet_timer=SimpleNamespace(start=lambda: calls.append("timer")),
    )

    MainWindowDataMixin._start_server_auto_bet(window)

    assert window._server_event_cursor == 128
    assert calls[:3] == ["latest", "save", "pending"]
    assert "等待本期频率与 AI 决策" in records[0].content


def test_server_event_stale_filter_does_not_hide_events_when_client_draw_context_is_inferred():
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    window = SimpleNamespace(
        _draw_infos={"pc28": SimpleNamespace(next_period="3463038", source="inferred")},
    )

    assert MainWindowDataMixin._server_event_is_stale_for_current_site(window, "pc28", "3463030") is False


def test_server_event_handler_skips_stale_sent_events_older_than_current_draw_context():
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    appended = []
    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(append_log=appended.append),
        _server_event_poll_in_progress=True,
        _server_event_cursor=0,
        _server_event_seen_keys=set(),
        _draw_infos={"pc28": SimpleNamespace(next_period="3463038")},
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 1, "site": "pc28", "period": "3463028", "event_type": "sent", "message": "旧期已发送"},
        {"id": 2, "site": "pc28", "period": "3463038", "event_type": "sent", "message": "当前期已发送"},
    ]})

    assert [record.content for record in appended] == ["当前期已发送"]
    assert window._server_event_cursor == 2


def test_server_event_handler_skips_backfilled_periods_older_than_current_draw_context():
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    appended = []
    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(append_log=appended.append),
        _server_event_poll_in_progress=True,
        _server_event_cursor=0,
        _server_event_seen_keys=set(),
        _draw_infos={"pc28": SimpleNamespace(next_period="3462300")},
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 1, "site": "pc28", "period": "3462211", "event_type": "frequency_skip", "message": "历史频率未达"},
        {"id": 2, "site": "pc28", "period": "3462300", "event_type": "frequency_skip", "message": "当前频率未达"},
    ]})

    assert [record.content for record in appended] == ["当前频率未达"]
    assert window._server_event_cursor == 2


def test_server_mode_tick_refreshes_server_statistics_snapshot():
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=True),
        server_api_client=SimpleNamespace(is_authenticated=True),
        _bootstrap_server_mode=lambda: calls.append("bootstrap"),
        _refresh_server_pending_bet=lambda: calls.append("pending"),
        _refresh_server_betting_events=lambda: calls.append("events"),
        _refresh_server_runtime_logs=lambda now=None: calls.append("logs"),
        _refresh_server_statistics=lambda: calls.append("statistics"),
    )

    MainWindowDataMixin._on_auto_bet_tick(window)

    assert calls == ["pending", "events", "logs", "statistics"]


def test_handle_server_statistics_ready_updates_runtime_and_ai_statistics_cards():
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    panel = SimpleNamespace(
        update_runtime_state=lambda state: calls.append(("runtime", state.total_rounds, state.total_profit)),
        update_ai_statistics=lambda summary: calls.append(("ai", summary["settled_count"])),
    )
    window = SimpleNamespace(
        _server_statistics_poll_in_progress=True,
        auto_bet_panel=panel,
    )

    MainWindowDataMixin._handle_server_statistics_ready(window, {
        "runtime_state": {"total_rounds": 2, "total_profit": 6.8, "win_rounds": 1, "lose_rounds": 1},
        "ai_statistics": {"settled_count": 2, "overall": {}, "short": {}, "streak": {}},
    })

    assert window._server_statistics_poll_in_progress is False
    assert calls == [("runtime", 2, 6.8), ("ai", 2)]


def test_server_mode_tick_refreshes_server_frequency_statistics_and_events():
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=True),
        server_api_client=SimpleNamespace(is_authenticated=True),
        _active_site="pc28",
        _bootstrap_server_mode=lambda: calls.append("bootstrap"),
        _refresh_server_pending_bet=lambda: calls.append("pending"),
        _refresh_server_betting_events=lambda: calls.append("events"),
        _refresh_server_runtime_logs=lambda now=None: calls.append("logs"),
        _refresh_server_statistics=lambda: calls.append("statistics"),
        _refresh_auto_bet_frequency_analysis=lambda site: calls.append(("frequency", site)),
    )

    MainWindowDataMixin._on_auto_bet_tick(window)

    assert calls == ["pending", "events", "logs", "statistics", ("frequency", "pc28")]


def test_handle_server_frequency_ready_updates_probability_cards():
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    panel = SimpleNamespace(update_frequency_analysis=lambda value: calls.append(value))
    window = SimpleNamespace(_server_frequency_poll_in_progress=True, auto_bet_panel=panel)
    payload = {"site": "pc28", "sample_count": 50}

    MainWindowDataMixin._handle_server_frequency_ready(window, payload)

    assert window._server_frequency_poll_in_progress is False
    assert calls == [payload]


def test_server_frequency_poll_uses_current_draw_period_for_dynamic_probability_cards():
    from types import SimpleNamespace
    from app.models.auto_bet import StrategyConfig
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []

    class Worker:
        def submit(self, callback):
            calls.append(callback())
            return SimpleNamespace(add_done_callback=lambda _: None)

    panel = SimpleNamespace(get_config=lambda: StrategyConfig(site="pc28", ai_history_count=50, ai_confidence_threshold=45))
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=True),
        auto_bet_panel=panel,
        server_api_client=SimpleNamespace(
            is_authenticated=True,
            frequency_analysis=lambda *args, **kwargs: calls.append((args, kwargs)) or {},
        ),
        _worker=Worker(),
        _draw_infos={"pc28": SimpleNamespace(next_period="3463001")},
        _server_frequency_poll_in_progress=False,
    )

    MainWindowDataMixin._refresh_auto_bet_frequency_analysis(window, "pc28", force=True)

    assert calls[-2] == (("pc28",), {"history_count": 50, "confidence_threshold": 45, "target_period": "3463001"})


def test_server_mode_ai_history_loads_from_api_without_disabling_the_running_panel():
    from types import SimpleNamespace
    from app.models.auto_bet import StrategyConfig
    from app.ui.main_window_data import MainWindowDataMixin

    shown = []

    class Future:
        def __init__(self, result):
            self._result = result
        def result(self):
            return self._result
        def add_done_callback(self, callback):
            callback(self)

    class Worker:
        def submit(self, callback):
            return Future(callback())

    panel = SimpleNamespace(
        get_config=lambda: StrategyConfig(site="pc28"),
        show_ai_history=shown.append,
    )
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=True),
        auto_bet_panel=panel,
        server_api_client=SimpleNamespace(is_authenticated=True, ai_prediction_history=lambda site, limit: [{"site": site}]),
        _worker=Worker(),
    )

    MainWindowDataMixin._on_show_ai_history(window)

    assert shown == [[{"site": "pc28"}]]


def test_server_event_handler_hides_events_created_before_current_run_start():
    from datetime import datetime
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    appended = []
    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(append_log=appended.append),
        _server_event_poll_in_progress=True,
        _server_event_cursor=0,
        _server_event_seen_keys=set(),
        _server_run_started_at=datetime(2026, 7, 28, 22, 22, 49),
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 1, "site": "pc28", "period": "3462389", "event_type": "sent", "message": "旧期已发送", "created_at": "2026-07-28T22:22:48"},
        {"id": 2, "site": "pc28", "period": "3462600", "event_type": "sent", "message": "本次运行发送", "created_at": "2026-07-28T22:22:50"},
    ]})

    assert [record.content for record in appended] == ["本次运行发送"]
    assert window._server_event_cursor == 2


def test_starting_server_auto_bet_resets_three_statistics_panels():
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    class Panel:
        def get_config(self):
            from app.models.auto_bet import StrategyConfig
            return StrategyConfig(site="pc28", target_groups=["group"], bet_amount=10)
        def set_running(self, running): pass
        def append_log(self, record): pass
        def update_runtime_state(self, state): calls.append(("runtime", state.total_rounds, state.total_profit))
        def update_ai_statistics(self, summary): calls.append(("ai", summary.get("settled_count", 0)))
        def update_frequency_analysis(self, analysis): calls.append(("frequency", analysis))
    window = SimpleNamespace(
        auto_bet_panel=Panel(),
        server_api_client=SimpleNamespace(latest_betting_event_id=lambda **kwargs: 10),
        _schedule_server_strategy_save=lambda payload: None,
        _refresh_server_pending_bet=lambda: None,
        _refresh_server_betting_events=lambda: None,
        _refresh_server_statistics=lambda: None,
        _refresh_auto_bet_frequency_analysis=lambda site: None,
        _auto_bet_timer=SimpleNamespace(start=lambda: None),
    )

    MainWindowDataMixin._start_server_auto_bet(window)

    assert calls[:3] == [("runtime", 0, 0.0), ("ai", 0), ("frequency", None)]
    assert hasattr(window, "_server_run_started_at")


def test_server_event_poll_requests_only_events_since_current_run_start():
    from datetime import datetime
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []

    class Client:
        is_authenticated = True
        def betting_events(self, **kwargs):
            calls.append(kwargs)
            return []

    class Future:
        def __init__(self, result):
            self._result = result
        def result(self):
            return self._result
        def add_done_callback(self, callback):
            pass

    class Worker:
        def submit(self, callback):
            return Future(callback())

    window = SimpleNamespace(
        server_api_client=Client(),
        _worker=Worker(),
        _server_event_poll_in_progress=False,
        _server_event_cursor=12,
        _active_site="pc28",
        _server_run_started_at=datetime(2026, 7, 28, 22, 22, 49),
    )

    MainWindowDataMixin._refresh_server_betting_events(window)

    assert calls == [{"after_id": 12, "site": "pc28", "since": datetime(2026, 7, 28, 22, 22, 49)}]


def test_auto_bet_panel_refresh_interval_switches_from_burst_to_steady_mode():
    from app.ui.main_window_data import MainWindowDataMixin

    start = datetime(2026, 7, 28, 12, 0, 0)
    window = SimpleNamespace()

    MainWindowDataMixin._arm_auto_bet_refresh_burst(window, now=start)

    assert MainWindowDataMixin._auto_bet_panel_refresh_interval_seconds(window, now=start + timedelta(seconds=5)) == 2
    assert MainWindowDataMixin._auto_bet_panel_refresh_interval_seconds(window, now=start + timedelta(seconds=25)) == 10


def test_server_statistics_poll_uses_mixed_refresh_cadence():
    from app.ui.main_window_data import MainWindowDataMixin
    from app.models.auto_bet import StrategyConfig

    submitted = []

    class Worker:
        def submit(self, callback):
            submitted.append(callback)
            return SimpleNamespace(add_done_callback=lambda _: None)

    panel = SimpleNamespace(get_config=lambda: StrategyConfig(site="pc28", ai_accuracy_window=20))
    start = datetime(2026, 7, 28, 12, 0, 0)
    window = SimpleNamespace(
        _worker=Worker(),
        auto_bet_panel=panel,
        server_api_client=SimpleNamespace(is_authenticated=True, betting_statistics=lambda *args, **kwargs: {}),
        _server_statistics_poll_in_progress=False,
    )

    MainWindowDataMixin._arm_auto_bet_refresh_burst(window, now=start)
    MainWindowDataMixin._refresh_server_statistics(window, now=start)
    window._server_statistics_poll_in_progress = False
    MainWindowDataMixin._refresh_server_statistics(window, now=start + timedelta(seconds=1))
    window._server_statistics_poll_in_progress = False
    MainWindowDataMixin._refresh_server_statistics(window, now=start + timedelta(seconds=2))
    window._server_statistics_poll_in_progress = False
    MainWindowDataMixin._refresh_server_statistics(window, now=start + timedelta(seconds=25))
    window._server_statistics_poll_in_progress = False
    MainWindowDataMixin._refresh_server_statistics(window, now=start + timedelta(seconds=30))

    assert len(submitted) == 3


def test_handle_server_statistics_ready_skips_redundant_ui_update_when_snapshot_unchanged():
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    panel = SimpleNamespace(
        update_runtime_state=lambda state: calls.append(("runtime", state.total_rounds, state.total_profit)),
        update_ai_statistics=lambda summary: calls.append(("ai", summary["settled_count"])),
    )
    payload = {
        "runtime_state": {"total_rounds": 2, "total_profit": 6.8, "win_rounds": 1, "lose_rounds": 1},
        "ai_statistics": {"settled_count": 2, "overall": {}, "short": {}, "streak": {}},
    }
    window = SimpleNamespace(
        _server_statistics_poll_in_progress=True,
        auto_bet_panel=panel,
    )

    MainWindowDataMixin._handle_server_statistics_ready(window, payload)
    window._server_statistics_poll_in_progress = True
    MainWindowDataMixin._handle_server_statistics_ready(window, payload)

    assert calls == [("runtime", 2, 6.8), ("ai", 2)]


def test_handle_server_frequency_ready_skips_redundant_ui_update_when_snapshot_unchanged():
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    panel = SimpleNamespace(update_frequency_analysis=lambda value: calls.append(value))
    payload = {"site": "pc28", "sample_count": 50, "selected_plays": ["小单", "大双", "大单"]}
    window = SimpleNamespace(_server_frequency_poll_in_progress=True, auto_bet_panel=panel)

    MainWindowDataMixin._handle_server_frequency_ready(window, payload)
    window._server_frequency_poll_in_progress = True
    MainWindowDataMixin._handle_server_frequency_ready(window, dict(payload))

    assert calls == [payload]


def test_server_event_handler_reenters_high_frequency_refresh_on_key_activity():
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    window = SimpleNamespace(
        auto_bet_panel=SimpleNamespace(append_log=lambda record: calls.append(("log", record.content))),
        _server_event_poll_in_progress=True,
        _server_event_cursor=0,
        _server_event_seen_keys=set(),
        _refresh_server_statistics=lambda force=False: calls.append(("statistics", force)),
        _refresh_auto_bet_frequency_analysis=lambda site, force=False: calls.append(("frequency", site, force)),
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 1, "site": "pc28", "period": "3462600", "event_type": "ai_execute", "message": "AI 执行"},
    ]})

    assert calls == [("log", "AI 执行"), ("statistics", True), ("frequency", "pc28", True)]


def test_server_owned_runtime_log_does_not_duplicate_strategy_event_in_local_log():
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=True),
        auto_bet_panel=SimpleNamespace(append_log=lambda record: calls.append(("log", record.content))),
        _server_event_poll_in_progress=True,
        _server_event_cursor=0,
        _server_event_seen_keys=set(),
        _refresh_server_runtime_logs=lambda force=False: calls.append(("runtime_logs", force)),
        _refresh_server_statistics=lambda force=False: calls.append(("statistics", force)),
        _refresh_auto_bet_frequency_analysis=lambda site, force=False: calls.append(("frequency", site, force)),
    )

    MainWindowDataMixin._handle_server_betting_events_ready(window, {"items": [
        {"id": 1, "site": "pc28", "period": "3462600", "event_type": "ai_execute", "message": "AI 执行"},
    ]})

    assert calls == [("runtime_logs", True), ("statistics", True), ("frequency", "pc28", True)]


@pytest.mark.skip(reason="desktop local auto-bet polling was removed; server polling has separate coverage")
def test_local_auto_bet_tick_uses_mixed_refresh_cadence_for_three_panels():
    from app.ui.main_window_data import MainWindowDataMixin
    from app.models.auto_bet import StrategyConfig, AutoBetRuntimeState

    calls = []
    start = datetime(2026, 7, 28, 12, 0, 0)

    class Service:
        is_running = True
        runtime_state = AutoBetRuntimeState(total_rounds=1)
        config = StrategyConfig(site="pc28", ai_accuracy_window=20)
        _ai_prediction_store = SimpleNamespace(accuracy_summary=lambda site, window: {"settled_count": 1})
        def tick(self, *args, **kwargs):
            calls.append(("tick", args[2]))

    panel = SimpleNamespace(
        update_runtime_state=lambda state: calls.append(("runtime", state.total_rounds)),
        update_ai_statistics=lambda summary: calls.append(("ai", summary["settled_count"])),
    )
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=False),
        auto_bet_service=Service(),
        auto_bet_panel=panel,
        _active_site="pc28",
        _draw_infos={"pc28": SimpleNamespace(next_period="1001", next_countdown=100)},
        _refresh_auto_bet_frequency_analysis=lambda site, period, now=None, force=False: calls.append(("frequency", period, force)),
    )

    MainWindowDataMixin._arm_auto_bet_refresh_burst(window, now=start)
    MainWindowDataMixin._on_auto_bet_tick(window, now=start)
    MainWindowDataMixin._on_auto_bet_tick(window, now=start + timedelta(seconds=1))
    MainWindowDataMixin._on_auto_bet_tick(window, now=start + timedelta(seconds=2))
    MainWindowDataMixin._on_auto_bet_tick(window, now=start + timedelta(seconds=25))
    MainWindowDataMixin._on_auto_bet_tick(window, now=start + timedelta(seconds=30))

    assert [item for item in calls if item[0] == "runtime"] == [("runtime", 1)]
    assert [item for item in calls if item[0] == "ai"] == [("ai", 1)]


def test_local_three_panel_snapshot_dedupe_skips_identical_payloads():
    from app.ui.main_window_data import MainWindowDataMixin
    from app.models.auto_bet import StrategyConfig, AutoBetRuntimeState

    calls = []
    class Store:
        def accuracy_summary(self, site, window):
            return {"settled_count": 3, "overall": {}}
    service = SimpleNamespace(
        runtime_state=AutoBetRuntimeState(total_rounds=3, total_profit=12.5),
        config=StrategyConfig(site="pc28", ai_accuracy_window=20),
        _ai_prediction_store=Store(),
    )
    panel = SimpleNamespace(
        update_runtime_state=lambda state: calls.append(("runtime", state.total_rounds, state.total_profit)),
        update_ai_statistics=lambda summary: calls.append(("ai", summary["settled_count"])),
    )
    window = SimpleNamespace(auto_bet_service=service, auto_bet_panel=panel)

    MainWindowDataMixin._update_local_runtime_and_ai_statistics(window)
    MainWindowDataMixin._update_local_runtime_and_ai_statistics(window)

    assert calls == [("runtime", 3, 12.5), ("ai", 3)]


def test_local_frequency_analysis_skips_identical_payloads():
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    analysis = {"site": "pc28", "sample_count": 50}
    service = SimpleNamespace(
        _result_provider=object(),
        refresh_frequency_analysis=lambda site, target_period="": dict(analysis),
    )
    panel = SimpleNamespace(update_frequency_analysis=lambda value: calls.append(value))
    window = SimpleNamespace(
        server_mode_settings=SimpleNamespace(enabled=False),
        auto_bet_service=service,
        auto_bet_panel=panel,
    )

    MainWindowDataMixin._refresh_auto_bet_frequency_analysis(window, "pc28", "1001")
    MainWindowDataMixin._refresh_auto_bet_frequency_analysis(window, "pc28", "1001", force=True)

    assert calls == [analysis]


def test_local_24h_stability_simulation_bounds_three_panel_updates():
    from app.ui.main_window_data import MainWindowDataMixin
    from app.models.auto_bet import StrategyConfig, AutoBetRuntimeState

    calls = []
    start = datetime(2026, 7, 28, 0, 0, 0)
    class Service:
        is_running = True
        runtime_state = AutoBetRuntimeState(total_rounds=0)
        config = StrategyConfig(site="pc28", ai_accuracy_window=20)
        _ai_prediction_store = SimpleNamespace(accuracy_summary=lambda site, window: {"settled_count": 0})
        def tick(self, *args, **kwargs):
            pass
    class Window(MainWindowDataMixin):
        server_mode_settings = SimpleNamespace(enabled=False)
        auto_bet_service = Service()
        auto_bet_panel = SimpleNamespace(
            update_runtime_state=lambda state: calls.append("runtime"),
            update_ai_statistics=lambda summary: calls.append("ai"),
        )
        _active_site = "pc28"
        _draw_infos = {"pc28": SimpleNamespace(next_period="1001", next_countdown=100)}
        def _refresh_auto_bet_frequency_analysis(self, site, target_period="", now=None, force=False):
            if MainWindowDataMixin._auto_bet_refresh_due(self, "_local_frequency_last_polled_at", now, force=force):
                calls.append("frequency")

    window = Window()
    MainWindowDataMixin._arm_auto_bet_refresh_burst(window, now=start)
    for offset in range(0, 24 * 60 * 60, 2):
        MainWindowDataMixin._on_auto_bet_tick(window, now=start + timedelta(seconds=offset))

    assert calls.count("runtime") <= 8650
    assert calls.count("ai") <= 8650
    assert calls.count("frequency") <= 8650


def test_starting_server_auto_bet_uses_utc_run_start_for_server_filters(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    class FakeDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 7, 29, 16, 45, 28)
        @classmethod
        def utcnow(cls):
            return cls(2026, 7, 29, 8, 45, 28)

    monkeypatch.setattr("app.ui.main_window_data.datetime", FakeDateTime)

    class Panel:
        def get_config(self):
            from app.models.auto_bet import StrategyConfig
            return StrategyConfig(site="pc28", target_groups=["group"], bet_amount=10)
        def set_running(self, running): pass
        def append_log(self, record): pass
        def update_runtime_state(self, state): pass
        def update_ai_statistics(self, summary): pass
        def update_frequency_analysis(self, analysis): pass

    window = SimpleNamespace(
        auto_bet_panel=Panel(),
        server_api_client=SimpleNamespace(latest_betting_event_id=lambda **kwargs: 10),
        _schedule_server_strategy_save=lambda payload: None,
        _refresh_server_pending_bet=lambda: None,
        _refresh_server_statistics=lambda **kwargs: None,
        _refresh_auto_bet_frequency_analysis=lambda *args, **kwargs: None,
        _auto_bet_timer=SimpleNamespace(start=lambda: None),
    )

    MainWindowDataMixin._start_server_auto_bet(window)

    assert window._server_run_started_at == FakeDateTime(2026, 7, 29, 8, 45, 28)


def test_server_event_created_before_run_uses_utc_naive_comparison():
    from datetime import datetime
    from types import SimpleNamespace
    from app.ui.main_window_data import MainWindowDataMixin

    window = SimpleNamespace(_server_run_started_at=datetime(2026, 7, 29, 8, 45, 28))

    assert MainWindowDataMixin._event_created_before_server_run(
        window, {"created_at": "2026-07-29T09:25:42.621253"}
    ) is False
    assert MainWindowDataMixin._event_created_before_server_run(
        window, {"created_at": "2026-07-29T08:44:59"}
    ) is True
