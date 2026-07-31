"""Read the already logged-in Tencent Cloud Chat identity from local preferences."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.account_resolver import DEFAULT_SHARED_PREFS
from app.services.wuquan_account_mapping import load_shared_preferences, resolve_login_account


@dataclass(frozen=True)
class LocalWssCredentials:
    appid: str
    accid: str
    user_sig: str


class LocalWssCredentialProvider:
    def __init__(self, preferences_path: Path = DEFAULT_SHARED_PREFS) -> None:
        self._preferences_path = preferences_path

    def read(self, account_identifier: str) -> LocalWssCredentials | None:
        try:
            account = resolve_login_account(account_identifier, load_shared_preferences(self._preferences_path))
        except (OSError, ValueError):
            return None
        if account is None or not account.appid or not account.accid or not account.user_sig:
            return None
        sdk_appid = account.im_appid or account.appid
        return LocalWssCredentials(sdk_appid, account.accid, account.user_sig)
