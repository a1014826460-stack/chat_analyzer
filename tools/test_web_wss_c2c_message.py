"""Send a C2C message through TencentCloudChat Web WSS without ImSDK login.

This intentionally reuses the Web WSS protocol in tests/tests_wss.py, so it does
not call ImSDK and will not trigger the native SDK multi-login/kick behavior.

Examples:
    .\.venv\Scripts\python.exe tools\test_web_wss_c2c_message.py --from lin2225427 --to LYGG88888 --text "WSS Web?????"
    .\.venv\Scripts\python.exe tools\test_web_wss_c2c_message.py --from A7MYtCxL8 --to x1DuArYgV --text "hello"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import DEFAULT_SHARED_PREFS
from app.services.wuquan_account_mapping import (
    WuQuanLoginAccount,
    load_shared_preferences,
    resolve_im_accid,
    resolve_login_account,
)
from tests.tests_wss import ImWssClient, WS_ENDPOINTS


def parse_explicit_sender(
    *,
    from_id: str,
    from_accid: str,
    user_sig: str,
    sdk_app_id: str,
    nick: str = "",
    avatar: str = "",
) -> WuQuanLoginAccount:
    return WuQuanLoginAccount(
        accid=str(from_accid or from_id).strip(),
        appid=str(from_id).strip(),
        user_sig=str(user_sig).strip(),
        im_appid=str(sdk_app_id or "20011216").strip(),
        nick_name=str(nick or "").strip(),
        avatar=str(avatar or "").strip(),
    )


def _account_from_args(args: argparse.Namespace, payload: dict) -> WuQuanLoginAccount:
    account = resolve_login_account(args.from_id, payload)
    if account is not None and account.user_sig:
        return account
    if args.user_sig:
        return parse_explicit_sender(
            from_id=args.from_id,
            from_accid=args.from_accid or (account.accid if account is not None else args.from_id),
            user_sig=args.user_sig,
            sdk_app_id=args.sdk_app_id,
            nick=args.nick or (account.nick_name if account is not None else ""),
            avatar=args.avatar or (account.avatar if account is not None else ""),
        )
    raise RuntimeError(
        f"??? shared_preferences ????? {args.from_id!r} ? IM token?"
        "?? --from-accid ? --user-sig?????????"
    )


async def _run(args: argparse.Namespace) -> int:
    payload = load_shared_preferences(args.prefs) if args.prefs else {}
    sender = _account_from_args(args, payload)
    to_accid = resolve_im_accid(args.to, payload) if args.resolve_to else args.to
    sdk_app_id = int(args.sdk_app_id or sender.im_appid or 20011216)

    print("[1/5] Resolve accounts")
    print(f"      from: input={args.from_id!r} appid={sender.appid!r} accid={sender.accid!r}")
    print(f"      to:   input={args.to!r} accid={to_accid!r}")
    if args.to == to_accid and args.resolve_to:
        print("      note: ???????????????????? IM To_Account ??")

    client = ImWssClient(
        sdk_app_id=sdk_app_id,
        identifier=sender.accid,
        user_sig=sender.user_sig,
        endpoint=args.endpoint,
    )
    print(f"[2/5] Connecting WSS: {client.endpoint}")
    await client.connect()
    try:
        print("[3/5] Web WSS wslogin")
        login_resp = await client.login()
        print(
            "      login OK: "
            f"TinyId={client.tiny_id} InstId={client.status_instid} "
            f"HelloInterval={login_resp.get('body', {}).get('HelloInterval')}"
        )

        print("[4/5] Heartbeat")
        hb = await client.heartbeat()
        print(f"      heartbeat ret={hb.get('head', {}).get('retcode')} {hb.get('head', {}).get('retstr')}")

        print(f"[5/5] Send C2C via openim.sendmsg text={args.text!r}")
        resp = await client.send_c2c_text(
            to_accid,
            args.text,
            nick=args.nick or sender.nick_name or "",
            avatar=args.avatar or sender.avatar or "",
        )
        print("      send head:", json.dumps(resp.get("head", {}), ensure_ascii=False))
        print("      send body:", json.dumps(resp.get("body", {}), ensure_ascii=False))
        body = resp.get("body", {})
        if body.get("ActionStatus") == "OK" and int(body.get("ErrorCode", -1)) == 0:
            print("SUCCESS: Web WSS C2C message accepted by Tencent IM.")
            return 0
        print("FAILED: Web WSS request reached Tencent IM but was rejected.")
        if int(body.get("ErrorCode", -1)) == 20003:
            print("????????? IM accid?????? appid/??ID ????? accid?")
        return 1
    finally:
        await client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send C2C text through Web WSS, not ImSDK")
    parser.add_argument("--from", dest="from_id", default="lin2225427", help="sender appid/accid/phone in local login cache")
    parser.add_argument("--from-accid", default="", help="explicit sender IM accid when --from is only a business appid")
    parser.add_argument("--to", default="LYGG88888", help="receiver appid/accid/phone; resolved locally by default")
    parser.add_argument("--text", default="WSS Web?????")
    parser.add_argument("--prefs", default=str(DEFAULT_SHARED_PREFS), help="shared_preferences.json path")
    parser.add_argument("--sdk-app-id", default="20011216")
    parser.add_argument("--user-sig", default="", help="override sender Tencent UserSig/token")
    parser.add_argument("--nick", default="")
    parser.add_argument("--avatar", default="")
    parser.add_argument("--endpoint", default=WS_ENDPOINTS[0], choices=WS_ENDPOINTS)
    parser.add_argument("--no-resolve-to", dest="resolve_to", action="store_false", help="do not map receiver appid to accid")
    parser.set_defaults(resolve_to=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(parse_args())))
