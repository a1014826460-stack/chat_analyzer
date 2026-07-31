from __future__ import annotations


def test_server_pending_presentation_uses_neutral_copy_and_tracks_order_id():
    from PySide6.QtWidgets import QApplication

    from app.models.auto_bet import PendingAiBet
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.show_pending_server_bet(PendingAiBet(
        site="pc28", period="20260726001", play_type="大单", amount=10,
        reason="等待服务器确认下注", created_at=__import__("datetime").datetime.now(),
    ), order_id=17)

    assert panel.server_pending_bet_id == 17
    assert "服务器待确认下注" in panel._ai_pending_label.text()
    assert "AI 建议" not in panel._ai_pending_label.text()


def test_server_mode_hides_local_ai_configuration_and_does_not_require_an_api_key_to_start():
    from PySide6.QtWidgets import QApplication

    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.set_server_mode(True)

    assert not panel._ai_config_button.isHidden()
    errors = panel.get_config().start_validation_errors(require_ai_credentials=False)
    assert "API Key" not in errors


def test_server_mode_shows_server_managed_ai_status_without_local_secret_controls():
    from PySide6.QtWidgets import QApplication

    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.set_server_mode(True)
    panel.show()

    assert panel._server_ai_status_label.isVisible()
    assert "服务器托管" in panel._server_ai_status_label.text()
    assert "API Key" not in panel._server_ai_status_label.text()
    assert not panel._ai_config_button.isHidden()


def test_starting_server_auto_bet_appends_immediate_feedback_to_run_log():
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    records = []

    class Panel:
        def get_config(self):
            from app.models.auto_bet import StrategyConfig
            return StrategyConfig(site="pc28", target_groups=["group"], bet_amount=10)

        def set_running(self, running):
            self.running = running

        def append_log(self, record):
            records.append(record)

    window = SimpleNamespace(
        auto_bet_panel=Panel(),
        _schedule_server_strategy_save=lambda payload: None,
        _refresh_server_pending_bet=lambda: None,
        _auto_bet_timer=SimpleNamespace(start=lambda: None),
    )

    MainWindowDataMixin._start_server_auto_bet(window)

    assert records
    assert "等待本期频率与 AI 决策" in records[0].content


def test_server_mode_keeps_strategy_config_button_without_local_ai_secret_fields():
    from PySide6.QtWidgets import QApplication

    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.set_server_mode(True)
    panel.show()

    assert panel._ai_config_button.isVisibleTo(panel)
    assert "配置" in panel._ai_config_button.text()
    assert "API Key" not in panel._ai_config_button.toolTip()

    dialog = panel._ai_config_dialog
    assert not hasattr(dialog, "_base_url_edit")
    assert not hasattr(dialog, "_model_edit")
    assert not hasattr(dialog, "_api_key_edit")
    assert not dialog._confidence_spin.isHidden()
    assert not dialog._take_profit_spin.isHidden()
    assert not dialog._stop_loss_spin.isHidden()


