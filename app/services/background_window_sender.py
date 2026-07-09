from __future__ import annotations

import ctypes
import logging
import time
from pathlib import Path

from app.services.local_message_verifier import capture_message_cursor, local_message_exists

logger = logging.getLogger(__name__)

WM_CHAR = 0x0102
VK_RETURN = 13


class BackgroundWindowMessageSender:
    """Send text to WuQuan by posting keyboard messages to its window.

    This does not move the mouse, does not activate the window, does not call
    TIMLogin, and does not inject code into WuQuan.  It requires WuQuan to
    already be on the target conversation with the message input focused.
    """

    def __init__(
        self,
        *,
        msg_db_path: str | Path | None,
        hwnd: int | None = None,
        process_name: str = "wq_v2.exe",
        user32: object | None = None,
        verify_timeout_sec: float = 3.0,
        verify_poll_interval_sec: float = 0.2,
        char_delay_sec: float = 0.01,
    ) -> None:
        self._msg_db_path = Path(msg_db_path) if msg_db_path is not None else None
        self._process_name = process_name.casefold()
        self._user32 = user32 or ctypes.windll.user32
        self._verify_timeout_sec = max(float(verify_timeout_sec), 0.0)
        self._verify_poll_interval_sec = max(float(verify_poll_interval_sec), 0.01)
        self._char_delay_sec = max(float(char_delay_sec), 0.0)
        self._hwnd = int(hwnd or 0)
        self._running = False

    def startup(self) -> bool:
        if not self._hwnd:
            self._hwnd = self._find_wuquan_window()
        self._running = bool(self._hwnd and self._is_window(self._hwnd))
        if not self._running:
            logger.error("WuQuan window not found")
        return self._running

    def shutdown(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and bool(self._hwnd and self._is_window(self._hwnd))

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        return self.inject_text(group_id, f"{play_type} {self._fmt_amount(amount)}")

    def inject_text(self, target_id: str, text: str, *, is_group: bool = True) -> bool:
        if not self._hwnd:
            self._hwnd = self._find_wuquan_window()
        if not self._hwnd or not self._is_window(self._hwnd):
            logger.error("WuQuan window not available")
            return False

        cursor = capture_message_cursor(self._msg_db_path, target_id)
        if not self._post_text(self._hwnd, text):
            return False
        if not self._post_enter(self._hwnd):
            return False
        return self.verify_local_message(target_id, text, after_cursor=cursor)

    def verify_local_message(
        self,
        target_id: str,
        text: str,
        *,
        after_cursor: tuple[int, int, int] | None = None,
    ) -> bool:
        if self._msg_db_path is None:
            return True
        deadline = time.monotonic() + self._verify_timeout_sec
        while True:
            if self._message_exists(target_id, text, after_cursor=after_cursor):
                return True
            if time.monotonic() >= deadline:
                logger.error("Background send verification failed: group=%s text=%s", target_id, text)
                return False
            time.sleep(self._verify_poll_interval_sec)

    def _post_text(self, hwnd: int, text: str) -> bool:
        for ch in str(text):
            if not self._post_char(hwnd, ord(ch)):
                logger.error("PostMessageW WM_CHAR failed for %r", ch)
                return False
            if self._char_delay_sec:
                time.sleep(self._char_delay_sec)
        return True

    def _post_enter(self, hwnd: int) -> bool:
        return self._post_char(hwnd, VK_RETURN)

    def _post_char(self, hwnd: int, codepoint: int) -> bool:
        return bool(self._user32.PostMessageW(int(hwnd), WM_CHAR, int(codepoint), 0))

    def _is_window(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindow(int(hwnd)))

    def _message_exists(
        self,
        target_id: str,
        text: str,
        *,
        after_cursor: tuple[int, int, int] | None = None,
    ) -> bool:
        return local_message_exists(self._msg_db_path, target_id, text, after_cursor=after_cursor)

    def _find_wuquan_window(self) -> int:
        # Conservative fallback: find a visible top-level window whose title or
        # class hints at WuQuan.  Precise process matching is intentionally
        # avoided here to keep startup safe and non-invasive.
        found: list[int] = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            if not self._user32.IsWindowVisible(hwnd):
                return True
            title = ctypes.create_unicode_buffer(512)
            self._user32.GetWindowTextW(hwnd, title, 512)
            class_name = ctypes.create_unicode_buffer(256)
            self._user32.GetClassNameW(hwnd, class_name, 256)
            haystack = f"{title.value} {class_name.value}".casefold()
            if "wu quan" in haystack or "wuquan" in haystack or "wq" in haystack or "权" in haystack:
                found.append(int(hwnd))
                return False
            return True

        self._user32.EnumWindows(EnumWindowsProc(callback), 0)
        return found[0] if found else 0

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
