from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


logger = logging.getLogger(__name__)

ALLOWED_CHART_PLAYS = ("大单", "小单", "大双", "小双", "大", "小", "单", "双")
THEME_COLORS = ["#34dbcb", "#34c2db", "#3498db", "#346edb", "#3445db"]


@dataclass(frozen=True)
class ChartLayer:
    color: str
    values: dict[str, float]
    groups: frozenset[str] = frozenset()
    group_values: dict[str, dict[str, float]] | None = None


class VerticalStackedBarChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.categories = list(ALLOWED_CHART_PLAYS)
        self.layers: list[ChartLayer] = []
        self.current_totals = self._zero_totals()
        self.setMinimumHeight(260)

    def set_layers(self, layers: list[ChartLayer], current_totals: dict[str, float]) -> None:
        self.layers = [
            ChartLayer(layer.color, {category: float(layer.values.get(category, 0.0) or 0.0) for category in self.categories})
            for layer in layers
        ]
        self.current_totals = self._normalized_totals(current_totals)
        self.update()

    def set_totals(self, totals: dict[str, float]) -> None:
        normalized = self._normalized_totals(totals)
        layers = [ChartLayer(THEME_COLORS[0], normalized)] if any(normalized.values()) else []
        self.set_layers(layers, normalized)

    def _normalized_totals(self, totals: dict[str, float]) -> dict[str, float]:
        normalized = self._zero_totals()
        for category in self.categories:
            normalized[category] = max(0.0, float(totals.get(category, 0.0) or 0.0))
        return normalized

    def _zero_totals(self) -> dict[str, float]:
        return {category: 0.0 for category in self.categories}

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfaf7"))

        rect = self.rect().adjusted(18, 14, -18, -14)
        painter.setPen(QPen(QColor("#2f2b25")))
        title_font = QFont("Microsoft YaHei UI", 10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(rect.left(), rect.top(), "玩法下注堆积柱形图")

        if not self.layers or not any(self.current_totals.values()):
            painter.setPen(QColor("#8f8578"))
            painter.drawText(rect, Qt.AlignCenter, "暂无可绘制的下注数据")
            return

        chart_left = rect.left() + 54
        chart_top = rect.top() + 34
        chart_right = rect.right() - 12
        chart_bottom = rect.bottom() - 46
        chart_width = max(1, chart_right - chart_left)
        chart_height = max(1, chart_bottom - chart_top)
        baseline = chart_bottom
        max_value = max(self.current_totals.values()) or 1.0

        axis_pen = QPen(QColor("#d8d0c5"))
        painter.setPen(axis_pen)
        painter.drawLine(chart_left, chart_top, chart_left, chart_bottom)
        painter.drawLine(chart_left, chart_bottom, chart_right, chart_bottom)

        grid_font = QFont("Microsoft YaHei UI", 8)
        painter.setFont(grid_font)
        for step in range(1, 5):
            y = chart_bottom - int(chart_height * step / 4)
            painter.setPen(QPen(QColor("#ebe5dc")))
            painter.drawLine(chart_left, y, chart_right, y)
            painter.setPen(QColor("#8f8578"))
            painter.drawText(rect.left(), y + 4, f"{max_value * step / 4:,.0f}")

        slot_width = chart_width / max(1, len(self.categories))
        bar_width = max(12.0, min(46.0, slot_width * 0.54))
        label_font = QFont("Microsoft YaHei UI", 8)
        painter.setFont(label_font)

        for index, category in enumerate(self.categories):
            center_x = chart_left + slot_width * index + slot_width / 2
            left = center_x - bar_width / 2
            stacked_height = 0.0
            for layer in self.layers:
                value = float(layer.values.get(category, 0.0) or 0.0)
                if value <= 0:
                    continue
                height = chart_height * (value / max_value)
                top = baseline - stacked_height - height
                painter.fillRect(QRectF(left, top, bar_width, height), QColor(layer.color))
                stacked_height += height

            total = self.current_totals.get(category, 0.0)
            if total > 0:
                painter.setPen(QColor("#51483f"))
                painter.drawText(QRectF(left - 18, baseline - stacked_height - 20, bar_width + 36, 16), Qt.AlignCenter, f"{total:,.0f}")

            painter.setPen(QColor("#3a332d"))
            painter.drawText(QRectF(center_x - slot_width / 2, baseline + 8, slot_width, 22), Qt.AlignCenter, category)


BarChartWidget = VerticalStackedBarChartWidget


class ChartWindow(QWidget):
    groups_changed = Signal()

    def __init__(self, title: str = "投注图表", parent: QWidget | None = None, show_close: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._rows: list[dict[str, object]] = []
        self._period_rows: list[dict[str, object]] = []
        self._period_row_indexes: dict[tuple[object, ...], int] = {}
        self._status_mode = "empty"
        self._status_text = "暂无投注数据"
        self._last_totals = self._zero_totals()
        self._last_group_totals: dict[str, dict[str, float]] = {}
        self._last_period_key: tuple[str, ...] | None = None
        self._next_color_index = 0
        self._all_layers: list[ChartLayer] = []
        self._group_selection_initialized = False

        root = QVBoxLayout(self)

        self.status_label = QLabel(self._status_text)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("emphasisLabel")
        root.addWidget(self.status_label)

        self.bar_chart = VerticalStackedBarChartWidget()
        root.addWidget(self.bar_chart, 3)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self._build_stats_panel(), 2)
        bottom_row.addWidget(self._build_groups_panel(), 1)
        root.addLayout(bottom_row, 2)

        self._stack_timer = QTimer(self)
        self._stack_timer.setInterval(5000)
        self._stack_timer.timeout.connect(self._append_increment_layer)
        self._stack_timer.start()

        if show_close:
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.hide)
            root.addWidget(close_btn, alignment=Qt.AlignLeft)

    def _build_stats_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.addWidget(QLabel("实时统计文本"))
        self.stats_text_view = QTextEdit()
        self.stats_text_view.setReadOnly(True)
        self.stats_text_view.setMinimumHeight(140)
        layout.addWidget(self.stats_text_view)
        return panel

    def _build_groups_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(QLabel("可见群组"))

        buttons = QHBoxLayout()
        self.group_all_btn = QPushButton("全选")
        self.group_invert_btn = QPushButton("反选")
        self.group_clear_btn = QPushButton("清空")
        self.group_all_btn.clicked.connect(self._select_all_groups)
        self.group_invert_btn.clicked.connect(self._invert_groups)
        self.group_clear_btn.clicked.connect(self._clear_groups)
        buttons.addWidget(self.group_all_btn)
        buttons.addWidget(self.group_invert_btn)
        buttons.addWidget(self.group_clear_btn)
        layout.addLayout(buttons)

        self.group_list = QListWidget()
        self.group_list.itemChanged.connect(self._on_group_item_changed)
        self.group_list.setMinimumHeight(140)
        layout.addWidget(self.group_list)
        return panel

    def set_rows(self, rows: list[dict[str, object]]) -> None:
        incoming = list(rows)
        self._merge_period_rows(incoming)
        self._sync_group_list(self._period_rows)
        self._refresh_activity()
        logger.debug("Chart rows updated: %d rows", len(rows))

    def replace_rows(self, rows: list[dict[str, object]]) -> None:
        self._period_rows = []
        self._period_row_indexes = {}
        self._group_selection_initialized = False
        self._reset_layers()
        self._last_period_key = None
        self.set_rows(rows)

    def update_activity(self, rows: list[dict[str, object]]) -> None:
        self._merge_period_rows(list(rows))
        self._append_increment_layer()
        self._refresh_activity()

    def set_status(self, mode: str, text: str | None = None) -> None:
        self._status_mode = mode
        if text is not None:
            self._status_text = text
        elif mode == "running":
            self._status_text = "实时刷新运行中"
        elif mode == "locked":
            self._status_text = "当前期数统计已锁定"
        elif mode == "waiting":
            self._status_text = "等待下一期"
        else:
            self._status_text = "暂无投注数据"
        self.status_label.setText(self._status_text)

    def set_status_seconds(self, seconds: int) -> None:
        if self._status_mode == "running":
            self.status_label.setText(f"实时刷新运行中 · 距锁定 {max(0, int(seconds)):,} 秒")

    def selected_groups(self) -> set[str]:
        groups: set[str] = set()
        for index in range(self.group_list.count()):
            item = self.group_list.item(index)
            if item.checkState() == Qt.Checked:
                groups.add(str(item.data(Qt.UserRole) or item.text()))
        return groups

    def _sync_group_list(self, rows: list[dict[str, object]]) -> None:
        selected = self.selected_groups()
        groups = sorted({str(row.get("group", "")).strip() for row in rows if str(row.get("group", "")).strip()})
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for group in groups:
            item = QListWidgetItem(group)
            item.setData(Qt.UserRole, group)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            should_check = not self._group_selection_initialized or group in selected
            item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
            self.group_list.addItem(item)
        self.group_list.blockSignals(False)
        if groups:
            self._group_selection_initialized = True

    def _refresh_activity(self) -> None:
        totals = self._visible_totals_from_layers()
        self._refresh_stats_text()
        self.bar_chart.set_layers(self._visible_layers(), totals)

    def _refresh_stats_text(self) -> None:
        lines: list[str] = []
        scrollbar = self.stats_text_view.verticalScrollBar()
        scroll_value = scrollbar.value()
        for row in reversed(self._filtered_allowed_rows()[-200:]):
            ts = row.get("time")
            ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else "-"
            display_name = str(row.get("bettor") or row.get("nickname") or row.get("username") or "").strip()
            lines.append(
                " - ".join(
                    [
                        ts_text,
                        str(row.get("group", "")).strip(),
                        display_name,
                        str(row.get("play", "")).strip(),
                        f"{float(row.get('amount', 0) or 0):,.0f}",
                    ]
                )
                + self._stats_row_suffix(row)
            )
        self.stats_text_view.setPlainText("\n".join(lines))
        scrollbar.setValue(min(scroll_value, scrollbar.maximum()))

    def _stats_row_suffix(self, row: dict[str, object]) -> str:
        if str(row.get("source_kind", "") or "").strip() != "receipt":
            return ""
        sender_id = str(row.get("sender_id", "") or "").strip()
        source_kind = str(row.get("source_kind", "") or "").strip()
        parts: list[str] = []
        if sender_id:
            parts.append(f"sender_id={sender_id}")
        if source_kind:
            parts.append(f"source={source_kind}")
        return f" | {' | '.join(parts)}" if parts else ""

    def _append_increment_layer(self) -> None:
        period_key = self._period_key()
        current_totals = self._all_allowed_totals()
        if period_key != self._last_period_key:
            self._reset_layers()
            self._last_period_key = period_key

        increments = {
            category: max(0.0, current_totals[category] - self._last_totals[category])
            for category in ALLOWED_CHART_PLAYS
        }
        group_totals = self._all_allowed_totals_by_group()
        group_increments = self._group_increments(group_totals)
        if any(increments.values()):
            color = THEME_COLORS[self._next_color_index % len(THEME_COLORS)]
            self._next_color_index += 1
            self._all_layers.append(
                ChartLayer(
                    color=color,
                    values=increments,
                    groups=frozenset(group_increments),
                    group_values=group_increments,
                )
            )
            self._last_totals = {
                category: max(self._last_totals[category], current_totals[category])
                for category in ALLOWED_CHART_PLAYS
            }
            self._last_group_totals = self._max_group_totals(self._last_group_totals, group_totals)
        self._refresh_activity()

    def _reset_layers(self) -> None:
        self._last_totals = self._zero_totals()
        self._last_group_totals = {}
        self._next_color_index = 0
        self._all_layers = []
        self.bar_chart.set_layers([], self._last_totals)

    def _period_key(self) -> tuple[str, ...]:
        return tuple(sorted({str(row.get("period", "")).strip() for row in self._period_rows if str(row.get("period", "")).strip()}))

    def _filtered_rows(self) -> list[dict[str, object]]:
        selected = self.selected_groups()
        if self.group_list.count() > 0 and not selected:
            return []
        return [row for row in self._period_rows if not selected or str(row.get("group", "")) in selected]

    def _filtered_allowed_rows(self) -> list[dict[str, object]]:
        return [row for row in self._filtered_rows() if str(row.get("play", "")).strip() in ALLOWED_CHART_PLAYS]

    def _all_allowed_totals(self) -> dict[str, float]:
        totals = self._zero_totals()
        for group_totals in self._all_allowed_totals_by_group().values():
            for category in ALLOWED_CHART_PLAYS:
                totals[category] += group_totals[category]
        return totals

    def _all_allowed_totals_by_group(self) -> dict[str, dict[str, float]]:
        totals: dict[str, dict[str, float]] = {}
        for row in self._period_rows:
            play = str(row.get("play", "")).strip()
            group = str(row.get("group", "")).strip()
            if play not in ALLOWED_CHART_PLAYS or not group:
                continue
            group_totals = totals.setdefault(group, self._zero_totals())
            group_totals[play] += float(row.get("amount", 0) or 0)
        return totals

    def _visible_layers(self) -> list[ChartLayer]:
        selected = self.selected_groups()
        if self.group_list.count() > 0 and not selected:
            return []
        if not selected:
            return list(self._all_layers)
        visible: list[ChartLayer] = []
        for layer in self._all_layers:
            group_values = layer.group_values or {}
            values = self._zero_totals()
            for group in selected:
                for category, amount in group_values.get(group, {}).items():
                    if category in values:
                        values[category] += float(amount or 0.0)
            if any(values.values()):
                visible.append(ChartLayer(layer.color, values, frozenset(selected), group_values))
        return visible

    def _visible_totals_from_layers(self) -> dict[str, float]:
        totals = self._zero_totals()
        for layer in self._visible_layers():
            for category in ALLOWED_CHART_PLAYS:
                totals[category] += float(layer.values.get(category, 0.0) or 0.0)
        return totals

    def _group_increments(self, group_totals: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        increments: dict[str, dict[str, float]] = {}
        for group, totals in group_totals.items():
            previous = self._last_group_totals.get(group, self._zero_totals())
            values = {
                category: max(0.0, totals[category] - previous[category])
                for category in ALLOWED_CHART_PLAYS
            }
            if any(values.values()):
                increments[group] = values
        return increments

    def _max_group_totals(
        self,
        previous: dict[str, dict[str, float]],
        current: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        merged = {group: dict(values) for group, values in previous.items()}
        for group, totals in current.items():
            existing = merged.setdefault(group, self._zero_totals())
            for category in ALLOWED_CHART_PLAYS:
                existing[category] = max(existing[category], totals[category])
        return merged

    def _zero_totals(self) -> dict[str, float]:
        return {category: 0.0 for category in ALLOWED_CHART_PLAYS}

    def _merge_period_rows(self, rows: list[dict[str, object]]) -> None:
        incoming_periods = {str(row.get("period", "")).strip() for row in rows if str(row.get("period", "")).strip()}
        existing_periods = {str(row.get("period", "")).strip() for row in self._period_rows if str(row.get("period", "")).strip()}
        if incoming_periods and existing_periods and incoming_periods != existing_periods:
            self._period_rows = []
            self._period_row_indexes = {}
            self._group_selection_initialized = False
            self._last_period_key = None
            self._reset_layers()
        for row in rows:
            key = self._row_identity(row)
            existing_index = self._period_row_indexes.get(key)
            if existing_index is not None:
                self._period_rows[existing_index] = dict(row)
                continue
            self._period_row_indexes[key] = len(self._period_rows)
            self._period_rows.append(dict(row))

    def _row_identity(self, row: dict[str, object]) -> tuple[object, ...]:
        row_id = str(row.get("row_id", "")).strip()
        if row_id:
            return ("row_id", row_id)
        ts = row.get("time")
        ts_key = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")
        bettor = str(row.get("bettor") or row.get("nickname") or row.get("username") or "").strip()
        if bettor:
            return (
                "bettor",
                str(row.get("group", "")).strip(),
                bettor,
                str(row.get("period", "")).strip(),
                str(row.get("play", "")).strip(),
            )
        return (
            "fallback",
            ts_key,
            str(row.get("group", "")).strip(),
            str(row.get("period", "")).strip(),
            str(row.get("play", "")).strip(),
        )

    def _select_all_groups(self) -> None:
        logger.debug("Chart group filter: select all")
        self._set_group_checks(Qt.Checked)

    def _invert_groups(self) -> None:
        logger.debug("Chart group filter: invert")
        self.group_list.blockSignals(True)
        for index in range(self.group_list.count()):
            item = self.group_list.item(index)
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self.group_list.blockSignals(False)
        self._handle_group_filter_changed()

    def _clear_groups(self) -> None:
        logger.debug("Chart group filter: clear")
        self._set_group_checks(Qt.Unchecked)

    def _set_group_checks(self, state: Qt.CheckState) -> None:
        self.group_list.blockSignals(True)
        for index in range(self.group_list.count()):
            self.group_list.item(index).setCheckState(state)
        self.group_list.blockSignals(False)
        self._handle_group_filter_changed()

    def _on_group_item_changed(self, _item: QListWidgetItem) -> None:
        self._handle_group_filter_changed()

    def _handle_group_filter_changed(self) -> None:
        self._group_selection_initialized = True
        self._refresh_activity()
        self.groups_changed.emit()
