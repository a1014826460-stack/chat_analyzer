
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QGridLayout, QWidget

from app.models import DrawInfo
from app.ui.main_window_realtime import MainWindowRealtimeMixin


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
