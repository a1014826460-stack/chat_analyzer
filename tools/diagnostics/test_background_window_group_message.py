from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing as a package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.account_resolver import AccountResolver
from app.services.background_window_sender import BackgroundWindowMessageSender


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a group text through the already-open WuQuan window using background PostMessageW."
    )
    parser.add_argument("account", help="WuQuan account nickname or accid, for locating msg_0.db")
    parser.add_argument("group_id", help="target group id, e.g. 207191791")
    parser.add_argument("text", help="message text, e.g. 小单 1")
    parser.add_argument("--timeout", type=float, default=5.0, help="local msg_0.db verification timeout seconds")
    parser.add_argument("--no-prompt", action="store_true", help="do not wait for Enter before sending")
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

    print("\n[2/4] Prepare WuQuan")
    print(f"      Open WuQuan, enter group {args.group_id}, and make sure the message input box is ready.")
    print("      This script will not move the mouse and will not activate the window.")
    if not args.no_prompt:
        input("      Press Enter to send...")

    print(f"\n[3/4] Sending in background to group {args.group_id}: {args.text!r}")
    sender = BackgroundWindowMessageSender(
        msg_db_path=resolved.msg_db,
        verify_timeout_sec=args.timeout,
    )
    if not sender.startup():
        print("FAILED: WuQuan window not found. Keep WuQuan running and visible in the desktop session.")
        return 1
    print(f"      hwnd:         {sender.hwnd}")
    ok = sender.inject_text(args.group_id, args.text)
    sender.shutdown()

    print("\n[4/4] Result")
    if ok:
        print("OK: message was posted and found in local msg_0.db.")
        return 0
    print("FAILED: message was not verified in msg_0.db within timeout.")
    print("Tip: confirm the target group chat was open and the input box had focus before sending.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
