"""Manual REST group-message test.

Usage:
    python tools/test_rest_group_message.py <account_name_or_accid> [group_id] [text]

Example:
    .\.venv\Scripts\python.exe tools\test_rest_group_message.py lin2225427 207191791 "小单 1"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import AccountResolver, DEFAULT_SHARED_PREFS
from app.services.rest_message_sender import RestGroupMessageSender


def _load_user_sig(accid: str) -> str:
    payload = json.loads(Path(DEFAULT_SHARED_PREFS).read_text(encoding="utf-8"))
    account_list = payload.get("flutter.AccountManager_AccountList", [])
    if not isinstance(account_list, list):
        return ""

    for raw_account in account_list:
        try:
            account = json.loads(raw_account) if isinstance(raw_account, str) else raw_account
        except json.JSONDecodeError:
            continue
        if not isinstance(account, dict):
            continue
        login = account.get("loginResultEntity", {})
        if isinstance(login, dict):
            account_accid = account.get("accid") or login.get("accid")
            if account_accid == accid:
                return str(login.get("token", "") or "").strip()
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/test_rest_group_message.py <account_name_or_accid> [group_id] [text]")
        return 2

    username = sys.argv[1]
    group_id = sys.argv[2] if len(sys.argv) >= 3 else "207191791"
    text = sys.argv[3] if len(sys.argv) >= 4 else "小单 1"

    print(f"[1/4] Resolving account: {username}")
    resolver = AccountResolver()
    resolved = resolver.resolve(username)
    if resolved is None:
        diag = resolver.get_diagnostic()
        if diag is not None:
            print(diag.format_message())
        print("ERROR: Could not resolve account database.")
        return 1

    print(f"      account_name: {resolved.account_name}")
    print(f"      accid:        {resolved.accid}")
    print(f"      im_appid:     {resolved.im_appid}")
    print(f"      msg_db:       {resolved.msg_db}")

    print("\n[2/4] Loading token from shared_preferences.json")
    user_sig = _load_user_sig(resolved.accid)
    if not user_sig:
        print(f"ERROR: UserSig/token not found for accid={resolved.accid}")
        return 1
    print("      token:        loaded")

    print(f"\n[3/4] Sending REST group message to {group_id}: {text!r}")
    sender = RestGroupMessageSender(
        sdk_app_id=resolved.im_appid,
        identifier=resolved.accid,
        user_sig=user_sig,
        from_account=resolved.accid,
        msg_db_path=resolved.msg_db,
        verify_timeout_sec=5.0,
        verify_poll_interval_sec=0.5,
    )
    print(f"      REST endpoint: {sender.endpoint}")
    ok = sender.inject_text(group_id, text)

    print("\n[4/4] Result")
    if ok:
        print("SUCCESS: REST returned OK and msg_0.db contains the target group/content row.")
        return 0

    print("FAILED: REST failed or msg_0.db did not contain the target group/content row within timeout.")
    print("Tip: if the group receives the message but verification fails, wait a few seconds and check whether msg_0.db sync is delayed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
