from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.server_api_client import ServerApiClient, ServerApiError
from app.services.server_mode_settings import ServerModeSettings


class ServerModeDialog(QDialog):
    """Configure the central API and keep its JWT only in the supplied client."""

    def __init__(
        self,
        *,
        settings: ServerModeSettings,
        machine_code: str,
        license_token: str,
        wss_credentials: tuple[str, str, str] | None,
        client_factory=ServerApiClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("服务器模式")
        self.setModal(True)
        self.resize(460, 300)
        self._machine_code = machine_code
        self._license_token = license_token
        self._wss_credentials = wss_credentials
        self._client_factory = client_factory
        self.client: ServerApiClient | None = None
        self.settings: ServerModeSettings = settings

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled_check = QCheckBox("启用服务器集中调度")
        self.enabled_check.setChecked(settings.enabled)
        self._base_url = settings.base_url
        self.wss_status = QLineEdit("已检测到本机登录凭据" if wss_credentials else "未检测到本机登录凭据")
        self.wss_status.setReadOnly(True)
        form.addRow("WSS 同步", self.wss_status)
        layout.addWidget(self.enabled_check)
        layout.addLayout(form)

        self.login_button = QPushButton("登录并保存")
        self.login_button.clicked.connect(self._login_and_accept)
        layout.addWidget(self.login_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _login_and_accept(self) -> None:
        base_url = self._base_url
        if self.enabled_check.isChecked() and not self._license_token:
            QMessageBox.warning(self, "服务器模式", "本机授权无效，无法连接服务器")
            return
        client = self._client_factory(base_url)
        try:
            if self.enabled_check.isChecked():
                client.login_with_local_license(self._machine_code, self._license_token)
                self._save_wss_credentials(client)
        except ServerApiError as exc:
            QMessageBox.warning(self, "服务器登录失败", str(exc))
            return
        self.client = client
        self.settings = ServerModeSettings(enabled=self.enabled_check.isChecked(), base_url=base_url)
        self.accept()

    def _save_wss_credentials(self, client: ServerApiClient) -> None:
        if self._wss_credentials is None:
            return
        client.save_wss_credentials(*self._wss_credentials)
