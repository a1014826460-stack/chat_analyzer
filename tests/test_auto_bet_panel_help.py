from __future__ import annotations

from app.ui.auto_bet_panel import BET_STRATEGY_OPTIONS, strategy_help_text


def test_auto_bet_panel_exposes_martingale_strategy_option():
    assert ("\u8d8b\u52bf\u53cd\u6253", "trend_following") in BET_STRATEGY_OPTIONS
    assert ("\u56fa\u5b9a\u500d\u6295", "martingale") in BET_STRATEGY_OPTIONS
    assert ("\u5e73\u63a8", "flat") in BET_STRATEGY_OPTIONS
    assert all(value != "ai" for _label, value in BET_STRATEGY_OPTIONS)


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

    assert not hasattr(panel, "_site_combo")

    panel.set_active_site("macao")
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
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("flat"))
    panel._ai_config_dialog._provider_combo.setCurrentIndex(panel._ai_config_dialog._provider_combo.findData("anthropic"))
    panel._ai_config_dialog._base_url_edit.setText("https://api.example")
    panel._ai_config_dialog._model_edit.setText("claude-test")
    panel._ai_config_dialog._api_key_edit.setText("secret")
    panel._ai_config_dialog._history_spin.setValue(80)
    panel._ai_config_dialog._confidence_spin.setValue(70)
    panel._ai_config_dialog._accuracy_window_spin.setValue(35)
    panel._ai_config_dialog._confirm_check.setChecked(True)

    config = panel.get_config()
    panel._ai_config_dialog.apply_to_config(config)

    assert config.strategy_type == "flat"
    assert config.ai_provider == "anthropic"
    assert config.ai_base_url == "https://api.example"
    assert config.ai_model == "claude-test"
    assert config.ai_api_key == "secret"
    assert config.ai_history_count == 80
    assert config.ai_confidence_threshold == 70
    assert config.ai_accuracy_window == 35
    assert config.ai_require_confirmation is True
    assert panel._ai_config_button.isVisibleTo(panel)
    assert panel._mode_row_widget.isVisibleTo(panel)
    assert panel._play_row_widget.isVisibleTo(panel)


def test_ai_config_button_is_visible_for_every_ai_constrained_strategy():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("trend_following"))
    assert panel._ai_config_button.isVisibleTo(panel)

    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("flat"))
    assert panel._ai_config_button.isVisibleTo(panel)


def test_auto_bet_panel_locks_all_configuration_controls_while_running():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("flat"))

    panel.set_running(True)

    assert not panel._strategy_combo.isEnabled()
    assert not panel._amount_spin.isEnabled()
    assert not panel._lock_spin.isEnabled()
    assert not panel._ai_config_button.isEnabled()
    assert not panel._odds_edits["\u5927"].isEnabled()

    panel.set_running(False)
    assert panel._strategy_combo.isEnabled()
    assert panel._amount_spin.isEnabled()
    assert panel._lock_spin.isEnabled()
    assert panel._ai_config_button.isEnabled()


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
        confidence=78,
        quant_rationale="近 20 期方向频率偏高",
    ))

    assert panel._ai_pending_widget.isVisibleTo(panel)
    assert "\u5927\u5355100" in panel._ai_pending_label.text()
    assert "\u6d4b\u8bd5\u7406\u7531" in panel._ai_pending_label.text()
    assert "78/100" in panel._ai_pending_label.text()
    assert "近 20 期方向频率偏高" in panel._ai_pending_label.text()


def test_auto_bet_panel_displays_ai_accuracy_summary():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    panel.update_ai_statistics({
        "settled_count": 10,
        "overall": {"direction_accuracy": 0.7, "exact_accuracy": 0.4},
        "short": {"window": 20, "count": 8, "direction_accuracy": 0.625, "exact_accuracy": 0.375},
        "streak": {"result": "hit", "count": 3},
    })

    text = panel._ai_stats_label.text()
    assert "总体方向 70.0%" in text
    assert "总体精确 40.0%" in text
    assert "近 20 条方向 62.5%" in text
    assert "连中 3" in text


