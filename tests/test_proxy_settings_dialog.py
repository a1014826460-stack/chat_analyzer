from __future__ import annotations


def test_proxy_dialog_defaults_to_direct_connection():
    from PySide6.QtWidgets import QApplication
    from app.ui.proxy_settings_dialog import ProxySettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = ProxySettingsDialog({})

    assert dialog.values() == (False, "", "")
    assert not dialog._http_edit.isEnabled()
    assert not dialog._https_edit.isEnabled()


def test_proxy_dialog_loads_saved_values_and_enables_address_fields():
    from PySide6.QtWidgets import QApplication
    from app.ui.proxy_settings_dialog import ProxySettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = ProxySettingsDialog({
        "proxy_enabled": True,
        "proxy_http": "http://127.0.0.1:7890",
        "proxy_https": "http://127.0.0.1:7890",
    })

    assert dialog.values() == (
        True,
        "http://127.0.0.1:7890",
        "http://127.0.0.1:7890",
    )
    assert dialog._http_edit.isEnabled()
    assert dialog._https_edit.isEnabled()
