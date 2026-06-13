from __future__ import annotations

import logging
from collections import defaultdict

from PySide6.QtCore import Qt, Signal
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


class BarChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.totals: dict[str, float] = {}
        self.setMinimumHeight(220)

    def set_totals(self, totals: dict[str, float]) -> None:
        self.totals = {str(key): float(value or 0) for key, value in totals.items() if float(value or 0) > 0}
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(16, 12, -16, -12)
        painter.fillRect(self.rect(), QColor("#fbfaf7"))
        painter.setPen(QPen(QColor("#2f2b25")))
        title_font = QFont("Microsoft YaHei UI", 10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(rect.left(), rect.top(), "玩法下注柱形图")

        if not self.totals:
            painter.setPen(QColor("#8f8578"))
            painter.drawText(rect, Qt.AlignCenter, "暂无可绘制的下注数据")
            return

        items = sorted(self.totals.items(), key=lambda item: item[1], reverse=True)[:12]
        max_value = max(value for _play, value in items) or 1.0
        chart_top = rect.top() + 30
        row_height = max(22, min(34, (rect.height() - 34) // max(1, len(items))))
        label_width = 76
        value_width = 88
        bar_left = rect.left() + label_width
        bar_max_width = max(40, rect.width() - label_width - value_width)
        colors = [QColor("#d97745"), QColor("#2f7f73"), QColor("#b13f3f"), QColor("#6b7f2f")]

        body_font = QFont("Microsoft YaHei UI", 9)
        painter.setFont(body_font)
        for index, (play, amount) in enumerate(items):
            y = chart_top + index * row_height
            painter.setPen(QColor("#3a332d"))
            painter.drawText(rect.left(), y + row_height - 7, play)
            width = int(bar_max_width * (amount / max_value))
            painter.fillRect(bar_left, y + 5, width, row_height - 10, colors[index % len(colors)])
            painter.setPen(QColor("#6c6257"))
            painter.drawText(bar_left + bar_max_width + 8, y + row_height - 7, f"{amount:,.0f}")


class ChartWindow(QWidget):
    groups_changed = Signal()

    def __init__(self, title: str = "投注图表", parent: QWidget | None = None, show_close: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._rows: list[dict[str, object]] = []
        self._status_mode = "empty"
        self._status_text = "暂无投注数据"

        root = QVBoxLayout(self)
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("可见群组"))
        self.group_all_btn = QPushButton("全选")
        self.group_invert_btn = QPushButton("反选")
        self.group_clear_btn = QPushButton("清空")
        self.group_all_btn.clicked.connect(self._select_all_groups)
        self.group_invert_btn.clicked.connect(self._invert_groups)
        self.group_clear_btn.clicked.connect(self._clear_groups)
        top_bar.addWidget(self.group_all_btn)
        top_bar.addWidget(self.group_invert_btn)
        top_bar.addWidget(self.group_clear_btn)
        top_bar.addStretch(1)
        root.addLayout(top_bar)

        self.group_list = QListWidget()
        self.group_list.itemChanged.connect(self._on_group_item_changed)
        self.group_list.setMaximumHeight(96)
        root.addWidget(self.group_list)

        self.status_label = QLabel(self._status_text)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("emphasisLabel")
        root.addWidget(self.status_label)

        self.bar_chart = BarChartWidget()
        root.addWidget(self.bar_chart, 2)

        self.activity_view = QTextEdit()
        self.activity_view.setReadOnly(True)
        root.addWidget(self.activity_view, 1)

        if show_close:
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.hide)
            root.addWidget(close_btn, alignment=Qt.AlignLeft)

    def set_rows(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)
        self._sync_group_list(rows)
        self._refresh_activity()
        logger.debug("Chart rows updated: %d rows", len(rows))

    def update_activity(self, rows: list[dict[str, object]]) -> None:
        self.set_rows(rows)

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
            item.setCheckState(Qt.Checked if not selected or group in selected else Qt.Unchecked)
            self.group_list.addItem(item)
        self.group_list.blockSignals(False)

    def _refresh_activity(self) -> None:
        selected = self.selected_groups()
        rows = [row for row in self._rows if not selected or str(row.get("group", "")) in selected]
        self.bar_chart.set_totals(self._totals_by_play(rows))
        lines = []
        for row in rows[-120:]:
            ts = row.get("time")
            ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else "-"
            display_name = str(row.get("bettor") or row.get("username") or "")
            lines.append(
                " | ".join(
                    [
                        ts_text,
                        str(row.get("group", "")),
                        display_name,
                        str(row.get("period", "")),
                        str(row.get("play", "")),
                        f"{float(row.get('amount', 0) or 0):,.0f}",
                    ]
                )
            )
        self.activity_view.setPlainText("\n".join(lines))

    def _totals_by_play(self, rows: list[dict[str, object]]) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for row in rows:
            play = str(row.get("play", "")).strip()
            if not play:
                continue
            totals[play] += float(row.get("amount", 0) or 0)
        return dict(totals)

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
        self._refresh_activity()
        self.groups_changed.emit()

    def _clear_groups(self) -> None:
        logger.debug("Chart group filter: clear")
        self._set_group_checks(Qt.Unchecked)

    def _set_group_checks(self, state: Qt.CheckState) -> None:
        self.group_list.blockSignals(True)
        for index in range(self.group_list.count()):
            self.group_list.item(index).setCheckState(state)
        self.group_list.blockSignals(False)
        self._refresh_activity()
        self.groups_changed.emit()

    def _on_group_item_changed(self, _item: QListWidgetItem) -> None:
        self._refresh_activity()
        self.groups_changed.emit()
