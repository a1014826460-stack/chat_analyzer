from __future__ import annotations


def test_server_mode_bootstrap_uses_local_license_and_automatically_syncs_detected_wss_credentials():
    from app.services.server_mode_bootstrap import bootstrap_server_mode

    class License:
        def get_machine_code(self) -> str:
            return "machine-001"

        def local_license_token(self) -> str:
            return "signed-license"

    class Client:
        is_authenticated = False

        def __init__(self) -> None:
            self.login_args: tuple[str, str] | None = None
            self.credentials: tuple[str, str, str] | None = None

        def login_with_local_license(self, machine_code: str, license_token: str) -> None:
            self.login_args = (machine_code, license_token)
            self.is_authenticated = True

        def save_wss_credentials(self, appid: str, accid: str, user_sig: str) -> None:
            self.credentials = (appid, accid, user_sig)

    class Provider:
        def read(self, account_identifier: str):
            assert account_identifier == "accid-1"
            return type("Credentials", (), {"appid": "app", "accid": "accid-1", "user_sig": "sig"})()

    client = Client()
    status = bootstrap_server_mode(client, License(), account_identifier="accid-1", credential_provider=Provider())

    assert status.connected is True
    assert status.wss_synced is True
    assert client.login_args == ("machine-001", "signed-license")
    assert client.credentials == ("app", "accid-1", "sig")


def test_server_mode_bootstrap_refuses_to_connect_without_valid_local_license():
    from app.services.server_mode_bootstrap import bootstrap_server_mode

    class License:
        def get_machine_code(self) -> str:
            return "machine-001"

        def local_license_token(self) -> str:
            return ""

    status = bootstrap_server_mode(object(), License())

    assert status.connected is False
    assert "本机授权" in status.message
