from __future__ import annotations

from app.ui.auto_bet_panel import BET_STRATEGY_OPTIONS, strategy_help_text


def test_auto_bet_panel_exposes_martingale_strategy_option():
    assert ("\u8d8b\u52bf\u53cd\u6253", "trend_following") in BET_STRATEGY_OPTIONS
    assert ("\u56fa\u5b9a\u500d\u6295", "martingale") in BET_STRATEGY_OPTIONS
    assert ("AI\u4e0b\u6ce8", "ai") in BET_STRATEGY_OPTIONS


def test_strategy_help_text_explains_strategy_differences():
    text = strategy_help_text()

    assert "\u8d8b\u52bf\u53cd\u6253" in text
    assert "\u56fa\u5b9a\u500d\u6295" in text
    assert "\u8fde\u7eed" in text
    assert "\u500d\u6295\u5e8f\u5217" in text
    assert "\u6700\u540e\u4e00\u6863" in text
    assert "\u4e09\u95e8" in text


def test_auto_bet_panel_get_config_uses_selected_strategy():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    idx = panel._strategy_combo.findData("martingale")
    assert idx >= 0

    panel._strategy_combo.setCurrentIndex(idx)

    assert panel.get_config().strategy_type == "martingale"


def test_auto_bet_panel_load_config_selects_martingale_strategy():
    from PySide6.QtWidgets import QApplication
    from app.models.auto_bet import StrategyConfig
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    panel.load_config(StrategyConfig(strategy_type="martingale"))

    assert panel._strategy_combo.currentData() == "martingale"



def test_martingale_sequence_row_visible_only_for_fixed_martingale():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    trend_idx = panel._strategy_combo.findData("trend_following")
    martingale_idx = panel._strategy_combo.findData("martingale")
    assert trend_idx >= 0 and martingale_idx >= 0

    panel._strategy_combo.setCurrentIndex(trend_idx)
    assert not panel._martingale_row_widget.isVisibleTo(panel)

    panel._strategy_combo.setCurrentIndex(martingale_idx)
    assert panel._martingale_row_widget.isVisibleTo(panel)



def test_amount_row_hidden_when_fixed_martingale_sequence_has_value():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("martingale"))

    panel._martingale_edit.setText("100-200-400")
    assert panel._martingale_row_widget.isVisibleTo(panel)
    assert not panel._amount_row_widget.isVisibleTo(panel)

    panel._martingale_edit.setText("")
    assert panel._martingale_row_widget.isVisibleTo(panel)
    assert panel._amount_row_widget.isVisibleTo(panel)

    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("trend_following"))
    assert not panel._martingale_row_widget.isVisibleTo(panel)
    assert panel._amount_row_widget.isVisibleTo(panel)



def test_auto_bet_panel_site_is_read_only_and_follows_active_site():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    assert not panel._site_combo.isEnabled()

    panel.set_active_site("macao")
    assert panel.get_config().site == "macao"
    assert panel._site_combo.currentText() == "macao"

    # Even if code tries to change the combo directly, get_config remains bound to active site.
    panel._site_combo.setCurrentText("norway")
    assert panel.get_config().site == "macao"



def test_auto_bet_panel_locks_target_groups_while_running():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.set_available_groups([("g1", "???")])

    panel.set_running(True)
    assert not panel._target_group_list.isEnabled()

    panel.set_running(False)
    assert panel._target_group_list.isEnabled()


def test_auto_bet_panel_log_shows_group_name_site_and_period():
    from datetime import datetime
    from PySide6.QtWidgets import QApplication
    from app.models.auto_bet import InjectRecord
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    panel.append_log(InjectRecord(
        ts=datetime(2026, 7, 5, 23, 30, 23),
        group_name="???",
        play_type="?",
        amount=100,
        content="?100",
        success=True,
        site="pc28",
        period="20260705001",
    ))

    text = panel._log_edit.toPlainText()
    assert "[???]" in text
    assert "[271226997]" not in text
    assert "pc28" in text
    assert "20260705001" in text
    assert "?100" in text
    assert "\u4e0b\u6ce8\uff1a" in text



def test_auto_bet_panel_log_uses_stable_bet_separator_without_question_mark():
    from datetime import datetime
    from PySide6.QtWidgets import QApplication
    from app.models.auto_bet import InjectRecord
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    panel.append_log(InjectRecord(
        ts=datetime(2026, 7, 5, 23, 53, 58),
        group_name="A\u5438\u91d1A",
        play_type="\u5927/\u5c0f",
        amount=200,
        content="\u5927100\u5c0f100",
        success=True,
        site="pc28",
        period="3455061",
        group_id="g1",
    ))

    text = panel._log_edit.toPlainText()
    assert "?" not in text
    assert "\u4e0b\u6ce8\uff1a\u5927100\u5c0f100" in text


def test_auto_bet_panel_shows_target_group_lock_hint_while_running():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    panel.set_running(True)
    assert panel._target_group_lock_hint.isVisibleTo(panel)
    assert "\u505c\u6b62" in panel._target_group_lock_hint.text()

    panel.set_running(False)
    assert not panel._target_group_lock_hint.isVisibleTo(panel)


def test_ai_strategy_config_exposes_provider_history_and_confirmation():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("ai"))
    panel._ai_provider_combo.setCurrentIndex(panel._ai_provider_combo.findData("anthropic"))
    panel._ai_base_url_edit.setText("https://api.example")
    panel._ai_model_edit.setText("claude-test")
    panel._ai_api_key_edit.setText("secret")
    panel._ai_history_spin.setValue(80)
    panel._ai_confirm_check.setChecked(True)

    config = panel.get_config()

    assert config.strategy_type == "ai"
    assert config.ai_provider == "anthropic"
    assert config.ai_base_url == "https://api.example"
    assert config.ai_model == "claude-test"
    assert config.ai_api_key == "secret"
    assert config.ai_history_count == 80
    assert config.ai_require_confirmation is True
    assert panel._ai_settings_widget.isVisibleTo(panel)
    assert not panel._mode_row_widget.isVisibleTo(panel)
    assert not panel._play_row_widget.isVisibleTo(panel)


def test_ai_pending_suggestion_displays_confirmation_actions():
    from datetime import datetime
    from PySide6.QtWidgets import QApplication
    from app.models.auto_bet import PendingAiBet
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.show_pending_ai_recommendation(PendingAiBet(
        site="pc28",
        period="1001",
        play_type="\u5927\u5355",
        amount=100,
        reason="\u6d4b\u8bd5\u7406\u7531",
        created_at=datetime(2026, 7, 10, 12, 0),
    ))

    assert panel._ai_pending_widget.isVisibleTo(panel)
    assert "\u5927\u5355100" in panel._ai_pending_label.text()
    assert "\u6d4b\u8bd5\u7406\u7531" in panel._ai_pending_label.text()
