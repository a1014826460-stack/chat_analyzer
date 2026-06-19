from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout


PLAY_ORDER = ("大单", "小单", "大双", "小双", "大", "小", "单", "双")
ALL_GROUPS_LABEL = "全部群组"


class SummaryCheckDialog(QDialog):
    def __init__(self, summary_check: dict[str, object] | list[dict[str, object]] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("机器人汇总校验结果")
        self.resize(760, 520)
        self.summary_history: list[dict[str, object]] = []

        layout = QVBoxLayout(self)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("群组"))
        self.group_filter = QComboBox()
        self.group_filter.currentTextChanged.connect(self._on_group_changed)
        filter_row.addWidget(self.group_filter, 1)
        filter_row.addWidget(QLabel("期号"))
        self.period_filter = QComboBox()
        self.period_filter.currentTextChanged.connect(self._refresh_result_view)
        filter_row.addWidget(self.period_filter, 1)
        layout.addLayout(filter_row)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        layout.addWidget(self.result_view, 1)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.set_summary_check(summary_check or {})

    def set_summary_check(self, summary_check: dict[str, object] | list[dict[str, object]]) -> None:
        if isinstance(summary_check, list):
            history = [self._normalize_record(item) for item in summary_check]
        else:
            history = [self._normalize_record(summary_check)] if summary_check else []
        self.summary_history = [record for record in history if record.get("period") or record.get("by_play")]
        self._refresh_filters()

    def _normalize_record(self, summary_check: dict[str, object] | object) -> dict[str, object]:
        payload = dict(summary_check) if isinstance(summary_check, dict) else {}
        return {
            "group": str(payload.get("group", "") or ""),
            "period": str(payload.get("period", "") or ""),
            "software_totals": dict(payload.get("software_totals", {}) or {}),
            "robot_totals": dict(payload.get("robot_totals", {}) or {}),
            "by_play": dict(payload.get("by_play", {}) or {}),
        }

    def _refresh_filters(self) -> None:
        current_group = self.group_filter.currentText() if self.group_filter.count() else ALL_GROUPS_LABEL
        groups = sorted({str(item.get("group", "")).strip() for item in self.summary_history if str(item.get("group", "")).strip()})
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem(ALL_GROUPS_LABEL)
        self.group_filter.addItems(groups)
        if current_group in [ALL_GROUPS_LABEL, *groups]:
            self.group_filter.setCurrentText(current_group)
        self.group_filter.blockSignals(False)
        self._refresh_period_filter()
        self._refresh_result_view()

    def _records_for_selected_group(self) -> list[dict[str, object]]:
        selected_group = self.group_filter.currentText()
        if not selected_group or selected_group == ALL_GROUPS_LABEL:
            return list(self.summary_history)
        return [record for record in self.summary_history if str(record.get("group", "")).strip() == selected_group]

    def _refresh_period_filter(self) -> None:
        current_period = self.period_filter.currentText() if self.period_filter.count() else ""
        periods = [
            str(record.get("period", "")).strip()
            for record in self._records_for_selected_group()
            if str(record.get("period", "")).strip()
        ]
        deduped_periods: list[str] = []
        seen: set[str] = set()
        for period in periods:
            if period in seen:
                continue
            seen.add(period)
            deduped_periods.append(period)
        self.period_filter.blockSignals(True)
        self.period_filter.clear()
        self.period_filter.addItems(deduped_periods[:20])
        if current_period and current_period in deduped_periods[:20]:
            self.period_filter.setCurrentText(current_period)
        elif self.period_filter.count() > 0:
            self.period_filter.setCurrentIndex(0)
        self.period_filter.blockSignals(False)

    def _selected_record(self) -> dict[str, object]:
        period = self.period_filter.currentText().strip()
        records = self._records_for_selected_group()
        if period:
            for record in records:
                if str(record.get("period", "")).strip() == period:
                    return record
        return records[0] if records else {}

    def _refresh_result_view(self) -> None:
        self.result_view.setPlainText(self._format_summary_check(self._selected_record()))

    def _format_summary_check(self, summary_check: dict[str, object]) -> str:
        period = str(summary_check.get("period", "") or "")
        group = str(summary_check.get("group", "") or "")
        by_play = dict(summary_check.get("by_play", {}) or {})
        if not period or not by_play:
            return "当前没有可展示的机器人汇总校验结果。"

        lines = []
        if group:
            lines.append(f"群组: {group}")
        lines.append(f"期号: {period}")
        lines.append("")
        for play in PLAY_ORDER:
            row = dict(by_play.get(play, {}) or {})
            software_total = float(row.get("software_total", 0.0) or 0.0)
            robot_total = float(row.get("robot_total", 0.0) or 0.0)
            diff = float(row.get("diff", 0.0) or 0.0)
            status = "通过" if bool(row.get("within_tolerance", False)) else "异常"
            lines.append(
                f"{play} | 软件 {software_total:,.0f} | 机器人 {robot_total:,.0f} | 偏差 {diff:,.0f} | {status}"
            )
        return "\n".join(lines)

    def _on_group_changed(self) -> None:
        self._refresh_period_filter()
        self._refresh_result_view()
