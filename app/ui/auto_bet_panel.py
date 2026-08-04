from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QDateTimeEdit,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.auto_bet import (
    DEFAULT_ODDS,
    AutoBetRuntimeState,
    InjectRecord,
    PendingAiBet,
    StrategyConfig,
)
from app.services.history_fetchers import supported_history_fetch_counts
from app.ui.collapsible_section import CollapsibleSection


logger = logging.getLogger(__name__)

PLAY_TYPE_OPTIONS = ["大", "小", "单", "双", "大单", "小单", "大双", "小双"]
SITE_OPTIONS = ["pc28", "macao", "australia", "norway"]
STAT_CARD_STYLE = "background: #f7f9fb; border: 1px solid #dbe3ea; border-radius: 6px; padding: 6px 8px;"
BET_STRATEGY_OPTIONS = [
    ("\u8d8b\u52bf\u53cd\u6253", "trend_following"),
    ("\u56fa\u5b9a\u500d\u6295", "martingale"),
    ("\u5e73\u63a8", "flat"),
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
        "   \u4e09\u95e8\uff1a\u57fa\u4e8e\u6700\u8fd1\u5386\u53f2\u9891\u7387\uff0c\u81ea\u52a8\u6392\u9664\u5927\u5355\u3001\u5927\u53cc\u3001\u5c0f\u5355\u3001\u5c0f\u53cc\u4e2d\u51fa\u73b0\u6b21\u6570\u6700\u4f4e\u7684\u4e00\u95e8\uff0c\u518d\u4e0b\u6ce8\u5176\u4f59 3 \u95e8\u3002\n"
        "   \u4e0b\u6ce8\u53ea\u4f1a\u5728\u5f53\u671f\u5f00\u59cb 30 \u79d2\u540e\u5230\u5c01\u76d8\u524d\u7684\u65f6\u95f4\u7a97\u53e3\u5185\u6267\u884c\u3002"
    )

BET_MODE_OPTIONS = [
    ("压大小", "size"),
    ("压单双", "parity"),
    ("压小单大双", "small_odd_big_even"),
    ("压小双大单", "small_even_big_odd"),
    ("压三门", "three_doors"),
]

PLAY_PRESET_TYPES: dict[str, tuple[str, ...]] = {
    "size": ("大", "小"),
    "parity": ("单", "双"),
    "small_odd_big_even": ("小单", "大双"),
    "small_even_big_odd": ("小双", "大单"),
    "three_doors": ("小单", "大双", "小双", "大单"),
}


class AiConfigDialog(QDialog):
    """Configure server-owned AI strategy parameters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("策略配置")
        self.setModal(True)
        self.resize(500, 380)
        layout = QVBoxLayout(self)

        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("历史期数:"))
        self._history_combo = QComboBox()
        history_row.addWidget(self._history_combo)
        self._confirm_check = QCheckBox("每期下注前需确认")
        history_row.addWidget(self._confirm_check)
        history_row.addStretch(1)
        layout.addLayout(history_row)
        self.set_history_site("pc28")

        quant_row = QHBoxLayout()
        quant_row.addWidget(QLabel("最低置信度:"))
        self._confidence_spin = QSpinBox()
        self._confidence_spin.setRange(0, 100)
        self._confidence_spin.setValue(45)
        self._confidence_spin.setSuffix(" / 100")
        quant_row.addWidget(self._confidence_spin)
        quant_row.addWidget(QLabel("短期统计:"))
        self._accuracy_window_spin = QSpinBox()
        self._accuracy_window_spin.setRange(5, 100)
        self._accuracy_window_spin.setValue(20)
        self._accuracy_window_spin.setSuffix(" 条")
        quant_row.addWidget(self._accuracy_window_spin)
        quant_row.addStretch(1)
        layout.addLayout(quant_row)

        risk_row = QHBoxLayout()
        risk_row.addWidget(QLabel("止盈线:"))
        self._take_profit_spin = QDoubleSpinBox()
        self._take_profit_spin.setRange(0.0, 9_999_999.0)
        self._take_profit_spin.setDecimals(2)
        self._take_profit_spin.setSpecialValueText("关闭")
        risk_row.addWidget(self._take_profit_spin)
        risk_row.addWidget(QLabel("止损线:"))
        self._stop_loss_spin = QDoubleSpinBox()
        self._stop_loss_spin.setRange(0.0, 9_999_999.0)
        self._stop_loss_spin.setDecimals(2)
        self._stop_loss_spin.setSpecialValueText("关闭")
        risk_row.addWidget(self._stop_loss_spin)
        risk_row.addStretch(1)
        layout.addLayout(risk_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_server_mode(self, enabled: bool) -> None:
        del enabled
        self.setWindowTitle("策略配置")

    def load_config(self, config: StrategyConfig) -> None:
        self.set_history_site(config.site)
        self._set_history_count(config.ai_history_count)
        self._confirm_check.setChecked(config.ai_require_confirmation)
        self._confidence_spin.setValue(config.ai_confidence_threshold)
        self._accuracy_window_spin.setValue(config.ai_accuracy_window)
        self._take_profit_spin.setValue(config.take_profit_limit)
        self._stop_loss_spin.setValue(config.stop_loss_limit)

    def apply_to_config(self, config: StrategyConfig) -> None:
        config.ai_history_count = int(self._history_combo.currentData() or 50)
        config.ai_require_confirmation = self._confirm_check.isChecked()
        config.ai_confidence_threshold = self._confidence_spin.value()
        config.ai_accuracy_window = self._accuracy_window_spin.value()
        config.ai_prefer_recommendation_on_conflict = False
        config.take_profit_limit = self._take_profit_spin.value()
        config.stop_loss_limit = self._stop_loss_spin.value()

    def has_required_values(self) -> bool:
        return True

    def set_history_site(self, site: str) -> None:
        """Restrict selectable history counts to the active site's API capability."""
        previous = int(self._history_combo.currentData() or 50)
        self._history_combo.blockSignals(True)
        self._history_combo.clear()
        for count in supported_history_fetch_counts(site):
            self._history_combo.addItem(f"{count} 条", count)
        self._history_combo.blockSignals(False)
        self._set_history_count(previous)

    def _set_history_count(self, count: int) -> None:
        if self._history_combo.count() == 0:
            return
        choices = [int(self._history_combo.itemData(index)) for index in range(self._history_combo.count())]
        selected = min(choices, key=lambda value: (abs(value - int(count)), -value))
        self._history_combo.setCurrentIndex(self._history_combo.findData(selected))


