from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout


ALL_GROUPS_LABEL = "全部群组"


class UnresolvedReceiptDialog(QDialog):
    def __init__(self, rows: list[dict[str, object]] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("未归属回执诊断")
        self.resize(760, 520)
        self.rows: list[dict[str, object]] = []

        layout = QVBoxLayout(self)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("群组"))
        self.group_filter = QComboBox()
        self.group_filter.currentTextChanged.connect(self._refresh_result_view)
        filter_row.addWidget(self.group_filter, 1)
        layout.addLayout(filter_row)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        layout.addWidget(self.result_view, 1)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.set_rows(rows or [])

    def set_rows(self, rows: list[dict[str, object]]) -> None:
        self.rows = [dict(row) for row in rows]
        current_group = self.group_filter.currentText() if self.group_filter.count() else ALL_GROUPS_LABEL
        groups = sorted({str(row.get("group", "")).strip() for row in self.rows if str(row.get("group", "")).strip()})
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem(ALL_GROUPS_LABEL)
        self.group_filter.addItems(groups)
        if current_group in [ALL_GROUPS_LABEL, *groups]:
            self.group_filter.setCurrentText(current_group)
        self.group_filter.blockSignals(False)
        self._refresh_result_view()

    def _filtered_rows(self) -> list[dict[str, object]]:
        selected_group = self.group_filter.currentText()
        if not selected_group or selected_group == ALL_GROUPS_LABEL:
            return list(self.rows)
        return [row for row in self.rows if str(row.get("group", "")).strip() == selected_group]

    def _refresh_result_view(self) -> None:
        rows = self._filtered_rows()
        if not rows:
            self.result_view.setPlainText("当前没有未归属回执。")
            return
        lines: list[str] = []
        for row in rows:
            lines.append(
                " | ".join(
                    [
                        str(row.get("group", "") or ""),
                        str(row.get("username", "") or ""),
                        str(row.get("bettor", "") or ""),
                        str(row.get("period", "") or ""),
                        str(row.get("play", "") or ""),
                        f"{float(row.get('amount', 0.0) or 0.0):,.0f}",
                        str(row.get("sender_id", "") or ""),
                        str(row.get("source_kind", "") or ""),
                    ]
                )
            )
        self.result_view.setPlainText("\n".join(lines))
