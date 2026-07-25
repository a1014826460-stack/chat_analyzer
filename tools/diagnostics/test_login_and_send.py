"""Login via WuQuan API → send message via ImSDK ctypes.

Usage:
    .\.venv\Scripts\python.exe tools\test_login_and_send.py <phone> <code> [group_id] [text]

Example:
    .\.venv\Scripts\python.exe tools\test_login_and_send.py 13727744565 608521 207191791 "小单 1"
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from app.services.message_injector import MessageInjector

IMSDK_DLL = ROOT / "WuQuan" / "ImSDK.dll"
IMSDK_DATA = ROOT / "WuQuan" / "data"
LOGIN_URL = "https://www.571919.xyz/wuquan/userApi/userLogin"


def login_api(phone: str, code: str) -> dict | None:
    """Call WuQuan login API. Returns parsed response data or None."""
    import urllib3
    urllib3.disable_warnings()

    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })

    # Visit homepage first (gets Cloudflare cookie if needed)
    try:
        session.get("https://www.571919.xyz/", timeout=15)
    except Exception:
        pass

    resp = session.post(
        LOGIN_URL,
        json={
            "isUnpack": True, "userName": phone, "code": code,
            "type": "1", "serverId": "88",
            "deviceId": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        headers={
            "app-authorization": "wuquan", "channel": "web", "loginrole": "3",
            "origin": "https://www.571919.xyz", "referer": "https://www.571919.xyz/",
        },
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    data = resp.json()
    if data.get("code") != 200:
        print(f"  API error: {data.get('msg', 'unknown')}")
        return None

    return data["data"]


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python tools/test_login_and_send.py <phone> <code> [group_id] [text]")
        return 2

    phone = sys.argv[1]
    code = sys.argv[2]
    group_id = sys.argv[3] if len(sys.argv) >= 4 else "207191791"
    text = sys.argv[4] if len(sys.argv) >= 5 else "小单 1"

    # Step 1 — Login via API
    print(f"[1/4] Login API: phone={phone} code={code}")
    login_data = login_api(phone, code)
    if login_data is None:
        return 1

    accid = login_data["accid"]
    token = login_data["token"]
    nickname = login_data["nickName"]
    im_appid = login_data["imAppid"]
    print(f"      nick={nickname}, accid={accid}, imAppid={im_appid}")
    print(f"      token={token[:50]}...")

    # Step 2 — ImSDK init + login
    print(f"\n[2/4] ImSDK startup for {accid}...")
    injector = MessageInjector(
        dll_path=str(IMSDK_DLL),
        sdk_app_id=int(im_appid),
        accid=accid,
        user_sig=token,
        data_dir=str(IMSDK_DATA),
    )
    if not injector.startup():
        print("ERROR: ImSDK startup failed.")
        return 1
    print("      TIMInit + TIMLogin: OK")

    # Step 3 — Send message
    print(f"\n[3/4] Sending to {group_id}: {text!r}")
    ok = injector.inject_text(group_id, text, is_group=True)

    # Step 4 — Cleanup
    print("\n[4/4] Shutdown")
    injector.shutdown()

    if ok:
        print(f"SUCCESS! Message sent as {nickname}({accid}) to {group_id}")
        return 0

    print("FAILED: send returned False")
    print("Tip: make sure this account is a member of the target group.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
