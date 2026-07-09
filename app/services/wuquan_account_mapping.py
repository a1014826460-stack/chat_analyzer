from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class WuQuanLoginAccount:
    accid: str
    appid: str
    user_sig: str
    im_appid: str
    access_token: str = ""
    nick_name: str = ""
    avatar: str = ""
    phone: str = ""


def load_shared_preferences(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))


def _loads_record(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, dict) else None


def iter_login_accounts(payload: dict[str, Any]) -> Iterable[WuQuanLoginAccount]:
    seen: set[tuple[str, str]] = set()

    def emit_from_record(record: dict[str, Any]) -> WuQuanLoginAccount | None:
        login = record.get("loginResultEntity") if isinstance(record.get("loginResultEntity"), dict) else record
        if not isinstance(login, dict):
            return None
        accid = str(record.get("accid") or login.get("accid") or "").strip()
        appid = str(login.get("appid") or record.get("appid") or "").strip()
        user_sig = str(login.get("token") or login.get("userSig") or record.get("token") or "").strip()
        im_appid = str(login.get("imAppid") or record.get("imAppid") or "").strip()
        if not accid:
            return None
        return WuQuanLoginAccount(
            accid=accid,
            appid=appid,
            user_sig=user_sig,
            im_appid=im_appid,
            access_token=str(login.get("access_token") or "").strip(),
            nick_name=str(login.get("nickName") or "").strip(),
            avatar=str(login.get("avatar") or "").strip(),
            phone=str(login.get("phonenumber") or login.get("userName") or "").strip(),
        )

    account_list = payload.get("flutter.AccountManager_AccountList", [])
    if isinstance(account_list, list):
        for raw in account_list:
            record = _loads_record(raw)
            if record is None:
                continue
            account = emit_from_record(record)
            if account is None:
                continue
            key = (account.accid, account.appid)
            if key not in seen:
                seen.add(key)
                yield account

    for key, raw in payload.items():
        if not str(key).startswith("flutter.SpKeyLoginResult-"):
            continue
        record = _loads_record(raw)
        if record is None:
            continue
        account = emit_from_record(record)
        if account is None:
            continue
        dedupe_key = (account.accid, account.appid)
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            yield account


def resolve_login_account(identifier: str, payload: dict[str, Any]) -> WuQuanLoginAccount | None:
    needle = str(identifier).strip()
    if not needle:
        return None
    for account in iter_login_accounts(payload):
        if needle in {account.accid, account.appid, account.phone}:
            return account
    return None


def resolve_im_accid(identifier: str, payload: dict[str, Any]) -> str:
    account = resolve_login_account(identifier, payload)
    return account.accid if account is not None else str(identifier).strip()
