"""Manual group-message test via remote thread injection into wq_v2.exe.

Sends a message through WuQuan's existing IM session — does NOT create
a new TIMLogin, so WuQuan stays online.

Usage:
    python tools/test_imsdk_group_message.py [group_id] [text]

Example:
    .\.venv\Scripts\python.exe tools\test_imsdk_group_message.py 207191791 "小单 1"
    .\.venv\Scripts\python.exe tools\test_imsdk_group_message.py 207191791 "大 100"
    .\.venv\Scripts\python.exe tools\test_imsdk_group_message.py  # defaults
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.remote_im_sender import RemoteIMSender


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0

    group_id = sys.argv[1] if len(sys.argv) >= 2 else "207191791"
    text = sys.argv[2] if len(sys.argv) >= 3 else "小单 1"

    # ------------------------------------------------------------------
    # Step 1 — Find wq_v2.exe and ImSDK.dll
    # ------------------------------------------------------------------
    print("[1/3] Locating wq_v2.exe ...")
    try:
        sender = RemoteIMSender()
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}")
        print("Tip: make sure WuQuan (wq_v2.exe) is running and you have admin privileges.")
        return 1

    print(f"      PID:             {sender._pid}")
    print(f"      TIMMsgSendMessage: {hex(sender._func_addr)}")

    # ------------------------------------------------------------------
    # Step 2 — Send group message via remote thread injection
    # ------------------------------------------------------------------
    print(f"\n[2/3] Sending to group {group_id}: {text!r}")
    print(f"      (via CreateRemoteThread — no TIMLogin, no kick-off)")

    ok = sender.inject_text(group_id, text, is_group=True)

    # ------------------------------------------------------------------
    # Step 3 — Cleanup & result
    # ------------------------------------------------------------------
    print("\n[3/3] Releasing process handle")
    sender.shutdown()

    if ok:
        print("SUCCESS: message sent through WuQuan's existing IM session.")
        print("WuQuan should still be online — check the app.")
        return 0

    print("FAILED: remote thread injection did not produce a message ID.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
