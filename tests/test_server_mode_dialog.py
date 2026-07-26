from __future__ import annotations


def test_server_mode_dialog_uses_local_license_and_auto_detected_wss_credentials_only():
    from PySide6.QtWidgets import QApplication

    from app.services.server_mode_settings import ServerModeSettings
    from app.ui.server_mode_dialog import ServerModeDialog

    class Client:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url
            self.logged_in: tuple[str, str] | None = None
            self.credentials: tuple[str, str, str] | None = None

        def login_with_local_license(self, machine_code: str, license_token: str) -> None:
            self.logged_in = (machine_code, license_token)

        def save_wss_credentials(self, appid: str, accid: str, user_sig: str) -> dict:
            self.credentials = (appid, accid, user_sig)
            return {}

    app = QApplication.instance() or QApplication([])
    dialog = ServerModeDialog(
        settings=ServerModeSettings(), machine_code="machine-001", license_token="signed-license",
        wss_credentials=("10001", "accid", "secret"), client_factory=Client,
    )
    dialog.enabled_check.setChecked(True)
    dialog._login_and_accept()

    assert dialog.client.logged_in == ("machine-001", "signed-license")
    assert dialog.client.credentials == ("10001", "accid", "secret")
    assert dialog.settings.to_dict() == {"enabled": True, "base_url": "http://127.0.0.1:8080"}
    assert not hasattr(dialog, "activation_code_edit")
    assert not hasattr(dialog, "wss_user_sig_edit")
