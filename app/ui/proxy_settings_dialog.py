from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class ProxySettingsDialog(QDialog):
    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("代理设置")
        self.setModal(True)
        self.resize(480, 210)

        layout = QVBoxLayout(self)
        hint = QLabel("默认使用直连。只有需要时才启用并填写代理地址。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._enabled_check = QCheckBox("启用代理")
        self._enabled_check.setChecked(bool(settings.get("proxy_enabled", False)))
        self._enabled_check.toggled.connect(self._sync_enabled)
        layout.addWidget(self._enabled_check)

        form = QFormLayout()
        self._http_edit = QLineEdit(str(settings.get("proxy_http", "") or ""))
        self._http_edit.setPlaceholderText("http://127.0.0.1:7890")
        self._https_edit = QLineEdit(str(settings.get("proxy_https", "") or ""))
        self._https_edit.setPlaceholderText("留空时复用 HTTP 代理")
        form.addRow("HTTP:", self._http_edit)
        form.addRow("HTTPS:", self._https_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_enabled(self._enabled_check.isChecked())

    def values(self) -> tuple[bool, str, str]:
        return (
            self._enabled_check.isChecked(),
            self._http_edit.text().strip(),
            self._https_edit.text().strip(),
        )

    def _sync_enabled(self, enabled: bool) -> None:
        self._http_edit.setEnabled(enabled)
        self._https_edit.setEnabled(enabled)
