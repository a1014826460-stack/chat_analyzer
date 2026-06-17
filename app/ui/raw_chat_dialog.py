from __future__ import annotations

from html import escape
from math import ceil

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout


ALL_GROUPS_LABEL = "全部群组"


class RawChatDialog(QDialog):
    def __init__(self, messages: list[object] | None = None, parent=None, *, page_size: int = 50) -> None:
        super().__init__(parent)
        self.setWindowTitle("原始聊天记录")
        self.resize(900, 620)
        self.messages: list[object] = []
        self.page_size = page_size
        self.message_page = 0

        layout = QVBoxLayout(self)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("群组"))
        self.group_filter = QComboBox()
        self.group_filter.currentTextChanged.connect(self._on_group_changed)
        filter_row.addWidget(self.group_filter, 1)
        layout.addLayout(filter_row)

        self.message_view = QTextEdit()
        self.message_view.setReadOnly(True)
        layout.addWidget(self.message_view, 1)

        pager = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self._next_page)
        self.page_label = QLabel("第 1 / 1 页")
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.next_btn)
        pager.addWidget(self.page_label)
        pager.addStretch(1)
        layout.addLayout(pager)

        self.set_messages(messages or [])

    def set_messages(self, messages: list[object]) -> None:
        current_group = self.group_filter.currentText() if self.group_filter.count() else ALL_GROUPS_LABEL
        current_page = self.message_page
        current_scroll = self._current_scroll_value()
        self.messages = list(messages)
        groups = sorted({str(getattr(message, "group", "")).strip() for message in self.messages if str(getattr(message, "group", "")).strip()})
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem(ALL_GROUPS_LABEL)
        self.group_filter.addItems(groups)
        if current_group in [ALL_GROUPS_LABEL, *groups]:
            self.group_filter.setCurrentText(current_group)
        self.group_filter.blockSignals(False)
        total_pages = max(1, ceil(len(self._filtered_messages()) / self.page_size))
        self.message_page = min(current_page, total_pages - 1)
        self._refresh_message_view(preserve_scroll_value=current_scroll)

    def _filtered_messages(self) -> list[object]:
        selected_group = self.group_filter.currentText()
        if not selected_group or selected_group == ALL_GROUPS_LABEL:
            return self.messages
        return [message for message in self.messages if str(getattr(message, "group", "")).strip() == selected_group]

    def _current_scroll_value(self) -> int:
        scrollbar = self.message_view.verticalScrollBar()
        return int(scrollbar.value()) if scrollbar is not None else 0

    def _refresh_message_view(self, preserve_scroll_value: int | None = None) -> None:
        filtered = self._filtered_messages()
        total_pages = max(1, ceil(len(filtered) / self.page_size))
        self.message_page = min(self.message_page, total_pages - 1)
        start = self.message_page * self.page_size
        page_rows = filtered[start : start + self.page_size]

        self.message_view.clear()
        cursor = self.message_view.textCursor()
        for message in page_rows:
            cursor.insertHtml(self._message_html(message))
            cursor.insertHtml("<br/><br/>")
        self.page_label.setText(f"第 {self.message_page + 1} / {total_pages} 页")
        self.prev_btn.setEnabled(self.message_page > 0)
        self.next_btn.setEnabled(self.message_page + 1 < total_pages)
        if preserve_scroll_value is None:
            self.message_view.moveCursor(QTextCursor.Start)
        else:
            scrollbar = self.message_view.verticalScrollBar()
            if scrollbar is not None:
                scrollbar.setValue(min(int(preserve_scroll_value), scrollbar.maximum()))

    def _message_html(self, message: object) -> str:
        ts = getattr(message, "ts", None)
        ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else "-"
        header = " | ".join(
            [
                ts_text,
                str(getattr(message, "group", "")).strip(),
                str(getattr(message, "username", "")).strip(),
                str(getattr(message, "sender_id", "")).strip(),
            ]
        )
        content = str(getattr(message, "content", "")).strip()
        return f"<b>{escape(header)}</b><br/>{escape(content).replace(chr(10), '<br/>')}"

    def _on_group_changed(self) -> None:
        self.message_page = 0
        self._refresh_message_view()

    def _prev_page(self) -> None:
        if self.message_page > 0:
            self.message_page -= 1
            self._refresh_message_view()

    def _next_page(self) -> None:
        total_pages = max(1, ceil(len(self._filtered_messages()) / self.page_size))
        if self.message_page + 1 < total_pages:
            self.message_page += 1
            self._refresh_message_view()
