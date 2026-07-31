"""Establish the mandatory server session from local signed authorization."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.server_api_client import ServerApiError


@dataclass(frozen=True)
class ServerModeStatus:
    connected: bool
    wss_synced: bool
    message: str


def bootstrap_server_mode(client, license_service, *, account_identifier: str = "", credential_provider=None) -> ServerModeStatus:
    license_token = license_service.local_license_token()
    if not license_token:
        return ServerModeStatus(False, False, "本机授权无效，无法连接服务器")
    try:
        if not getattr(client, "is_authenticated", False):
            client.login_with_local_license(license_service.get_machine_code(), license_token)
        if not account_identifier or credential_provider is None:
            return ServerModeStatus(True, False, "服务器已连接，等待检测本机 WSS 凭据")
        credentials = credential_provider.read(account_identifier)
        if credentials is None:
            return ServerModeStatus(True, False, "服务器已连接，未检测到本机 WSS 凭据")
        client.save_wss_credentials(credentials.appid, credentials.accid, credentials.user_sig)
        return ServerModeStatus(True, True, "服务器已连接，本机 WSS 凭据已同步")
    except ServerApiError as exc:
        return ServerModeStatus(False, False, f"服务器连接失败：{exc}")