def test_auto_bet_panel_labels_pending_and_settled_betting_statistics():
    from PySide6.QtWidgets import QApplication
    from app.models.auto_bet import AutoBetRuntimeState
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.update_runtime_state(AutoBetRuntimeState(
        pending_staked=20,
        total_staked=40,
        total_payout=79.2,
        total_profit=39.2,
    ))

    text = panel._stats_label.text()
    assert "待开奖下注: 20.00" in text
    assert "已结算下注: 40.00" in text
    assert "已结算盈亏: 39.20" in text


def test_auto_bet_panel_formats_recent_ai_prediction_history():
    from datetime import datetime
    from app.services.ai_prediction_store import AiPredictionRecord
    from app.ui.auto_bet_panel import AutoBetPanel

    record = AiPredictionRecord(
        site="pc28", period="1001", action="bet", play_type="大", confidence=78,
        quant_rationale="方向频率偏高", reason="存在优势", model="model",
        history_snapshot=[], quant_snapshot={}, sent=True, actual_result="大双",
        direction_hit=True, exact_hit=False, status="settled",
        created_at=datetime(2026, 7, 12, 12, 0), settled_at=datetime(2026, 7, 12, 12, 3),
    )

    text = AutoBetPanel.format_ai_history([record])

    assert "[pc28 1001]" in text
    assert "预测 大" in text
    assert "置信度 78/100" in text
    assert "实际 大双" in text
    assert "方向命中 / 精确未中" in text


def test_ai_status_log_shows_site_period_and_group_names():
    from datetime import datetime
    from PySide6.QtWidgets import QApplication
    from app.models.auto_bet import InjectRecord
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel.append_log(InjectRecord(
        ts=datetime(2026, 7, 10, 23, 52, 53),
        group_name="\u7fa4A, \u7fa4B",
        play_type="",
        amount=0,
        content="AI \u81ea\u52a8\u4e0b\u6ce8\uff1a\u5c0f\u53cc100\uff1b\u6d4b\u8bd5\u7406\u7531",
        success=True,
        site="pc28",
        period="3455463",
    ))

    text = panel._log_edit.toPlainText()
    assert "[pc28 3455463]" in text
    assert "[\u7fa4A, \u7fa4B]" in text


def test_ai_api_key_is_hidden_by_default_and_eye_button_toggles_visibility():
    from PySide6.QtWidgets import QApplication, QLineEdit
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    dialog = panel._ai_config_dialog

    assert dialog._api_key_edit.echoMode() == QLineEdit.Password
    dialog._api_key_visibility_button.click()
    assert dialog._api_key_edit.echoMode() == QLineEdit.Normal
    dialog._api_key_visibility_button.click()
    assert dialog._api_key_edit.echoMode() == QLineEdit.Password


def test_ai_config_dialog_requires_a_valid_provider_and_all_credential_fields():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    dialog = panel._ai_config_dialog
    dialog._base_url_edit.setText("https://api.example")
    dialog._model_edit.setText("model")
    dialog._api_key_edit.setText("key")

    assert dialog.has_required_values()

    dialog._provider_combo.setCurrentIndex(-1)

    assert not dialog.has_required_values()


def test_ai_config_exposes_conflict_preference_and_risk_limits():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    dialog = panel._ai_config_dialog
    dialog._prefer_ai_conflict_check.setChecked(True)
    dialog._take_profit_spin.setValue(500)
    dialog._stop_loss_spin.setValue(300)

    config = panel.get_config()

    assert config.ai_prefer_recommendation_on_conflict is True
    assert config.take_profit_limit == 500
    assert config.stop_loss_limit == 300
    assert panel._play_label.text() == "推荐玩法:"


def test_recommended_play_checkboxes_allow_all_eight_play_types():
    from PySide6.QtWidgets import QApplication
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()
    panel._mode_combo.setCurrentIndex(panel._mode_combo.findData("size"))

    assert all(check.isEnabled() for check in panel._play_checkboxes.values())
