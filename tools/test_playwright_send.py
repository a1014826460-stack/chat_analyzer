"""Send IM message via Playwright UI automation on WuQuan web page.

Finds the message input field and chat target, types the message,
presses Enter to send. Uses persistent browser context for auto-login.

Usage:
    .\.venv\Scripts\python.exe tools\test_playwright_send.py [group_id] [text]
"""
from __future__ import annotations

import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright


def main() -> int:
    group_id = sys.argv[1] if len(sys.argv) >= 2 else "207191791"
    text = sys.argv[2] if len(sys.argv) >= 3 else "小单 1"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(Path.home() / ".playwright-wuquan"),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        print("[1/2] Opening WuQuan (persistent login)...")
        page.goto("https://www.571919.xyz/", wait_until="domcontentloaded")

        # Wait for login
        logged_in = page.evaluate("() => !!localStorage.getItem('flutter.SpKeyUserSig')")
        if not logged_in:
            print("      Please log in manually (session saved for next time).")
            try:
                page.wait_for_function(
                    "() => !!localStorage.getItem('flutter.SpKeyUserSig')",
                    timeout=120000,
                )
            except Exception:
                print("ERROR: Login timeout."); context.close(); return 1

        # Wait for the chat UI to load
        print("      Waiting for chat UI...")
        time.sleep(5)

        # Flutter Web renders on canvas — no DOM inputs.
        # Click near bottom-right (message input area), type, press Enter.
        print(f"\n[2/2] Sending to {group_id}: {text!r}")

        viewport = page.viewport_size
        w, h = viewport["width"], viewport["height"]

        # Click message input area (bottom, slightly left of center)
        page.mouse.click(w * 0.6, h - 80)
        time.sleep(0.5)

        # Clear any existing text and type
        page.keyboard.press("Control+a")
        time.sleep(0.1)
        page.keyboard.type(text, delay=50)
        time.sleep(0.3)

        # Press Enter to send
        page.keyboard.press("Enter")
        print(f"      Typed '{text}' and pressed Enter.")

        print("\nDone. 5s to verify.")
        time.sleep(5)
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
