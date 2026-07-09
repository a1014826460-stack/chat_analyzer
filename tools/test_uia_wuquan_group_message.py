from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import AccountResolver
from app.services.chat_service import ChatLogService
from app.services.uia_wuquan_sender import UiaWuQuanMessageSender


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a WuQuan group text through UI Automation.")
    parser.add_argument("account", help="WuQuan account nickname or accid, for locating msg_0.db")
    parser.add_argument("group_id", help="target group id, e.g. 207191791")
    parser.add_argument("text", help="message text, e.g. 小单 1")
    parser.add_argument("--timeout", type=float, default=30.0, help="local msg_0.db verification timeout seconds")
    parser.add_argument("--hwnd", type=int, default=0, help="specific WuQuan window handle")
    args = parser.parse_args()

    print(f"[1/4] Resolving account: {args.account}")
    resolved = AccountResolver().resolve(args.account)
    if resolved is None:
        print("FAILED: cannot locate account msg_0.db")
        return 1
    print(f"      account_name: {resolved.account_name}")
    print(f"      accid:        {resolved.accid}")
    print(f"      im_appid:     {resolved.im_appid}")
    print(f"      msg_db:       {resolved.msg_db}")

    groups = ChatLogService().list_groups_from_db(resolved.msg_db)
    group_name = next((g.group_name for g in groups if str(g.group_id) == str(args.group_id)), "")
    print("\n[2/4] Target group")
    print(f"      group_id:     {args.group_id}")
    print(f"      group_name:   {group_name or '(not found in im.db; current chat must already be target)'}")

    print(f"\n[3/4] Sending via UIA to group {args.group_id}: {args.text!r}")
    sender = UiaWuQuanMessageSender(
        msg_db_path=resolved.msg_db,
        hwnd=args.hwnd or None,
        verify_timeout_sec=args.timeout,
    )
    if not sender.startup():
        print("FAILED: cannot connect WuQuan UIA window. Install pywinauto/comtypes and keep WuQuan running.")
        return 1
    print(f"      hwnd:         {sender.hwnd}")
    ok = sender.inject_text(args.group_id, args.text)
    sender.shutdown()

    print("\n[4/4] Result")
    if ok:
        print("OK: UIA send completed and target group/content row was found in msg_0.db.")
        return 0
    print("FAILED: UIA send was not verified in msg_0.db within timeout.")
    print("Tip: run tools/inspect_wuquan_ui.py again and confirm Edit controls and target group name are visible.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
