
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtWidgets import QApplication, QLabel, QGridLayout, QWidget

from app.models import DrawInfo
from app.ui.main_window_realtime import MainWindowRealtimeMixin
from app.services.server_api_client import ServerApiError


def test_main_window_restores_only_a_known_last_selected_site(monkeypatch):
    from app.ui.main_window import MainWindow

    monkeypatch.setattr("app.ui.main_window.site_list", lambda: ["pc28", "macao"])

    assert MainWindow._last_selected_site_from_settings({"last_selected_site": "macao"}) == "macao"
    assert MainWindow._last_selected_site_from_settings({"last_selected_site": "unknown"}) == ""


class DummyRealtimeWindow(QWidget, MainWindowRealtimeMixin):
    def __init__(self) -> None:
        super().__init__()
        self._active_site = "macao"
        self._draw_infos = {
            "pc28": DrawInfo(current_period="1"),
            "macao": DrawInfo(current_period="2"),
        }
        self._site_card_widgets = {}
        self.site_cards_layout = QGridLayout()
        self.site_status_label = QLabel()

    def _select_site(self, site: str) -> None:  # not used by this test
        self._active_site = site


def test_render_site_cards_marks_active_site_visually(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.ui.main_window_realtime.site_list", lambda: ["pc28", "macao"])
    monkeypatch.setattr("app.ui.main_window_realtime.site_label", lambda site: site)

    window = DummyRealtimeWindow()
    window._render_site_cards()

    active_frame = window._site_card_widgets["macao"]["frame"]
    inactive_frame = window._site_card_widgets["pc28"]["frame"]

    assert active_frame.property("activeSite") is True
    assert inactive_frame.property("activeSite") is False
    assert "border: 2px" in active_frame.styleSheet()
    assert "background" in active_frame.styleSheet()


def test_render_site_cards_marks_unavailable_period_without_discarding_previous_data(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.ui.main_window_realtime.site_list", lambda: ["pc28", "macao"])
    monkeypatch.setattr("app.ui.main_window_realtime.site_label", lambda site: site)

    window = DummyRealtimeWindow()
    window._draw_infos["macao"] = DrawInfo(
        current_period="2",
        next_period="3",
        source="unavailable",
    )
    window._render_site_cards()

    assert window._site_card_widgets["macao"]["notice"].text() == "当前期暂不可用，保留上次数据"
    assert "暂不可用" in window.site_status_label.text()



class FakeAutoBetPanel:
    def __init__(self) -> None:
        self.site = ""

    def set_active_site(self, site: str) -> None:
        self.site = site


def test_refresh_active_site_info_syncs_auto_bet_panel_site(monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.ui.main_window_realtime.site_label", lambda site: site)

    window = DummyRealtimeWindow()
    window.active_site_label = QLabel()
    window.active_period_label = QLabel()
    window.next_period_label = QLabel()
    window.countdown_label = QLabel()
    window.period_input = QLineEdit()
    window.auto_bet_panel = FakeAutoBetPanel()

    window._refresh_active_site_info()

    assert window.auto_bet_panel.site == "macao"


def test_select_site_persists_the_last_selected_site(monkeypatch):
    from types import SimpleNamespace

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.ui.main_window_realtime.site_label", lambda site: site)

    saved: list[dict[str, str]] = []
    window = DummyRealtimeWindow()
    window.settings = {}
    window._query_period_overrides_by_site = {}
    window._query_period_override = ""
    window._manual_period_override = False
    window._stats_locked = False
    window._awaiting_next_period = False
    window._last_message_cursor = {}
    window.lock_status_label = QLabel()
    window.auto_refresh_label = QLabel()
    window.active_site_label = QLabel()
    window.active_period_label = QLabel()
    window.next_period_label = QLabel()
    window.countdown_label = QLabel()
    window.current_visual_rows = []
    window.chart_window = SimpleNamespace(set_status=lambda *args: None, set_status_seconds=lambda *args: None)
    window._format_countdown = lambda value: "00:00"
    window._set_status = lambda *args: None
    window._load_filtered_messages = lambda: None
    window._sync_chart_status = lambda: None
    window._save_settings = lambda: saved.append(dict(window.settings))
    window._current_period_override = lambda: ""
    window._has_manual_period_override = lambda: False
    window._default_query_period = lambda info: ""
    window._sync_period_input_from_site = lambda info: None

    MainWindowRealtimeMixin._select_site(window, "pc28")

    assert window.settings["last_selected_site"] == "pc28"
    assert saved == [{"last_selected_site": "pc28"}]


class ClockHarness(MainWindowRealtimeMixin):
    def __init__(self) -> None:
        self.applied: list[tuple[str, DrawInfo]] = []
        self.calibrations: list[tuple[str, datetime]] = []

    def _apply_single_draw_info(self, payload) -> None:
        site, info, _error = payload
        self.applied.append((site, info))

    def _schedule_draw_calibration(self, site: str, due_at: datetime) -> None:
        self.calibrations.append((site, due_at))


def test_countdown_tick_does_not_advance_without_a_schedule_anchor():
    window = ClockHarness()
    info = DrawInfo(current_period="100", next_period="101", next_countdown=0)

    window._advance_site_countdown("pc28", info, datetime(2026, 7, 10, 12, 0))

    assert window.applied == []
    assert window.calibrations == []


def test_local_advance_catches_up_only_for_elapsed_intervals():
    window = ClockHarness()
    boundary = datetime(2026, 7, 10, 12, 0)
    info = DrawInfo(
        current_period="100",
        next_period="101",
        next_time=boundary,
        interval_sec=210,
        source="inferred",
    )

    advanced = window._advance_site_locally(
        "pc28",
        info,
        boundary + timedelta(seconds=420),
    )

    assert advanced.current_period == "103"
    assert advanced.next_period == "104"
    assert advanced.start_time == boundary + timedelta(seconds=420)
    assert advanced.next_time == boundary + timedelta(seconds=630)


def test_server_draw_fetch_keeps_other_sites_when_one_current_period_is_unavailable(monkeypatch):
    class Client:
        def current_draw(self, site):
            if site == "macao":
                raise ServerApiError("服务器请求失败 (503): 当前期数据暂不可用")
            return {"next_period": "1002", "next_time": "2026-08-02T12:03:00"}

    class Window(MainWindowRealtimeMixin):
        server_api_client = Client()
        _draw_infos = {"macao": DrawInfo(current_period="1000", next_period="1001")}

    monkeypatch.setattr("app.ui.main_window_realtime.site_list", lambda: ["pc28", "macao"])

    payload = Window()._fetch_server_draw_infos()

    assert payload["pc28"].next_period == "1002"
    assert payload["macao"].next_period == "1001"
    assert payload["macao"].source == "unavailable"


def test_primary_modules_start_as_a_single_expanded_accordion():
    from app.ui.auto_bet_panel import AutoBetPanel
    from app.ui.collapsible_section import CollapsibleSection, ModuleAccordion

    app = QApplication.instance() or QApplication([])
    site = CollapsibleSection("线路选择", expanded=True)
    account = CollapsibleSection("账号与数据源")
    blocked = CollapsibleSection("屏蔽名单")
    auto_bet = AutoBetPanel()
    auto_bet.set_expanded(False)
    accordion = ModuleAccordion(site, account, blocked, auto_bet)

    assert site.is_expanded()
    assert not account.is_expanded()
    assert not blocked.is_expanded()
    assert not auto_bet.is_expanded()

    auto_bet.set_expanded(True)

    assert not site.is_expanded()
    assert auto_bet.is_expanded()


def test_primary_module_accordion_includes_filter_conditions():
    from app.ui.collapsible_section import CollapsibleSection, ModuleAccordion

    app = QApplication.instance() or QApplication([])
    site = CollapsibleSection("线路选择", expanded=True)
    account = CollapsibleSection("账号与数据源")
    filters = CollapsibleSection("筛选条件")
    blocked = CollapsibleSection("屏蔽名单")
    auto_bet = CollapsibleSection("自动下注")
    accordion = ModuleAccordion(site, account, filters, blocked, auto_bet)

    filters.set_expanded(True)

    assert not site.is_expanded()
    assert not account.is_expanded()
    assert filters.is_expanded()
    assert not blocked.is_expanded()
    assert not auto_bet.is_expanded()


def test_analysis_left_primary_modules_use_compact_spacing_and_filter_module_source():
    from pathlib import Path

    source = Path("app/ui/main_window_layout.py").read_text(encoding="utf-8")

    assert "left.setSpacing(3)" in source
    assert 'self.filter_module_section = CollapsibleSection("筛选条件")' in source
    assert "def _configure_primary_module" in source