class AutoBetPanel(CollapsibleSection):
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
    ai_history_clicked = Signal()
    runtime_log_filters_changed = Signal()
    runtime_log_load_more_clicked = Signal()
    _BEIJING_TZ = ZoneInfo("Asia/Shanghai")

    def __init__(self, parent: QWidget | None = None) -> None:
        # Standalone callers retain the historical visible panel behavior.
        # The main-window accordion collapses this primary module on startup.
        super().__init__("自动下注", expanded=True, parent=parent)
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
        self._sync_strategy_visibility()

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

    def runtime_log_refresh_interval_seconds(self) -> int:
        """Return zero when automatic server-log refresh is disabled."""
        return int(self._runtime_log_interval_combo.currentData() or 0)

    def runtime_log_filters(self) -> dict[str, object]:
        level = str(self._runtime_log_level_combo.currentData() or "")
        category = str(self._runtime_log_category_combo.currentData() or "")
        keyword = self._runtime_log_keyword_edit.text().strip()
        return {
            "level": level or None,
            "category": category or None,
            "keyword": keyword or None,
            "start_at": self._runtime_log_start_edit.dateTime().toPython().replace(tzinfo=self._BEIJING_TZ),
            "end_at": self._runtime_log_end_edit.dateTime().toPython().replace(tzinfo=self._BEIJING_TZ),
            "limit": 50,
        }

    def runtime_log_before_id(self) -> int | None:
        return self._runtime_log_next_before_id

    def runtime_log_row_count(self) -> int:
        return self._runtime_log_row_count

    def reset_runtime_log_pagination(self) -> None:
        self._runtime_log_next_before_id = None

    def apply_runtime_log_page(self, payload: dict[str, object], *, replace: bool) -> None:
        """Render one bounded server page without disturbing local event history."""
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return
        if replace:
            self._log_edit.clear()
            self._runtime_log_row_count = 0
        for item in items[:50]:
            if not isinstance(item, dict):
                continue
            created_at = self._format_runtime_log_time(item.get("created_at", ""))
            level = str(item.get("level", "INFO"))
            category = str(item.get("category", ""))
            message = str(item.get("message", ""))
            suffix = ""
            if item.get("request_url"):
                suffix += f" url={item['request_url']}"
            if item.get("duration_ms") is not None:
                suffix += f" {item['duration_ms']}ms"
            if item.get("status_code") is not None:
                suffix += f" HTTP {item['status_code']}"
            self._log_edit.append(f"{created_at} [{level}] [{category}] {message}{suffix}")
            self._runtime_log_row_count += 1
        next_before = payload.get("next_before_id") if isinstance(payload, dict) else None
        self._runtime_log_next_before_id = int(next_before) if next_before else None
        has_more = bool(payload.get("has_more")) if isinstance(payload, dict) else False
        self._runtime_log_load_more_button.setEnabled(has_more)
        self._runtime_log_load_more_button.setVisible(has_more)
        self._runtime_log_status_label.setText("" if items else "没有匹配的运行日志")

    @classmethod
    def _format_runtime_log_time(cls, raw: object) -> str:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(cls._BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(raw)[:19].replace("T", " ")

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
        win_rate = state.win_rounds / state.total_rounds if state.total_rounds else 0.0
        profit_color = "#198754" if state.total_profit > 0 else "#c0392b" if state.total_profit < 0 else "#5f6b73"
        status = state.halt_reason if state.halted else ("运行中" if self._running else "已停止")
        values = (
            ("待开奖下注", f"{state.pending_staked:.2f}", "#8a5a00"),
            ("已结算下注", f"{state.total_staked:.2f}", "#2f5f85"),
            ("已结算派彩", f"{state.total_payout:.2f}", "#2f5f85"),
            ("已结算盈亏", f"{state.total_profit:+.2f}", profit_color),
            ("命中率", f"{win_rate:.1%} ({state.win_rounds}/{state.total_rounds})", "#5f6b73"),
            ("最大连中", str(state.max_consecutive_wins), "#198754"),
            ("最大连输", str(state.max_consecutive_losses), "#c0392b"),
            ("当前连中", str(state.consecutive_wins), "#198754"),
            ("当前连输", str(state.consecutive_losses), "#c0392b"),
            ("当前倍投档", str(state.current_step + 1), "#6f42c1"),
            ("已结算", str(state.total_rounds), "#2f5f85"),
            ("命中", str(state.win_rounds), "#198754"),
            ("未中", str(state.lose_rounds), "#c0392b"),
            ("策略状态", status, "#c0392b" if state.halted else "#198754" if self._running else "#5f6b73"),
        )
        for label, (heading, text, text_color) in zip(self._runtime_stat_labels, values, strict=True):
            label.setText(f"<small>{heading}</small><br><b style='color:{text_color}'>{text}</b>")
        self._stats_label.setText(
            "待开奖下注: {pending:.2f} | 已结算下注: {staked:.2f} | 已结算派彩: {payout:.2f} | 已结算盈亏: {profit:.2f}".format(
                pending=state.pending_staked,
                staked=state.total_staked,
                payout=state.total_payout,
                profit=state.total_profit,
            )
        )
        self._update_martingale_peak(state)

    def _set_stat_cards(self, labels: list[QLabel], values: list[tuple[str, str, str]]) -> None:
        for index, label in enumerate(labels):
            if index < len(values):
                heading, value, color = values[index]
                label.setVisible(True)
                label.setText(f"<small>{heading}</small><br><b style='color:{color}'>{value}</b>")
            else:
                label.setVisible(False)

    def update_frequency_analysis(self, analysis: object | None) -> None:
        """Render the latest history-frequency snapshot without changing bet settings."""
        if analysis is None:
            self._frequency_analysis_label.setText("暂无可用历史概率分析")
            if hasattr(self, "_frequency_stat_labels"):
                self._set_stat_cards(self._frequency_stat_labels, [("概率分析", "暂无数据", "#5f6b73")])
            return

        def field(name: str, default: object = None) -> object:
            if isinstance(analysis, dict):
                return analysis.get(name, default)
            return getattr(analysis, name, default)

        number_probabilities = field("number_probabilities", {})
        play_probabilities = field("play_probabilities", {})
        if not isinstance(number_probabilities, dict):
            number_probabilities = {}
        if not isinstance(play_probabilities, dict):
            play_probabilities = {}
        selected_plays = "、".join(str(play) for play in (field("selected_plays", ()) or ())) or "-"
        should_bet = bool(field("should_bet", False))
        status = "本期将下注" if should_bet else "本期不下注"
        status_color = "#198754" if should_bet else "#c0392b"
        period = str(field("period", "") or "-")
        analyzed_at = field("analyzed_at", None)
        updated_at = analyzed_at.strftime("%H:%M:%S") if isinstance(analyzed_at, datetime) else str(field("updated_at", "-") or "-")
        site = field("site", "-") or "-"
        requested = field("requested_history_count", field("history_count", 0))
        sample = field("sample_count", 0)
        number_sample = field("number_sample_count", 0)
        thirteen = float(number_probabilities.get(13, number_probabilities.get("13", 0.0)))
        fourteen = float(number_probabilities.get(14, number_probabilities.get("14", 0.0)))
        excluded = field("excluded_play", "-") or "-"
        threshold = field("confidence_threshold", 0)
        highest = float(field("highest_selected_probability", 0.0))
        play_text = "  ".join(
            f"{play}: {float(play_probabilities.get(play, 0.0)):.1f}%"
            for play in PLAY_TYPE_OPTIONS
        )
        self._frequency_analysis_label.setText(
            "站点：{site}  目标期：{period}  更新时间：{updated}\n"
            "历史期数：{requested}  实际样本：{sample}  数值样本：{number_sample}\n"
            "13: {thirteen:.1f}%  14: {fourteen:.1f}%\n"
            "{plays}\n"
            "排除：{excluded}  压三门：{selected}  阈值：{threshold}%  最高：{highest:.1f}%  {status}".format(
                site=site,
                period=period,
                updated=updated_at,
                requested=requested,
                sample=sample,
                number_sample=number_sample,
                thirteen=thirteen,
                fourteen=fourteen,
                plays=play_text,
                excluded=excluded,
                selected=selected_plays,
                threshold=threshold,
                highest=highest,
                status=status,
            )
        )
        if hasattr(self, "_frequency_stat_labels"):
            values = [
                ("站点 / 目标期", f"{site} / {period}", "#2f5f85"),
                ("更新时间", updated_at, "#5f6b73"),
                ("历史 / 实际", f"{requested} / {sample}", "#5f6b73"),
                ("数值样本", str(number_sample), "#5f6b73"),
                ("13 概率", f"{thirteen:.1f}%", "#6f42c1"),
                ("14 概率", f"{fourteen:.1f}%", "#6f42c1"),
                ("排除玩法", str(excluded), "#c0392b"),
                ("压三门", selected_plays, "#198754"),
                ("阈值 / 最高", f"{threshold}% / {highest:.1f}%", "#8a5a00"),
                ("判断", status, status_color),
            ]
            for play in ("小单", "大双", "小双", "大单"):
                values.append((f"{play} 概率", f"{float(play_probabilities.get(play, 0.0)):.1f}%", "#2f5f85"))
            self._set_stat_cards(self._frequency_stat_labels, values)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if hasattr(self, "_runtime_stats_grid"):
            self._relayout_runtime_stat_cards()
        super().resizeEvent(event)

    def _relayout_runtime_stat_cards(self) -> None:
        """Keep three statistic cards per row and stretch the incomplete last row."""
        columns = 3
        grid_columns = 6
        self._runtime_stat_columns = columns
        while self._runtime_stats_grid.count():
            self._runtime_stats_grid.takeAt(0)
        rows = (len(self._runtime_stat_labels) + columns - 1) // columns
        complete_count = len(self._runtime_stat_labels) - (len(self._runtime_stat_labels) % columns)
        for index, label in enumerate(self._runtime_stat_labels[:complete_count]):
            self._runtime_stats_grid.addWidget(label, index // columns, (index % columns) * 2, 1, 2)
        for column in range(grid_columns):
            self._runtime_stats_grid.setColumnStretch(column, 1)
        last_row_count = len(self._runtime_stat_labels) % columns
        if last_row_count:
            last_row = rows - 1
            for index, label in enumerate(self._runtime_stat_labels[complete_count:]):
                self._runtime_stats_grid.addWidget(
                    label,
                    last_row,
                    index * (grid_columns // last_row_count),
                    1,
                    grid_columns // last_row_count,
                )
        self._runtime_stats_box.setMinimumHeight(rows * 58 + 42)

    def _update_martingale_peak(self, state: AutoBetRuntimeState) -> None:
        if state.martingale_peak_amount <= 0:
            self._martingale_peak_label.setText("本次运行尚未发送固定倍投下注。")
            return
        timestamp = state.martingale_peak_at.strftime("%Y-%m-%d %H:%M:%S") if state.martingale_peak_at else "-"
        self._martingale_peak_label.setText(
            f"最高实际下注：第 {state.martingale_peak_step + 1} 档 / "
            f"{self._format_amount(state.martingale_peak_amount)}\n"
            f"首次达到时间：{timestamp} | 站点：{state.martingale_peak_site or '-'} | "
            f"期数：{state.martingale_peak_period or '-'}"
        )

    def update_ai_statistics(self, summary: dict) -> None:
        overall = summary.get("overall", {})
        short = summary.get("short", {})
        streak = summary.get("streak", {})
        streak_name = "连中" if streak.get("result") == "hit" else (
            "连错" if streak.get("result") == "miss" else "无连续记录"
        )
        settled_count = int(summary.get("settled_count", 0))
        short_count = int(short.get("count", 0))
        values = (
            ("AI 已结算", str(settled_count), "#2f5f85"),
            ("总体方向命中", self._format_accuracy(overall, "direction", settled_count), "#198754"),
            ("总体精确命中", self._format_accuracy(overall, "exact", settled_count), "#2f5f85"),
            (
                f"近 {int(short.get('window', 20))} 条方向",
                self._format_accuracy(short, "direction", short_count),
                "#198754",
            ),
            (
                f"近 {int(short.get('window', 20))} 条精确",
                self._format_accuracy(short, "exact", short_count),
                "#2f5f85",
            ),
            (streak_name, str(int(streak.get("count", 0))), "#198754" if streak_name == "连中" else "#c0392b"),
        )
        for label, (heading, text, text_color) in zip(self._ai_stat_labels, values, strict=True):
            label.setText(f"<small>{heading}</small><br><b style='color:{text_color}'>{text}</b>")

    @staticmethod
    def _format_accuracy(summary: dict, kind: str, count: int) -> str:
        hits = int(summary.get(f"{kind}_hits", round(float(summary.get(f"{kind}_accuracy", 0.0)) * count)))
        accuracy = float(summary.get(f"{kind}_accuracy", 0.0))
        return f"{accuracy:.1%} ({hits}/{count})"

    @staticmethod
    def format_ai_history(records: list) -> str:
        if not records:
            return "暂无 AI 预测记录。"
        lines = []
        for record in records:
            if isinstance(record, dict):
                created_at = str(record.get("created_at", "") or "-").replace("T", " ")[:19]
                site = str(record.get("site", "-") or "-")
                period = str(record.get("period", "-") or "-")
                event_type = str(record.get("event_type", "AI") or "AI")
                message = str(record.get("message", "-") or "-")
                lines.append(f"{created_at} [{site} {period}] {event_type}\n{message}")
                continue
            action = "预测 " + record.play_type if record.action == "bet" else "跳过本期"
            actual = record.actual_result or "待开奖"
            if record.actual_result:
                direction = "方向命中" if record.direction_hit else "方向未中"
                exact = "精确命中" if record.exact_hit else "精确未中"
                outcome = f"{direction} / {exact}"
            else:
                outcome = record.status
            lines.append(
                f"{record.created_at:%Y-%m-%d %H:%M:%S} [{record.site} {record.period}] "
                f"{action} | 置信度 {record.confidence}/100 | 实际 {actual} | {outcome}\n"
                f"量化：{record.quant_rationale or '-'}；结论：{record.reason or '-'}"
            )
        return "\n\n".join(lines)

    def show_ai_history(self, records: list) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("AI 预测历史")
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        content = QTextEdit()
        content.setReadOnly(True)
        content.setPlainText(self.format_ai_history(records))
        layout.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _set_config_controls_enabled(self, enabled: bool) -> None:
        controls = [
            self._strategy_combo,
            self._target_group_list,
            self._select_all_groups_button,
            self._clear_groups_button,
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
            self._server_pending_bet_id = None
            return
        self._ai_pending_key = (pending.site, pending.period)
        self._ai_pending_label.setText(
            "\u672c\u671f AI \u5efa\u8bae [{site} {period}]\uff1a{play}{amount}\n"
            "置信度：{confidence}/100\n{conflict}量化依据：{quant}\n\u7406\u7531\uff1a{reason}".format(
                site=pending.site,
                period=pending.period,
                play=pending.play_type,
                amount=self._format_amount(pending.amount),
                reason=pending.reason,
                confidence=pending.confidence,
                conflict=(
                    f"⚠ 与推荐玩法 {', '.join(pending.recommended_plays) or '无'} 冲突，请选择是否使用 AI 建议。\n"
                    if pending.has_play_conflict else ""
                ),
                quant=pending.quant_rationale,
            )
        )
        self._ai_pending_widget.setVisible(True)

    def show_pending_server_bet(self, pending: PendingAiBet | None, *, order_id: int | None = None) -> None:
        """Show a server-created order without presenting it as an AI proposal."""
        if pending is None:
            self.show_pending_ai_recommendation(None)
            return
        self._server_pending_bet_id = int(order_id) if order_id is not None else None
        self._ai_pending_key = (pending.site, pending.period)
        self._ai_pending_label.setText(
            "服务器待确认下注 [{site} {period}]：{play}{amount}\n"
            "说明：{reason}".format(
                site=pending.site,
                period=pending.period,
                play=pending.play_type,
                amount=self._format_amount(pending.amount),
                reason=pending.reason,
            )
        )
        self._ai_pending_widget.setVisible(True)

    @property
    def server_pending_bet_id(self) -> int | None:
        return getattr(self, "_server_pending_bet_id", None)

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
        self._ai_config_dialog.set_history_site(value)
        if changed:
            self._emit_config()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = self.content_layout()
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
        mode_row.addWidget(QLabel("快速选取玩法:"))
        self._mode_combo = QComboBox()
        for label, value in BET_MODE_OPTIONS:
            self._mode_combo.addItem(label, value)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo, 1)
        layout.addWidget(self._mode_row_widget)

        # --- Target groups ---
        target_header = QHBoxLayout()
        target_header.addWidget(QLabel("目标群组:"))
        target_header.addStretch(1)
        self._select_all_groups_button = QPushButton("全选")
        self._select_all_groups_button.clicked.connect(self._select_all_target_groups)
        target_header.addWidget(self._select_all_groups_button)
        self._clear_groups_button = QPushButton("全不选")
        self._clear_groups_button.clicked.connect(self._clear_target_groups)
        target_header.addWidget(self._clear_groups_button)
        layout.addLayout(target_header)
        self._target_group_list = QListWidget()
        self._target_group_list.setMaximumHeight(80)
        self._target_group_list.itemChanged.connect(self._emit_config)
        layout.addWidget(self._target_group_list)
        self._target_group_lock_hint = QLabel("\u8fd0\u884c\u4e2d\u5df2\u9501\u5b9a\u76ee\u6807\u7fa4\u7ec4\uff0c\u5982\u9700\u4fee\u6539\u8bf7\u5148\u505c\u6b62\u81ea\u52a8\u4e0b\u6ce8\u3002")
        self._target_group_lock_hint.setStyleSheet("color: #d35400; font-weight: bold;")
        self._target_group_lock_hint.setWordWrap(True)
        self._target_group_lock_hint.setVisible(False)
        layout.addWidget(self._target_group_lock_hint)

        # --- Trend-reversal parameters ---
        self._trend_parameters_widget = QWidget()
        grid = QHBoxLayout(self._trend_parameters_widget)
        grid.setContentsMargins(0, 0, 0, 0)
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
        layout.addWidget(self._trend_parameters_widget)

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

        self._server_ai_status_label = QLabel("AI 自动决策：由服务器托管")
        self._server_ai_status_label.setWordWrap(True)
        self._server_ai_status_label.setStyleSheet(
            "background: #eef6ff; border: 1px solid #cfe2ff; "
            "border-radius: 6px; padding: 6px 8px; color: #2f5f85;"
        )
        self._server_ai_status_label.setToolTip("服务器统一配置模型与密钥；客户端只提交策略、确认或跳过订单。")
        layout.addWidget(self._server_ai_status_label)

        # --- Play types ---
        self._play_row_widget = QWidget()
        play_row = QVBoxLayout(self._play_row_widget)
        play_row.setContentsMargins(0, 0, 0, 0)
        self._play_label = QLabel("推荐玩法:")
        play_row.addWidget(self._play_label)
        self._play_grid = QGridLayout()
        self._play_grid.setContentsMargins(0, 0, 0, 0)
        self._play_grid.setHorizontalSpacing(10)
        self._play_grid.setVerticalSpacing(4)
        self._play_checkboxes: dict[str, QCheckBox] = {}
        for index, pt in enumerate(PLAY_TYPE_OPTIONS):
            cb = QCheckBox(pt)
            cb.setChecked(pt in ("大", "小"))
            cb.toggled.connect(self._emit_config)
            self._play_checkboxes[pt] = cb
            self._play_grid.addWidget(cb, index // 4, index % 4)
        for column in range(4):
            self._play_grid.setColumnStretch(column, 1)
        play_row.addLayout(self._play_grid)
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
        self._lock_spin.setRange(20, 60)
        self._lock_spin.setValue(20)
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

        self._frequency_analysis_box = QGroupBox("概率分析")
        frequency_layout = QVBoxLayout(self._frequency_analysis_box)
        frequency_layout.setContentsMargins(10, 14, 10, 10)
        self._frequency_stats_grid = QGridLayout()
        self._frequency_stats_grid.setContentsMargins(0, 0, 0, 0)
        self._frequency_stats_grid.setHorizontalSpacing(8)
        self._frequency_stats_grid.setVerticalSpacing(8)
        self._frequency_stat_labels: list[QLabel] = []
        for index in range(14):
            label = QLabel()
            label.setMinimumWidth(104)
            label.setMinimumHeight(50)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            label.setStyleSheet(STAT_CARD_STYLE)
            label.setTextFormat(Qt.RichText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._frequency_stat_labels.append(label)
            self._frequency_stats_grid.addWidget(label, index // 3, index % 3)
        frequency_layout.addLayout(self._frequency_stats_grid)
        self._frequency_analysis_label = QLabel("暂无可用历史概率分析")
        self._frequency_analysis_label.setVisible(False)
        self._frequency_analysis_label.setWordWrap(True)
        self._frequency_analysis_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        frequency_layout.addWidget(self._frequency_analysis_label)
        layout.addWidget(self._frequency_analysis_box)

        self._runtime_stats_box = QGroupBox("实战统计")
        self._runtime_stats_box.setMinimumHeight(150)
        stats_layout = QVBoxLayout(self._runtime_stats_box)
        stats_layout.setContentsMargins(10, 14, 10, 10)
        self._runtime_stats_grid = QGridLayout()
        self._runtime_stats_grid.setContentsMargins(0, 0, 0, 0)
        self._runtime_stats_grid.setHorizontalSpacing(8)
        self._runtime_stats_grid.setVerticalSpacing(8)
        self._runtime_stat_columns = -1
        self._runtime_stat_labels: list[QLabel] = []
        for _ in range(14):
            label = QLabel()
            label.setMinimumWidth(104)
            label.setMinimumHeight(50)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            label.setStyleSheet(STAT_CARD_STYLE)
            label.setTextFormat(Qt.RichText)
            self._runtime_stat_labels.append(label)
        stats_layout.addLayout(self._runtime_stats_grid)
        # Retained for compatibility; the values now have dedicated statistic cards.
        self._stats_detail_label = QLabel()
        self._stats_detail_label.setVisible(False)
        stats_layout.addWidget(self._stats_detail_label)
        self._stats_label = QLabel("待开奖下注: 0.00 | 已结算下注: 0.00 | 已结算派彩: 0.00 | 已结算盈亏: 0.00")
        self._stats_label.setVisible(False)
        stats_layout.addWidget(self._stats_label)
        layout.addWidget(self._runtime_stats_box)
        self._relayout_runtime_stat_cards()

        ai_stats_box = QGroupBox("AI 已结算统计")
        ai_stats_layout = QGridLayout(ai_stats_box)
        self._ai_stat_labels: list[QLabel] = []
        for index in range(6):
            label = QLabel()
            label.setMinimumWidth(116)
            label.setStyleSheet(STAT_CARD_STYLE)
            label.setTextFormat(Qt.RichText)
            self._ai_stat_labels.append(label)
            ai_stats_layout.addWidget(label, index // 3, index % 3)
        layout.addWidget(ai_stats_box)
        self.update_ai_statistics({})

        self._martingale_peak_box = QGroupBox("本次固定倍投峰值")
        martingale_peak_layout = QVBoxLayout(self._martingale_peak_box)
        self._martingale_peak_label = QLabel("本次运行尚未发送固定倍投下注。")
        self._martingale_peak_label.setWordWrap(True)
        martingale_peak_layout.addWidget(self._martingale_peak_label)
        self._martingale_peak_box.setVisible(False)
        layout.addWidget(self._martingale_peak_box)

        self._ai_history_button = QPushButton("查看 AI 预测历史")
        self._ai_history_button.clicked.connect(self.ai_history_clicked.emit)
        layout.addWidget(self._ai_history_button)

        # --- Run log ---
        layout.addWidget(QLabel("运行日志:"))
        runtime_log_filters = QHBoxLayout()
        runtime_log_filters.addWidget(QLabel("级别:"))
        self._runtime_log_level_combo = QComboBox()
        self._runtime_log_level_combo.addItem("全部", "")
        for level in ("DEBUG", "INFO", "WARN", "ERROR"):
            self._runtime_log_level_combo.addItem(level, level)
        runtime_log_filters.addWidget(self._runtime_log_level_combo)
        runtime_log_filters.addWidget(QLabel("分类:"))
        self._runtime_log_category_combo = QComboBox()
        for label, category in (
            ("下注与结算", "strategy"),
            ("全部", ""),
            ("用户操作", "user_action"),
            ("系统", "system"),
            ("第三方", "third_party"),
            ("异常", "exception"),
        ):
            self._runtime_log_category_combo.addItem(label, category)
        runtime_log_filters.addWidget(self._runtime_log_category_combo)
        runtime_log_filters.addWidget(QLabel("关键词:"))
        self._runtime_log_keyword_edit = QLineEdit()
        self._runtime_log_keyword_edit.setPlaceholderText("搜索日志")
        self._runtime_log_keyword_edit.editingFinished.connect(self._on_runtime_log_filters_changed)
        runtime_log_filters.addWidget(self._runtime_log_keyword_edit, 1)
        runtime_log_filters.addWidget(QLabel("时间:"))
        self._runtime_log_start_edit = QDateTimeEdit()
        self._runtime_log_start_edit.setDisplayFormat("MM-dd HH:mm")
        self._runtime_log_start_edit.setCalendarPopup(True)
        self._runtime_log_start_edit.setDateTime(QDateTime.currentDateTime().addSecs(-24 * 3600))
        self._runtime_log_start_edit.editingFinished.connect(self._on_runtime_log_filters_changed)
        runtime_log_filters.addWidget(self._runtime_log_start_edit)
        self._runtime_log_end_edit = QDateTimeEdit()
        self._runtime_log_end_edit.setDisplayFormat("MM-dd HH:mm")
        self._runtime_log_end_edit.setCalendarPopup(True)
        self._runtime_log_end_edit.setDateTime(QDateTime.currentDateTime())
        self._runtime_log_end_edit.editingFinished.connect(self._on_runtime_log_filters_changed)
        runtime_log_filters.addWidget(self._runtime_log_end_edit)
        runtime_log_filters.addWidget(QLabel("刷新:"))
        self._runtime_log_interval_combo = QComboBox()
        for label, seconds in (("关闭", 0), ("5 秒", 5), ("10 秒", 10), ("30 秒", 30), ("60 秒", 60)):
            self._runtime_log_interval_combo.addItem(label, seconds)
        self._runtime_log_interval_combo.setCurrentIndex(1)
        self._runtime_log_level_combo.currentIndexChanged.connect(self._on_runtime_log_filters_changed)
        self._runtime_log_category_combo.currentIndexChanged.connect(self._on_runtime_log_filters_changed)
        self._runtime_log_interval_combo.currentIndexChanged.connect(self._on_runtime_log_filters_changed)
        runtime_log_filters.addWidget(self._runtime_log_interval_combo)
        layout.addLayout(runtime_log_filters)
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        # Keep the visible document bounded even if a long-running service
        # emits more status records than its own in-memory log retains.
        self._log_edit.document().setMaximumBlockCount(500)
        self._log_edit.setMaximumHeight(150)
        self._log_edit.setPlaceholderText("策略运行日志将显示在这里...")
        layout.addWidget(self._log_edit)
        runtime_log_actions = QHBoxLayout()
        self._runtime_log_load_more_button = QPushButton("加载更多")
        self._runtime_log_load_more_button.clicked.connect(self.runtime_log_load_more_clicked.emit)
        self._runtime_log_load_more_button.setVisible(False)
        runtime_log_actions.addWidget(self._runtime_log_load_more_button)
        self._runtime_log_status_label = QLabel()
        runtime_log_actions.addWidget(self._runtime_log_status_label, 1)
        layout.addLayout(runtime_log_actions)
        self._runtime_log_next_before_id: int | None = None
        self._runtime_log_row_count = 0
        self._sync_strategy_visibility()

    def _on_runtime_log_filters_changed(self) -> None:
        self.reset_runtime_log_pagination()
        self.runtime_log_filters_changed.emit()

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
        preset = PLAY_PRESET_TYPES.get(str(self._mode_combo.currentData() or ""), ())
        if preset:
            for play, checkbox in self._play_checkboxes.items():
                checkbox.blockSignals(True)
                checkbox.setChecked(play in preset)
                checkbox.blockSignals(False)
        self._emit_config()

    def _set_target_group_checks(self, checked: bool) -> None:
        self._target_group_list.blockSignals(True)
        for index in range(self._target_group_list.count()):
            self._target_group_list.item(index).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._target_group_list.blockSignals(False)
        self._emit_config()

    def _select_all_target_groups(self) -> None:
        self._set_target_group_checks(True)

    def _clear_target_groups(self) -> None:
        self._set_target_group_checks(False)

    def _on_start(self) -> None:
        validation_errors = self.get_config().start_validation_errors(
            require_ai_credentials=not getattr(self, "_server_mode", False),
        )
        if validation_errors:
            QMessageBox.warning(self, "无法启动自动下注", "\n".join(validation_errors))
            return
        self.set_running(True)
        self.start_clicked.emit()

    def set_server_mode(self, enabled: bool) -> None:
        """Use the server AI configuration instead of a client API key."""
        self._server_mode = bool(enabled)
        self._sync_strategy_visibility()

    def _on_stop(self) -> None:
        self.set_running(False)
        self.stop_clicked.emit()

    def _sync_strategy_visibility(self) -> None:
        strategy_type = str(self._strategy_combo.currentData() or "trend_following")
        is_martingale = strategy_type == "martingale"
        has_sequence = bool(self._parse_martingale_text(self._martingale_edit.text()))
        self._trend_parameters_widget.setVisible(strategy_type == "trend_following")
        self._martingale_row_widget.setVisible(is_martingale)
        self._amount_row_widget.setVisible(not (is_martingale and has_sequence))
        self._martingale_peak_box.setVisible(is_martingale)
        server_mode = bool(getattr(self, "_server_mode", False))
        self._ai_config_dialog.set_server_mode(server_mode)
        self._ai_config_button.setVisible(True)
        self._ai_config_button.setText("策略配置" if server_mode else "AI 配置")
        self._ai_config_button.setToolTip(
            "配置历史期数、置信度、每期确认、止盈止损等策略参数" if server_mode
            else "配置 AI 类型、Base URL、模型、API Key 和确认方式"
        )
        self._server_ai_status_label.setVisible(server_mode)
        self._mode_row_widget.setVisible(True)
        self._play_row_widget.setVisible(True)

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
        odds: dict[str, float] = {}
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
