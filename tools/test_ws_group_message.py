"""Manual WebSocket group-message test.

Opens an independent WebSocket connection to Tencent IM — does NOT
create an SDK login session, so WuQuan stays online.

Usage:
    python tools/test_ws_group_message.py <account_name_or_accid> [group_id] [text]

Example:
    .\.venv\Scripts\python.exe tools\test_ws_group_message.py x1DuArYgV 207191791 "小单 1"
    .\.venv\Scripts\python.exe tools\test_ws_group_message.py 齐天大圣 207191791 "大 100"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import AccountResolver, DEFAULT_SHARED_PREFS
from app.services.ws_message_sender import WsMessageSender


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
            acct_accid = account.get("accid") or login.get("accid")
            if acct_accid == accid:
                return str(login.get("token", "") or "").strip()
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/test_ws_group_message.py <account_name_or_accid> [group_id] [text]")
        print()
        print("Examples:")
        print("  .\\.venv\\Scripts\\python.exe tools\\test_ws_group_message.py 齐天大圣 207191791 \"小单 1\"")
        print("  .\\.venv\\Scripts\\python.exe tools\\test_ws_group_message.py x1DuArYgV 207191791 \"大 100\"")
        return 2

    username = sys.argv[1]
    group_id = sys.argv[2] if len(sys.argv) >= 3 else "207191791"
    text = sys.argv[3] if len(sys.argv) >= 4 else "小单 1"

    # Step 1 — Resolve account
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

    # Step 2 — Load UserSig
    print("\n[2/4] Loading UserSig from shared_preferences.json")
    user_sig = _load_user_sig(resolved.accid)
    if not user_sig:
        print(f"ERROR: UserSig not found for accid={resolved.accid}")
        return 1
    print(f"      token:        loaded ({len(user_sig)} chars)")

    # Step 3 — WebSocket connect + login
    print(f"\n[3/4] Opening WebSocket to wsssgp.im.qcloud.com ...")
    print(f"      (independent connection — WuQuan stays online)")
    sender = WsMessageSender(
        sdk_app_id=int(resolved.im_appid),
        identifier=resolved.accid,
        user_sig=user_sig,
    )

    if not sender.startup():
        print("ERROR: WebSocket connect or login failed.")
        return 1
    print("      WebSocket connected + logged in: OK")

    # Step 4 — Send message
    print(f"\n[4/4] Sending group message to {group_id}: {text!r}")
    ok = sender.inject_text(group_id, text, is_group=True)

    sender.shutdown()

    if ok:
        print("SUCCESS: WebSocket message sent.")
        print("WuQuan should still be online — independent connection.")
        return 0

    print("FAILED: WebSocket send returned error.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
