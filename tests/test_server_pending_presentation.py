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

    assert not panel._ai_config_button.isVisible()
    errors = panel.get_config().start_validation_errors(require_ai_credentials=False)
    assert "API Key" not in errors
