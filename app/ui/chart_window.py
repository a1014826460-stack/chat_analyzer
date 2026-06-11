from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
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
        root.addWidget(self.group_list)

        self.status_label = QLabel(self._status_text)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("emphasisLabel")
        root.addWidget(self.status_label)

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
        lines = []
        for row in rows[-120:]:
            ts = row.get("time")
            ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else "-"
            lines.append(
                " | ".join(
                    [
                        ts_text,
                        str(row.get("group", "")),
                        str(row.get("username", "")),
                        str(row.get("period", "")),
                        str(row.get("play", "")),
                        f"{float(row.get('amount', 0) or 0):,.0f}",
                    ]
                )
            )
        self.activity_view.setPlainText("\n".join(lines))

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
