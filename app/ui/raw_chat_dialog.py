from __future__ import annotations

from html import escape
from math import ceil
import re

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout


ALL_GROUPS_LABEL = "全部群组"
ALL_SEMANTICS_LABEL = "全部类型"
SEMANTIC_LABELS = [
    "下注归期边界",
    "推断期号边界",
    "机器人回执/汇总",
    "开奖结果播报",
    "机器人状态快照",
    "用户下注",
    "撤单/改注",
    "普通聊天",
]
SEMANTIC_COLORS = {
    "下注归期边界": ("#fff3cd", "#7a5200"),
    "推断期号边界": ("#fde2e1", "#8a1f17"),
    "机器人回执/汇总": ("#e3f2fd", "#0b4f7a"),
    "开奖结果播报": ("#e8f5e9", "#1b5e20"),
    "机器人状态快照": ("#f3e5f5", "#5e2472"),
    "用户下注": ("#eef7ff", "#1f4e79"),
    "撤单/改注": ("#ffebee", "#8a1c1c"),
    "普通聊天": ("#f5f5f5", "#444444"),
}
PLAY_TOKENS = ("大单", "小单", "大双", "小双", "大", "小", "单", "双")


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
        filter_row.addWidget(QLabel("类型"))
        self.semantic_filter = QComboBox()
        self.semantic_filter.currentTextChanged.connect(self._on_semantic_changed)
        filter_row.addWidget(self.semantic_filter, 1)
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
        current_semantic = self.semantic_filter.currentText() if self.semantic_filter.count() else ALL_SEMANTICS_LABEL
        self.semantic_filter.blockSignals(True)
        self.semantic_filter.clear()
        self.semantic_filter.addItem(ALL_SEMANTICS_LABEL)
        self.semantic_filter.addItems(SEMANTIC_LABELS)
        if current_semantic in [ALL_SEMANTICS_LABEL, *SEMANTIC_LABELS]:
            self.semantic_filter.setCurrentText(current_semantic)
        self.semantic_filter.blockSignals(False)
        total_pages = max(1, ceil(len(self._filtered_messages()) / self.page_size))
        self.message_page = min(current_page, total_pages - 1)
        self._refresh_message_view(preserve_scroll_value=current_scroll)

    def _filtered_messages(self) -> list[object]:
        selected_group = self.group_filter.currentText()
        selected_semantic = self.semantic_filter.currentText()
        filtered = self.messages
        if selected_group and selected_group != ALL_GROUPS_LABEL:
            filtered = [message for message in filtered if str(getattr(message, "group", "")).strip() == selected_group]
        if selected_semantic and selected_semantic != ALL_SEMANTICS_LABEL:
            filtered = [message for message in filtered if self._semantic_label(message) == selected_semantic]
        return filtered

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
        semantic = self._semantic_label(message)
        bg_color, fg_color = SEMANTIC_COLORS.get(semantic, SEMANTIC_COLORS["普通聊天"])
        return (
            f"<div style='background:{bg_color}; color:{fg_color}; padding:6px; border-radius:4px;'>"
            f"<b>[{escape(semantic)}] {escape(header)}</b><br/>"
            f"{escape(content).replace(chr(10), '<br/>')}"
            "</div>"
        )

    def _semantic_label(self, message: object) -> str:
        content = str(getattr(message, "content", "") or "").strip()
        username = str(getattr(message, "username", "") or "").strip()
        is_robot = "机器" in username
        if self._looks_like_receipt(content):
            return "机器人回执/汇总"
        if self._looks_like_result_broadcast(content):
            return "开奖结果播报"
        if self._looks_like_state_snapshot(content):
            return "机器人状态快照"
        if is_robot and self._looks_like_boundary(content):
            return "下注归期边界"
        if self._looks_like_cancel(content):
            return "撤单/改注"
        if self._looks_like_user_bet(content):
            return "用户下注"
        return "普通聊天"

    def _looks_like_receipt(self, content: str) -> bool:
        return "下注期数" in content and "下注内容" in content

    def _looks_like_result_broadcast(self, content: str) -> bool:
        return "彩种" in content and "期号" in content and ("结果" in content or "历史开奖" in content)

    def _looks_like_state_snapshot(self, content: str) -> bool:
        return "当前积分" in content and ("本期下注" in content or "本期未下注" in content)

    def _looks_like_boundary(self, content: str) -> bool:
        return any(token in content for token in ("开始下注", "下注开始", "截止线", "封盘线", "已截止"))

    def _looks_like_cancel(self, content: str) -> bool:
        return content.strip() == "取消" or "已取消" in content or "撤单" in content

    def _looks_like_user_bet(self, content: str) -> bool:
        return any(re.search(rf"{re.escape(play)}\s*\d", content) or re.search(rf"\d+\s*{re.escape(play)}", content) for play in PLAY_TOKENS)

    def _on_group_changed(self) -> None:
        self.message_page = 0
        self._refresh_message_view()

    def _on_semantic_changed(self) -> None:
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
