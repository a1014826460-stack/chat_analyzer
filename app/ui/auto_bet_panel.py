from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.auto_bet import DEFAULT_ODDS, AutoBetRuntimeState, InjectRecord, PendingAiBet, StrategyConfig


logger = logging.getLogger(__name__)

PLAY_TYPE_OPTIONS = ["大", "小", "单", "双", "大单", "小单", "大双", "小双"]
SITE_OPTIONS = ["pc28", "macao", "australia", "norway"]
BET_STRATEGY_OPTIONS = [
    ("\u8d8b\u52bf\u53cd\u6253", "trend_following"),
    ("\u56fa\u5b9a\u500d\u6295", "martingale"),
    ("AI\u4e0b\u6ce8", "ai"),
]


def strategy_help_text() -> str:
    return (
        "\u81ea\u52a8\u4e0b\u6ce8\u7b56\u7565\u8bf4\u660e\n\n"
        "1. \u8d8b\u52bf\u53cd\u6253\n"
        "   \u89c2\u5bdf\u6700\u8fd1 N \u671f\u5f00\u5956\u7ed3\u679c\uff0c\u5f53\u540c\u4e00\u7c7b\u7ed3\u679c\u8fde\u7eed\u51fa\u73b0\u8fbe\u5230\u89e6\u53d1\u9608\u503c\u65f6\uff0c\u4e0b\u4e00\u671f\u53cd\u5411\u4e0b\u6ce8\u3002\n"
        "   \u4f8b\u5982\uff1a\u8fde\u7eed 3 \u671f\u5c0f\uff0c\u5219\u4e0b\u4e00\u671f\u4e0b\u6ce8\u5927\u3002\n"
        "   \u7279\u70b9\uff1a\u7b49\u5f85\u8fde\u7eed\u4fe1\u53f7\uff0c\u51fa\u624b\u9891\u7387\u8f83\u4f4e\u3002\n\n"
        "2. \u56fa\u5b9a\u500d\u6295\n"
        "   \u4e0d\u7b49\u5f85\u8fde\u7eed\u9608\u503c\uff0c\u6bcf\u4e2a\u53ef\u4e0b\u6ce8\u65f6\u95f4\u7a97\u53e3\u90fd\u6309\u5df2\u9009\u73a9\u6cd5\u4e0b\u6ce8\u3002\n"
        "   \u91d1\u989d\u6765\u81ea\u500d\u6295\u5e8f\u5217\uff0c\u4f8b\u5982 100-200-400-800\u3002\n"
        "   \u4e0a\u4e00\u8f6e\u8f93\u4e86\u8fdb\u5165\u4e0b\u4e00\u6863\uff0c\u8d62\u4e86\u56de\u5230\u7b2c\u4e00\u6863\u3002\n"
        "   \u5982\u679c\u6700\u540e\u4e00\u6863\u4ecd\u7136\u5931\u8d25\uff0c\u7b56\u7565\u4f1a\u6682\u505c\uff0c\u7b49\u5f85\u4eba\u5de5\u5904\u7406\u3002\n\n"
        "3. \u529f\u80fd/\u73a9\u6cd5\u533a\u522b\n"
        "   \u5927\u5c0f\u3001\u5355\u53cc\uff1a\u9009\u62e9\u5176\u4e2d\u4e00\u4e2a\u6216\u591a\u4e2a\u65b9\u5411\u3002\n"
        "   \u4e09\u95e8\uff1a\u901a\u5e38\u9009\u62e9 3 \u4e2a\u95e8\uff0c\u6bcf\u671f\u540c\u65f6\u53d1\u9001 3 \u6761\u4e0b\u6ce8\u3002\n"
        "   \u4e0b\u6ce8\u53ea\u4f1a\u5728\u5f53\u671f\u5f00\u59cb 30 \u79d2\u540e\u5230\u5c01\u76d8\u524d\u7684\u65f6\u95f4\u7a97\u53e3\u5185\u6267\u884c\u3002"
    )

BET_MODE_OPTIONS = [
    ("压大小", "size"),
    ("压单双", "parity"),
    ("压小单大双", "small_odd_big_even"),
    ("压小双大单", "small_even_big_odd"),
    ("压三门", "three_doors"),
]


