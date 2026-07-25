"""Manual ImSDK group-message test (direct ctypes approach).

Loads ImSDK.dll, calls TIMLogin + TIMMsgSendMessage.  Will kick the
running WuQuan client offline if the same account is logged in.

Usage:
    python tools/test_imsdk_group_message.py <account_name> [group_id] [text]

Example:
    .\.venv\Scripts\python.exe tools\test_imsdk_group_message.py 齐天大圣 207191791 "小单 1"
    .\.venv\Scripts\python.exe tools\test_imsdk_group_message.py x1DuArYgV 207191791 "大 100"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import AccountResolver, DEFAULT_SHARED_PREFS
from app.services.message_injector import MessageInjector

IMSDK_DLL = ROOT / "WuQuan" / "ImSDK.dll"
IMSDK_DATA = ROOT / "WuQuan" / "data"


def _load_user_sig(accid: str) -> str:
    """Extract the compressed UserSig (token) for the given accid."""
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
        print("Usage: python tools/test_imsdk_group_message.py <account_name> [group_id] [text]")
        print()
        print("Examples:")
        print("  .\\.venv\\Scripts\\python.exe tools\\test_imsdk_group_message.py 齐天大圣 207191791 \"小单 1\"")
        print("  .\\.venv\\Scripts\\python.exe tools\\test_imsdk_group_message.py x1DuArYgV 207191791 \"大 100\"")
        return 2

    username = sys.argv[1]
    group_id = sys.argv[2] if len(sys.argv) >= 3 else "207191791"
    text = sys.argv[3] if len(sys.argv) >= 4 else "小单 1"

    # ------------------------------------------------------------------
    # Step 1 — Resolve account
    # ------------------------------------------------------------------
    print(f"[1/5] Resolving account: {username}")
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

    # ------------------------------------------------------------------
    # Step 2 — Load UserSig
    # ------------------------------------------------------------------
    print("\n[2/5] Loading UserSig from shared_preferences.json")
    user_sig = _load_user_sig(resolved.accid)
    if not user_sig:
        print(f"ERROR: UserSig/token not found for accid={resolved.accid}")
        return 1
    print(f"      token:        loaded ({len(user_sig)} chars)")

    # ------------------------------------------------------------------
    # Step 3 — TIMInit + TIMLogin
    # ------------------------------------------------------------------
    print(f"\n[3/5] Initializing ImSDK and logging in as {resolved.accid} ...")
    print("      WARNING: this may kick WuQuan offline if using the same account.")
    injector = MessageInjector(
        dll_path=str(IMSDK_DLL),
        sdk_app_id=int(resolved.im_appid),
        accid=resolved.accid,
        user_sig=user_sig,
        data_dir=str(IMSDK_DATA),
    )

    if not injector.startup():
        print("ERROR: ImSDK startup or login failed (check logs above).")
        return 1
    print("      TIMInit + TIMLogin: OK")

    # ------------------------------------------------------------------
    # Step 4 — Send group message
    # ------------------------------------------------------------------
    print(f"\n[4/5] Sending group message to {group_id}: {text!r}")
    ok = injector.inject_text(group_id, text, is_group=True)

    # ------------------------------------------------------------------
    # Step 5 — Cleanup & result
    # ------------------------------------------------------------------
    print("\n[5/5] Shutting down ImSDK")
    injector.shutdown()

    if ok:
        print("SUCCESS: TIMMsgSendMessage callback returned code=0.")
        print("Tip: if WuQuan was kicked, it should auto-reconnect within seconds.")
        return 0

    print("FAILED: TIMMsgSendMessage callback returned non-zero or timed out.")
    print("Tip: make sure the account is a member of the target group.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
