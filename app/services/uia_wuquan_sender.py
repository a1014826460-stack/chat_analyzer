from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Protocol

from app.services.chat_service import ChatLogService
from app.services.local_message_verifier import capture_message_cursor, local_message_exists
from tools.diagnostics.inspect_wuquan_ui import find_windows


logger = logging.getLogger(__name__)


class UiaControl(Protocol):
    element_info: object

    def set_focus(self) -> object: ...

    def click_input(self) -> object: ...

    def type_keys(self, text: str, **kwargs: object) -> object: ...


class UiaWindow(Protocol):
    def descendants(self) -> list[UiaControl]: ...

    def set_focus(self) -> object: ...

    def type_keys(self, text: str, **kwargs: object) -> object: ...


class UiaWuQuanMessageSender:
    """Send WuQuan group text through UI Automation.

    This sender uses the already-open WuQuan desktop window. It does not call
    Tencent IM login and does not inject code. It can switch to a target group
    when the group name can be resolved from local im.db and found through the
    app's search UI.
    """

    def __init__(
        self,
        *,
        msg_db_path: str | Path | None,
        process_name: str = "wq_v2.exe",
        hwnd: int | None = None,
        window_provider: Callable[[], UiaWindow | None] | None = None,
        verify_timeout_sec: float = 30.0,
        verify_poll_interval_sec: float = 0.2,
        switch_wait_sec: float = 0.3,
    ) -> None:
        self._msg_db_path = Path(msg_db_path) if msg_db_path is not None else None
        self._process_name = process_name
        self._hwnd = int(hwnd or 0)
        self._window_provider = window_provider
        self._verify_timeout_sec = max(float(verify_timeout_sec), 0.0)
        self._verify_poll_interval_sec = max(float(verify_poll_interval_sec), 0.01)
        self._switch_wait_sec = max(float(switch_wait_sec), 0.0)
        self._window: UiaWindow | None = None
        self._running = False

    def startup(self) -> bool:
        self._window = self._resolve_window()
        self._running = self._window is not None
        if not self._running:
            logger.error("WuQuan UIA window not available")
        return self._running

    def shutdown(self) -> None:
        self._running = False
        self._window = None

    @property
    def is_running(self) -> bool:
        return self._running and self._window is not None

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        return self.inject_text(group_id, f"{play_type}{self._fmt_amount(amount)}")

    def inject_text(self, target_id: str, text: str, *, is_group: bool = True) -> bool:
        if not is_group:
            logger.error("UIA sender currently supports group messages only")
            return False
        window = self._window or self._resolve_window()
        if window is None:
            logger.error("WuQuan UIA window not available")
            return False
        self._window = window
        self._running = True

        group_name = self._resolve_group_name(target_id)
        if not self._ensure_target_group(window, str(target_id), group_name):
            logger.error("Cannot open target WuQuan group: id=%s name=%s", target_id, group_name)
            return False

        cursor = self.capture_message_cursor(target_id)
        message_edit = self._find_message_edit(window)
        if message_edit is None:
            logger.error("WuQuan message input Edit control not found")
            return False
        try:
            message_edit.set_focus()
            message_edit.type_keys(str(text), with_spaces=True)
            message_edit.type_keys("{ENTER}")
        except Exception as exc:
            logger.error("UIA message send failed: %s", exc)
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
                logger.error("UIA sent but local msg_0.db verification failed: group=%s text=%s", target_id, text)
                return False
            time.sleep(self._verify_poll_interval_sec)

    def _resolve_window(self) -> UiaWindow | None:
        if self._window_provider is not None:
            return self._window_provider()
        try:
            from pywinauto import Desktop
        except Exception as exc:
            logger.error("pywinauto is required for UIA sender: %s", exc)
            return None

        hwnd = self._hwnd
        if not hwnd:
            windows = find_windows(self._process_name)
            hwnd = windows[0].hwnd if windows else 0
            self._hwnd = hwnd
        if not hwnd:
            return None
        try:
            return Desktop(backend="uia").window(handle=hwnd)
        except Exception as exc:
            logger.error("Failed to connect WuQuan UIA window hwnd=%s: %s", hwnd, exc)
            return None

    def _ensure_target_group(self, window: UiaWindow, group_id: str, group_name: str) -> bool:
        if self._is_current_group(window, group_id, group_name):
            return True
        if not group_name:
            return False
        if not self._search_and_open_group(window, group_name):
            return False
        if self._switch_wait_sec:
            time.sleep(self._switch_wait_sec)
        # Some Flutter UIA trees do not refresh immediately through the same
        # wrapper after clicking a search result. Continue to send and let the
        # local msg_0.db target/content verification be the source of truth.
        return True

    def _is_current_group(self, window: UiaWindow, group_id: str, group_name: str) -> bool:
        header_names = [
            self._control_name(ctrl)
            for ctrl in self._safe_descendants(window)
            if self._control_type(ctrl) == "Text" and self._rect_tuple(ctrl)[1] < 120
        ]
        if group_name and any(name.strip() == group_name for name in header_names):
            return True
        names = [self._control_name(ctrl) for ctrl in self._safe_descendants(window)]
        # In the current chat, historical message text may contain the group id
        # even when the header is a display name.
        return bool(group_id and any(group_id in name for name in names))

    def _search_and_open_group(self, window: UiaWindow, group_name: str) -> bool:
        search_edit = self._find_search_edit(window)
        if search_edit is None:
            logger.error("WuQuan search Edit control not found")
            return False
        try:
            search_edit.set_focus()
            if hasattr(search_edit, "set_edit_text"):
                search_edit.set_edit_text(group_name)  # type: ignore[attr-defined]
            else:
                search_edit.type_keys("^a")
                search_edit.type_keys(group_name, with_spaces=True)
        except Exception as exc:
            logger.error("WuQuan group search input failed: %s", exc)
            return False

        if self._switch_wait_sec:
            time.sleep(self._switch_wait_sec)
        result = self._find_named_clickable(window, group_name)
        if result is None:
            logger.error("WuQuan search result not found: %s", group_name)
            return False
        try:
            result.click_input()
            return True
        except Exception as exc:
            logger.error("WuQuan search result click failed: %s", exc)
            return False

    def _find_search_edit(self, window: UiaWindow) -> UiaControl | None:
        edits = self._edit_controls(window)
        if len(edits) >= 2:
            return sorted(edits, key=lambda ctrl: self._rect_tuple(ctrl))[0]
        return None

    def _find_message_edit(self, window: UiaWindow) -> UiaControl | None:
        edits = self._edit_controls(window)
        if not edits:
            return None
        return sorted(edits, key=lambda ctrl: self._rect_tuple(ctrl)[1])[-1]

    def _edit_controls(self, window: UiaWindow) -> list[UiaControl]:
        return [ctrl for ctrl in self._safe_descendants(window) if self._control_type(ctrl) == "Edit"]

    def _find_named_clickable(self, window: UiaWindow, name: str) -> UiaControl | None:
        controls = self._safe_descendants(window)
        exact = [ctrl for ctrl in controls if self._control_name(ctrl).strip() == name]
        if exact:
            return exact[0]
        partial = [ctrl for ctrl in controls if name and name in self._control_name(ctrl)]
        return partial[0] if partial else None

    def _resolve_group_name(self, group_id: str) -> str:
        if not self._msg_db_path:
            return ""
        try:
            groups = ChatLogService().list_groups_from_db(self._msg_db_path)
        except Exception:
            logger.debug("Failed to resolve group name for %s", group_id, exc_info=True)
            return ""
        for group in groups:
            if str(group.group_id).strip() == str(group_id).strip():
                return str(group.group_name).strip()
        return ""

    def capture_message_cursor(self, target_id: str) -> tuple[int, int, int]:
        return capture_message_cursor(self._msg_db_path, target_id)

    def _message_exists(
        self,
        target_id: str,
        text: str,
        *,
        after_cursor: tuple[int, int, int] | None = None,
    ) -> bool:
        return local_message_exists(self._msg_db_path, target_id, text, after_cursor=after_cursor)

    @staticmethod
    def _safe_descendants(window: UiaWindow) -> list[UiaControl]:
        try:
            return list(window.descendants())
        except Exception:
            return []

    @staticmethod
    def _control_type(ctrl: UiaControl) -> str:
        return str(getattr(getattr(ctrl, "element_info", None), "control_type", "") or "")

    @staticmethod
    def _control_name(ctrl: UiaControl) -> str:
        return str(getattr(getattr(ctrl, "element_info", None), "name", "") or "")

    @staticmethod
    def _rect_tuple(ctrl: UiaControl) -> tuple[int, int, int, int]:
        rect = getattr(getattr(ctrl, "element_info", None), "rectangle", None)
        return (
            int(getattr(rect, "left", 0) or 0),
            int(getattr(rect, "top", 0) or 0),
            int(getattr(rect, "right", 0) or 0),
            int(getattr(rect, "bottom", 0) or 0),
        )

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