class AiConfigDialog(QDialog):
    """Keep API credentials out of the always-visible betting panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 配置")
        self.setModal(True)
        self.resize(460, 230)
        layout = QVBoxLayout(self)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("AI 类型:"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("OpenAI 兼容", "openai_compatible")
        self._provider_combo.addItem("Anthropic", "anthropic")
        provider_row.addWidget(self._provider_combo, 1)
        layout.addLayout(provider_row)

        for label, attr, placeholder, secret in (
            ("Base URL:", "_base_url_edit", "https://api.example.com/v1", False),
            ("模型:", "_model_edit", "gpt-4.1-mini", False),
            ("API Key:", "_api_key_edit", "", True),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            if secret:
                edit.setEchoMode(QLineEdit.Password)
            setattr(self, attr, edit)
            row.addWidget(edit, 1)
            if secret:
                self._api_key_visibility_button = QPushButton("👁")
                self._api_key_visibility_button.setCheckable(True)
                self._api_key_visibility_button.setFixedWidth(38)
                self._api_key_visibility_button.setToolTip("显示 API Key")
                self._api_key_visibility_button.toggled.connect(self._toggle_api_key_visibility)
                row.addWidget(self._api_key_visibility_button)
            layout.addLayout(row)

        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("历史期数:"))
        self._history_spin = QSpinBox()
        self._history_spin.setRange(20, 200)
        self._history_spin.setValue(50)
        history_row.addWidget(self._history_spin)
        self._confirm_check = QCheckBox("每期下注前需确认")
        history_row.addWidget(self._confirm_check)
        history_row.addStretch(1)
        layout.addLayout(history_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def load_config(self, config: StrategyConfig) -> None:
        index = self._provider_combo.findData(config.ai_provider)
        if index >= 0:
            self._provider_combo.setCurrentIndex(index)
        self._base_url_edit.setText(config.ai_base_url)
        self._model_edit.setText(config.ai_model)
        self._api_key_edit.setText(config.ai_api_key)
        self._history_spin.setValue(config.ai_history_count)
        self._confirm_check.setChecked(config.ai_require_confirmation)

    def apply_to_config(self, config: StrategyConfig) -> None:
        config.ai_provider = str(self._provider_combo.currentData() or "openai_compatible")
        config.ai_base_url = self._base_url_edit.text().strip()
        config.ai_model = self._model_edit.text().strip()
        config.ai_api_key = self._api_key_edit.text().strip()
        config.ai_history_count = self._history_spin.value()
        config.ai_require_confirmation = self._confirm_check.isChecked()

    def has_required_values(self) -> bool:
        return bool(
            self._base_url_edit.text().strip()
            and self._model_edit.text().strip()
            and self._api_key_edit.text().strip()
        )

    def _toggle_api_key_visibility(self, visible: bool) -> None:
        self._api_key_edit.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self._api_key_visibility_button.setToolTip("隐藏 API Key" if visible else "显示 API Key")


class AutoBetPanel(QGroupBox):
    """Auto-betting configuration and control panel.

    Signals:
        config_changed(StrategyConfig) — emitted when any parameter changes
        start_clicked() — start button pressed
        stop_clicked()  — stop button pressed
    """

    config_changed = Signal(object)
    start_clicked = Signal()
    stop_clicked = Signal()
    ai_confirm_clicked = Signal()
    ai_skip_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("自动下注", parent)
        self._config = StrategyConfig()
        self._active_site = self._config.site
        self._group_names: dict[str, str] = {}
        self._running = False
        self._ai_config_dialog = AiConfigDialog(self)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_available_groups(self, groups: list[tuple[str, str]]) -> None:
        """Populate target group checklist. Each item is (group_id, group_name)."""
        self._target_group_list.clear()
        self._group_names = {str(group_id): str(group_name) for group_id, group_name in groups}
        for group_id, group_name in groups:
            item = QListWidgetItem(group_name)
            item.setData(Qt.UserRole, group_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if group_id in self._config.target_groups else Qt.Unchecked
            )
            self._target_group_list.addItem(item)

    def set_running(self, running: bool) -> None:
        """Update UI for running/stopped state."""
        self._running = running
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._set_config_controls_enabled(not running)
        if hasattr(self, "_target_group_lock_hint"):
            self._target_group_lock_hint.setVisible(running)
        self._status_label.setText("● 运行中" if running else "○ 已停止")
        self._status_label.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if running else "color: #9e9e9e;"
        )

    def append_log(self, record: InjectRecord) -> None:
        """Append a line to the run log."""
        ts = record.ts.strftime("%H:%M:%S")
        icon = "✓" if record.success else "✗"
        if record.play_type:
            group_label = self._display_group_name(record)
            context_parts = []
            if record.site:
                context_parts.append(record.site)
            if record.period:
                context_parts.append(record.period)
            context = f" [{' '.join(context_parts)}]" if context_parts else ""
            bet_text = record.content or f"{record.play_type}{self._format_amount(record.amount)}"
            line = f"{ts} {icon}{context} [{group_label}] \u4e0b\u6ce8\uff1a{bet_text}"
        else:
            context_parts = [value for value in (record.site, record.period) if value]
            context = f" [{' '.join(context_parts)}]" if context_parts else ""
            group_label = self._display_group_name(record)
            group_context = f" [{group_label}]" if group_label else ""
            line = f"{ts} {icon}{context}{group_context} {record.content}"
        if record.error:
            line += f"  ({record.error})"
        self._log_edit.append(line)

    def _display_group_name(self, record: InjectRecord) -> str:
        group_id = str(getattr(record, "group_id", "") or "").strip()
        raw = str(record.group_name or "").strip()
        if group_id and group_id in self._group_names:
            return self._group_names[group_id]
        if raw in self._group_names:
            return self._group_names[raw]
        return raw or group_id

    def update_runtime_state(self, state: AutoBetRuntimeState) -> None:
        """Refresh practical win/loss statistics."""
        self._stats_label.setText(
            "总下注: {staked:.2f} | 总派彩: {payout:.2f} | 总盈亏: {profit:.2f}\n"
            "当前倍投档: {step} | 当前连输: {losses} | 已结算: {rounds} | 命中: {wins} | 未中: {loses}\n"
            "状态: {status}".format(
                staked=state.total_staked,
                payout=state.total_payout,
                profit=state.total_profit,
                step=state.current_step + 1,
                losses=state.consecutive_losses,
                rounds=state.total_rounds,
                wins=state.win_rounds,
                loses=state.lose_rounds,
                status=state.halt_reason if state.halted else ("运行中" if self._running else "已停止"),
            )
        )

    def _set_config_controls_enabled(self, enabled: bool) -> None:
        controls = [
            self._strategy_combo,
            self._target_group_list,
            self._obs_window_spin,
            self._trigger_spin,
            self._amount_spin,
            self._martingale_edit,
            self._mode_combo,
            self._lock_spin,
            self._ai_config_button,
        ]
        controls.extend(self._play_checkboxes.values())
        controls.extend(self._odds_edits.values())
        for control in controls:
            control.setEnabled(enabled)

    def show_pending_ai_recommendation(self, pending: PendingAiBet | None) -> None:
        if pending is None:
            self._ai_pending_widget.setVisible(False)
            self._ai_pending_key = None
            return
        self._ai_pending_key = (pending.site, pending.period)
        self._ai_pending_label.setText(
            "\u672c\u671f AI \u5efa\u8bae [{site} {period}]\uff1a{play}{amount}\n\u7406\u7531\uff1a{reason}".format(
                site=pending.site,
                period=pending.period,
                play=pending.play_type,
                amount=self._format_amount(pending.amount),
                reason=pending.reason,
            )
        )
        self._ai_pending_widget.setVisible(True)

    @property
    def pending_ai_key(self) -> tuple[str, str] | None:
        return getattr(self, "_ai_pending_key", None)

    def get_config(self) -> StrategyConfig:
        """Build config from current UI state."""
        checked_groups: list[str] = []
        for i in range(self._target_group_list.count()):
            item = self._target_group_list.item(i)
            if item.checkState() == Qt.Checked:
                gid = str(item.data(Qt.UserRole) or "")
                if gid:
                    checked_groups.append(gid)

        checked_plays: list[str] = []
        for pt, cb in self._play_checkboxes.items():
            if cb.isChecked():
                checked_plays.append(pt)

        config = StrategyConfig(
            strategy_type=str(self._strategy_combo.currentData() or "trend_following"),
            enabled=self._running,
            site=self._active_site.strip(),
            target_groups=checked_groups,
            observation_window=self._obs_window_spin.value(),
            trigger_threshold=self._trigger_spin.value(),
            bet_amount=self._amount_spin.value(),
            play_types=checked_plays,
            lock_threshold_sec=self._lock_spin.value(),
            bet_mode=str(self._mode_combo.currentData() or "size"),
            martingale_sequence=self._parse_martingale_text(self._martingale_edit.text()),
            odds=self._odds_from_inputs(),
        )
        self._ai_config_dialog.apply_to_config(config)
        return config

    def load_config(self, config: StrategyConfig) -> None:
        """Apply config to UI fields."""
        self._config = config
        self._active_site = config.site or self._active_site
        idx = self._strategy_combo.findData(config.strategy_type)
        if idx >= 0:
            self._strategy_combo.setCurrentIndex(idx)
        self._obs_window_spin.setValue(config.observation_window)
        self._trigger_spin.setValue(config.trigger_threshold)
        self._amount_spin.setValue(config.bet_amount)
        self._lock_spin.setValue(config.lock_threshold_sec)
        idx = self._mode_combo.findData(config.bet_mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._martingale_edit.setText("-".join(self._format_amount(value) for value in config.martingale_sequence))
        for pt, cb in self._play_checkboxes.items():
            cb.setChecked(pt in config.play_types)
        for play, edit in self._odds_edits.items():
            edit.setText(str(config.odds.get(play, DEFAULT_ODDS.get(play, 1.0))))
        self._ai_config_dialog.load_config(config)
        self._sync_play_checkboxes_for_mode()
        self._sync_strategy_visibility()

    def set_active_site(self, site: str) -> None:
        """Keep auto-bet site in sync with the global line selection."""
        value = str(site or "").strip()
        if not value:
            return
        if self._running:
            return
        changed = value != self._active_site
        self._active_site = value
        if changed:
            self._emit_config()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- Row: strategy type ---
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel("策略:"))
        self._strategy_combo = QComboBox()
        for label, value in BET_STRATEGY_OPTIONS:
            self._strategy_combo.addItem(label, value)
        self._strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        strategy_row.addWidget(self._strategy_combo, 1)
        self._help_btn = QPushButton("?")
        self._help_btn.setToolTip("\u7b56\u7565\u8bf4\u660e")
        self._help_btn.clicked.connect(self._show_strategy_help)
        strategy_row.addWidget(self._help_btn)
        layout.addLayout(strategy_row)

        self._mode_row_widget = QWidget()
        mode_row = QHBoxLayout(self._mode_row_widget)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(QLabel("功能:"))
        self._mode_combo = QComboBox()
        for label, value in BET_MODE_OPTIONS:
            self._mode_combo.addItem(label, value)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo, 1)
        layout.addWidget(self._mode_row_widget)

        # --- Target groups ---
        layout.addWidget(QLabel("目标群组:"))
        self._target_group_list = QListWidget()
        self._target_group_list.setMaximumHeight(80)
        self._target_group_list.itemChanged.connect(self._emit_config)
        layout.addWidget(self._target_group_list)
        self._target_group_lock_hint = QLabel("\u8fd0\u884c\u4e2d\u5df2\u9501\u5b9a\u76ee\u6807\u7fa4\u7ec4\uff0c\u5982\u9700\u4fee\u6539\u8bf7\u5148\u505c\u6b62\u81ea\u52a8\u4e0b\u6ce8\u3002")
        self._target_group_lock_hint.setStyleSheet("color: #d35400; font-weight: bold;")
        self._target_group_lock_hint.setWordWrap(True)
        self._target_group_lock_hint.setVisible(False)
        layout.addWidget(self._target_group_lock_hint)

        # --- Parameters grid ---
        grid = QHBoxLayout()
        grid.addWidget(QLabel("观察窗口:"))
        self._obs_window_spin = QSpinBox()
        self._obs_window_spin.setRange(3, 100)
        self._obs_window_spin.setValue(10)
        self._obs_window_spin.valueChanged.connect(self._emit_config)
        grid.addWidget(self._obs_window_spin)
        grid.addWidget(QLabel("期"))
        grid.addWidget(QLabel("触发阈值:"))
        self._trigger_spin = QSpinBox()
        self._trigger_spin.setRange(2, 50)
        self._trigger_spin.setValue(3)
        self._trigger_spin.valueChanged.connect(self._emit_config)
        grid.addWidget(self._trigger_spin)
        grid.addWidget(QLabel("次"))
        grid.addStretch(1)
        layout.addLayout(grid)

        # --- Amount ---
        self._amount_row_widget = QWidget()
        amt_row = QHBoxLayout(self._amount_row_widget)
        amt_row.setContentsMargins(0, 0, 0, 0)
        amt_row.addWidget(QLabel("\u4e0b\u6ce8\u91d1\u989d:"))
        self._amount_spin = QDoubleSpinBox()
        self._amount_spin.setRange(0.01, 999999.0)
        self._amount_spin.setDecimals(2)
        self._amount_spin.setValue(10.0)
        self._amount_spin.valueChanged.connect(self._emit_config)
        amt_row.addWidget(self._amount_spin)
        amt_row.addStretch(1)
        layout.addWidget(self._amount_row_widget)

        self._martingale_row_widget = QWidget()
        martingale_row = QHBoxLayout(self._martingale_row_widget)
        martingale_row.setContentsMargins(0, 0, 0, 0)
        martingale_row.addWidget(QLabel("\u500d\u6295\u5e8f\u5217:"))
        self._martingale_edit = QLineEdit("100-200-400-800")
        self._martingale_edit.setPlaceholderText("\u4f8b\u5982: 100-200-400-800")
        self._martingale_edit.textChanged.connect(self._on_martingale_text_changed)
        martingale_row.addWidget(self._martingale_edit, 1)
        layout.addWidget(self._martingale_row_widget)

        self._ai_config_button = QPushButton("AI 配置")
        self._ai_config_button.setToolTip("配置 AI 类型、Base URL、模型、API Key 和确认方式")
        self._ai_config_button.clicked.connect(self._open_ai_config_dialog)
        layout.addWidget(self._ai_config_button)

        # --- Play types ---
        self._play_row_widget = QWidget()
        play_row = QHBoxLayout(self._play_row_widget)
        play_row.setContentsMargins(0, 0, 0, 0)
        play_row.addWidget(QLabel("玩法:"))
        self._play_checkboxes: dict[str, QCheckBox] = {}
        for pt in PLAY_TYPE_OPTIONS:
            cb = QCheckBox(pt)
            cb.setChecked(pt in ("大", "小"))
            cb.toggled.connect(self._emit_config)
            self._play_checkboxes[pt] = cb
            play_row.addWidget(cb)
        play_row.addStretch(1)
        layout.addWidget(self._play_row_widget)

        odds_box = QGroupBox("赔率设置（含本金）")
        odds_layout = QVBoxLayout(odds_box)
        self._odds_edits: dict[str, QLineEdit] = {}
        for chunk in (PLAY_TYPE_OPTIONS[:4], PLAY_TYPE_OPTIONS[4:]):
            row = QHBoxLayout()
            for play in chunk:
                row.addWidget(QLabel(f"{play}:"))
                edit = QLineEdit(str(DEFAULT_ODDS.get(play, 1.0)))
                edit.setMaximumWidth(56)
                edit.textChanged.connect(self._emit_config)
                self._odds_edits[play] = edit
                row.addWidget(edit)
            row.addStretch(1)
            odds_layout.addLayout(row)
        layout.addWidget(odds_box)

        # --- Lock threshold ---
        lock_row = QHBoxLayout()
        lock_row.addWidget(QLabel("封盘提前:"))
        self._lock_spin = QSpinBox()
        self._lock_spin.setRange(5, 120)
        self._lock_spin.setValue(15)
        self._lock_spin.valueChanged.connect(self._emit_config)
        lock_row.addWidget(self._lock_spin)
        lock_row.addWidget(QLabel("秒"))
        lock_row.addStretch(1)
        layout.addLayout(lock_row)

        self._ai_pending_widget = QFrame()
        ai_pending_layout = QVBoxLayout(self._ai_pending_widget)
        ai_pending_layout.setContentsMargins(6, 6, 6, 6)
        self._ai_pending_label = QLabel()
        self._ai_pending_label.setWordWrap(True)
        ai_pending_layout.addWidget(self._ai_pending_label)
        ai_pending_actions = QHBoxLayout()
        self._ai_confirm_btn = QPushButton("确认下注")
        self._ai_confirm_btn.clicked.connect(self.ai_confirm_clicked.emit)
        self._ai_skip_btn = QPushButton("跳过本期")
        self._ai_skip_btn.clicked.connect(self.ai_skip_clicked.emit)
        ai_pending_actions.addWidget(self._ai_confirm_btn)
        ai_pending_actions.addWidget(self._ai_skip_btn)
        ai_pending_actions.addStretch(1)
        ai_pending_layout.addLayout(ai_pending_actions)
        self._ai_pending_widget.setVisible(False)
        layout.addWidget(self._ai_pending_widget)

        # --- Start/Stop buttons ---
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ 启动")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        self._stop_btn = QPushButton("■ 停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)
        self._status_label = QLabel("○ 已停止")
        self._status_label.setStyleSheet("color: #9e9e9e;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("实战统计:"))
        self._stats_label = QLabel("总下注: 0.00 | 总派彩: 0.00 | 总盈亏: 0.00\n当前倍投档: 1 | 当前连输: 0 | 已结算: 0 | 命中: 0 | 未中: 0\n状态: 已停止")
        self._stats_label.setWordWrap(True)
        layout.addWidget(self._stats_label)

        # --- Run log ---
        layout.addWidget(QLabel("运行日志:"))
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(150)
        self._log_edit.setPlaceholderText("策略运行日志将显示在这里...")
        layout.addWidget(self._log_edit)
        self._sync_strategy_visibility()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _show_strategy_help(self) -> None:
        QMessageBox.information(self, "\u81ea\u52a8\u4e0b\u6ce8\u7b56\u7565\u8bf4\u660e", strategy_help_text())

    def _open_ai_config_dialog(self) -> None:
        self._ai_config_dialog.load_config(self.get_config())
        if self._ai_config_dialog.exec() == QDialog.Accepted:
            self._emit_config()

    def _emit_config(self) -> None:
        self.config_changed.emit(self.get_config())

    def _on_strategy_changed(self) -> None:
        self._sync_strategy_visibility()
        self._emit_config()

    def _on_martingale_text_changed(self) -> None:
        self._sync_strategy_visibility()
        self._emit_config()

    def _on_mode_changed(self) -> None:
        self._sync_play_checkboxes_for_mode()
        self._emit_config()

    def _on_start(self) -> None:
        if (
            str(self._strategy_combo.currentData() or "") == "ai"
            and not self._ai_config_dialog.has_required_values()
        ):
            QMessageBox.information(self, "需要 AI 配置", "请先填写 AI 类型、Base URL、模型和 API Key。")
            self._open_ai_config_dialog()
            if not self._ai_config_dialog.has_required_values():
                return
        self.set_running(True)
        self.start_clicked.emit()

    def _on_stop(self) -> None:
        self.set_running(False)
        self.stop_clicked.emit()

    def _sync_play_checkboxes_for_mode(self) -> None:
        mode = str(self._mode_combo.currentData() or "size")
        allowed = {
            "size": {"大", "小"},
            "parity": {"单", "双"},
            "small_odd_big_even": {"小单", "大双"},
            "small_even_big_odd": {"小双", "大单"},
            "three_doors": {"小单", "大双", "小双", "大单"},
        }.get(mode, set(PLAY_TYPE_OPTIONS))
        defaults = {
            "size": {"大", "小"},
            "parity": {"单", "双"},
            "small_odd_big_even": {"小单", "大双"},
            "small_even_big_odd": {"小双", "大单"},
            "three_doors": {"小单", "大双", "小双"},
        }.get(mode, allowed)
        for play, cb in self._play_checkboxes.items():
            cb.blockSignals(True)
            cb.setEnabled(play in allowed)
            cb.setChecked(play in defaults if play in allowed else False)
            cb.blockSignals(False)

    def _sync_strategy_visibility(self) -> None:
        strategy_type = str(self._strategy_combo.currentData() or "trend_following")
        is_martingale = strategy_type == "martingale"
        is_ai = strategy_type == "ai"
        has_sequence = bool(self._parse_martingale_text(self._martingale_edit.text()))
        self._martingale_row_widget.setVisible(is_martingale)
        self._amount_row_widget.setVisible(not (is_martingale and has_sequence))
        self._ai_config_button.setVisible(is_ai)
        self._mode_row_widget.setVisible(not is_ai)
        self._play_row_widget.setVisible(not is_ai)
        if not is_ai:
            self.show_pending_ai_recommendation(None)

    @staticmethod
    def _parse_martingale_text(text: str) -> list[float]:
        values: list[float] = []
        for chunk in str(text or "").replace(",", "-").split("-"):
            try:
                value = float(chunk.strip())
            except ValueError:
                continue
            if value > 0:
                values.append(value)
        return values

    def _odds_from_inputs(self) -> dict[str, float]:
        odds = dict(DEFAULT_ODDS)
        for play, edit in self._odds_edits.items():
            try:
                value = float(edit.text().strip())
            except ValueError:
                continue
            if value > 0:
                odds[play] = value
        return odds

    @staticmethod
    def _format_amount(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else str(value)
