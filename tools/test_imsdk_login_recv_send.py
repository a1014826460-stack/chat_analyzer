"""Login with ImSDK, listen for new messages, optionally send one."""
from __future__ import annotations

import json
import sys
import time
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import AccountResolver, DEFAULT_SHARED_PREFS
from app.services.message_injector import MessageInjector

IMSDK_DLL = ROOT / "WuQuan" / "ImSDK.dll"
IMSDK_DATA = ROOT / "WuQuan" / "data"


def load_user_sig(accid: str) -> str:
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


def text_of(message: dict) -> str:
    parts: list[str] = []
    for elem in message.get("message_elem_array", []) or []:
        if isinstance(elem, dict):
            text = elem.get("text_elem_content")
            if text:
                parts.append(str(text))
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Login with Tencent ImSDK, receive messages, optionally send one.",
    )
    parser.add_argument("account", nargs="?", help="account name or accid in local shared_preferences.json")
    parser.add_argument("group_id", nargs="?", default="", help="group id to send to")
    parser.add_argument("text", nargs="?", default="", help="text to send")
    parser.add_argument("listen_seconds", nargs="?", type=float, default=15.0)
    parser.add_argument("--target", "--group-id", dest="target", help="target group id or C2C user id")
    parser.add_argument("--message", "--text", dest="message", help="message text to send")
    parser.add_argument("--listen", dest="listen", type=float, help="listen duration in seconds")
    parser.add_argument("--accid", help="use explicit accid from login API response")
    parser.add_argument("--user-sig", "--token", dest="user_sig", help="use explicit token/UserSig from login API response")
    parser.add_argument("--sdk-app-id", "--im-appid", dest="sdk_app_id", default="20011216")
    parser.add_argument("--c2c", action="store_true", help="send as C2C instead of group message")
    args = parser.parse_args()
    target_id = args.target or args.group_id
    send_text = args.message or args.text
    listen_seconds = args.listen if args.listen is not None else args.listen_seconds

    if args.accid and args.user_sig:
        account_name = args.accid
        accid = args.accid
        im_appid = str(args.sdk_app_id)
        user_sig = args.user_sig
        print("[1/5] Using explicit login API parameters")
        print(f"      accid:        {accid}")
        print(f"      im_appid:     {im_appid}")
        print("\n[2/5] Loading UserSig")
        print(f"      token:        explicit ({len(user_sig)} chars)")
    else:
        if not args.account:
            parser.print_help()
            return 2
        print(f"[1/5] Resolving account: {args.account}")
        resolver = AccountResolver()
        resolved = resolver.resolve(args.account)
        if resolved is None:
            diag = resolver.get_diagnostic()
            if diag is not None:
                print(diag.format_message())
            return 1
        account_name = resolved.account_name
        accid = resolved.accid
        im_appid = resolved.im_appid
        print(f"      account_name: {account_name}")
        print(f"      accid:        {accid}")
        print(f"      im_appid:     {im_appid}")

        print("\n[2/5] Loading UserSig")
        user_sig = load_user_sig(accid)
        if not user_sig:
            print(f"ERROR: token not found for accid={accid}")
            return 1
        print(f"      token:        loaded ({len(user_sig)} chars)")

    injector = MessageInjector(
        dll_path=str(IMSDK_DLL),
        sdk_app_id=int(im_appid),
        accid=accid,
        user_sig=user_sig,
        data_dir=str(IMSDK_DATA),
    )

    def on_recv(message: dict) -> None:
        print(
            "RECV "
            f"conv={message.get('message_conv_id')} "
            f"sender={message.get('message_sender')} "
            f"self={message.get('message_is_from_self')} "
            f"text={text_of(message)!r}"
        )

    injector.add_recv_handler(on_recv)

    print("\n[3/5] TIMInit + TIMAddRecvNewMsgCallback + TIMLogin")
    if not injector.startup():
        print("ERROR: ImSDK startup/login failed")
        injector.shutdown()
        return 1
    print("      login: OK")

    ok = True
    if target_id and send_text:
        conv_kind = "C2C" if args.c2c else "group"
        print(f"\n[4/5] Sending {conv_kind} message to {target_id}: {send_text!r}")
        ok = injector.inject_text(target_id, send_text, is_group=not args.c2c)
        print(f"      send: {'OK' if ok else 'FAILED'}")
    else:
        print("\n[4/5] Sending skipped (no group_id/text)")

    print(f"\n[5/5] Listening for {listen_seconds:.1f}s ...")
    deadline = time.time() + listen_seconds
    last_count = 0
    while time.time() < deadline:
        injector.wait_for_messages(timeout=0.5, min_count=last_count + 1)
        last_count = len(injector.received_messages)

    print(f"      received_count: {len(injector.received_messages)}")
    injector.shutdown()
    print(f"      account: {account_name} ({accid})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
