"""Message injection via Tencent Cloud IM SDK (ImSDK.dll) ctypes calls.

Uses TIMLogin + TIMMsgSendMessage to send messages directly through
the IM network.  A background thread runs a Windows message pump to
drive SDK asynchronous callbacks.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Callback type — MUST be defined before any SDK calls
# ---------------------------------------------------------------------------
TIMCommCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_int32, ctypes.c_char_p, ctypes.c_void_p
)
TIMRecvNewMsgCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_char_p, ctypes.c_void_p
)


# ---------------------------------------------------------------------------
# MessageInjector
# ---------------------------------------------------------------------------
class MessageInjector:
    """Send messages via Tencent Cloud IM SDK (ImSDK.dll).

    Usage::

        injector = MessageInjector(dll_path, sdk_app_id, accid, user_sig)
        if injector.startup():
            injector.inject_bet("207191791", "大", 100)
            injector.shutdown()
    """

    _CALLBACK_TIMEOUT = 30.0

    def __init__(
        self,
        dll_path: str | Path,
        sdk_app_id: int,
        accid: str,
        user_sig: str,
        data_dir: str | Path | None = None,
    ) -> None:
        self._dll_path = Path(dll_path)
        self._sdk_app_id = sdk_app_id
        self._accid = accid
        self._user_sig = user_sig
        self._data_dir = Path(data_dir) if data_dir else self._dll_path.parent / "data"

        self._dll: ctypes.CDLL | None = None
        self._lock = threading.Lock()
        self._running = False
        self._pump_running = False
        self._logged_in = threading.Event()
        self._login_error: str | None = None

        # Per-call result holders
        self._msg_result: list[tuple[int, str]] = []
        self._received_messages: list[dict] = []
        self._recv_handlers: list[Callable[[dict], None]] = []
        self._recv_condition = threading.Condition()

        # Keep-alive references
        self._login_cb: TIMCommCallback | None = None
        self._msg_cb: TIMCommCallback | None = None
        self._recv_cb: TIMRecvNewMsgCallback | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        """Send a betting message to a group. Returns True on success."""
        content = f"{play_type} {self._fmt_amount(amount)}"
        return self._send(group_id, 2, content)

    def inject_text(
        self, target_id: str, text: str, *, is_group: bool = True,
    ) -> bool:
        """Send an arbitrary text message.

        Args:
            target_id: Group ID (is_group=True) or user ID (is_group=False).
            text: Message content.
            is_group: True for group message, False for C2C.
        """
        return self._send(target_id, 2 if is_group else 1, text)

    def add_recv_handler(self, handler: Callable[[dict], None]) -> None:
        """Register a Python handler for every newly received IM message."""
        with self._recv_condition:
            self._recv_handlers.append(handler)

    def clear_received_messages(self) -> None:
        """Clear the in-memory receive queue."""
        with self._recv_condition:
            self._received_messages.clear()

    @property
    def received_messages(self) -> list[dict]:
        """Return a snapshot of messages received through TIMAddRecvNewMsgCallback."""
        with self._recv_condition:
            return list(self._received_messages)

    def wait_for_messages(
        self,
        timeout: float = 30.0,
        predicate: Callable[[dict], bool] | None = None,
        *,
        min_count: int = 1,
    ) -> list[dict]:
        """Wait until at least ``min_count`` queued messages match ``predicate``.

        The Tencent IM Windows SDK dispatches callbacks through Windows messages
        in this ctypes setup, so this method pumps messages while waiting.
        """
        deadline = time.time() + timeout
        predicate = predicate or (lambda _msg: True)

        while time.time() < deadline:
            self._pump_once()
            with self._recv_condition:
                matched = [msg for msg in self._received_messages if predicate(msg)]
                if len(matched) >= min_count:
                    return matched
                remaining = max(0.0, min(0.05, deadline - time.time()))
                if remaining:
                    self._recv_condition.wait(timeout=remaining)

        with self._recv_condition:
            return [msg for msg in self._received_messages if predicate(msg)]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self) -> bool:
        """Load DLL, init SDK, login. Returns True on success."""
        with self._lock:
            if self._running:
                return self._logged_in.is_set()

            # -- Load DLL --
            try:
                import os
                os.add_dll_directory(str(self._dll_path.parent))
                self._dll = ctypes.CDLL(str(self._dll_path))
            except OSError as exc:
                logger.error("Failed to load ImSDK.dll: %s", exc)
                return False

            # -- TIMInit --
            dll = self._dll  # local alias for ctypes internals
            dll.TIMInit.restype = ctypes.c_int
            ret = dll.TIMInit(self._sdk_app_id, json.dumps({
                "sdk_config_file_path": str(self._data_dir),
            }).encode("utf-8"))
            if ret != 0:
                logger.error("TIMInit failed: %d", ret)
                return False
            logger.info("TIMInit OK (sdk_app_id=%d)", self._sdk_app_id)

            self._register_recv_callback()

            # -- TIMLogin --
            self._logged_in.clear()
            self._login_error = None

            # Register this injector so static callbacks can reach it
            _set_active_injector(self)

            self._login_cb = TIMCommCallback(self._login_handler)

            dll.TIMLogin.argtypes = [
                ctypes.c_char_p, ctypes.c_char_p,
                ctypes.c_void_p, ctypes.c_void_p,
            ]
            dll.TIMLogin.restype = ctypes.c_int
            ret = dll.TIMLogin(
                self._accid.encode("utf-8"),
                self._user_sig.encode("utf-8"),
                self._login_cb,
                None,
            )
            if ret != 0:
                logger.error("TIMLogin returned %d", ret)
                return False

            self._running = True

        # Wait for async login — pump INLINE
        deadline = time.time() + self._CALLBACK_TIMEOUT
        while time.time() < deadline and not self._logged_in.is_set():
            self._pump_once()
            time.sleep(0.05)

        if not self._logged_in.is_set():
            logger.error("Login timed out after %.0fs", self._CALLBACK_TIMEOUT)
            return False
        if self._login_error:
            logger.error("Login failed: %s", self._login_error)
            return False

        time.sleep(1.0)
        logger.info("Logged in as %s", self._accid)
        return True

    def shutdown(self) -> None:
        """Logout and cleanup SDK."""
        with self._lock:
            if not self._running or self._dll is None:
                return
            if self._recv_cb is not None:
                try:
                    self._dll.TIMRemoveRecvNewMsgCallback.argtypes = [ctypes.c_void_p]
                    self._dll.TIMRemoveRecvNewMsgCallback.restype = None
                except AttributeError:
                    pass
                try:
                    self._dll.TIMRemoveRecvNewMsgCallback(self._recv_cb)
                except Exception as exc:
                    logger.debug("TIMRemoveRecvNewMsgCallback: %s", exc)
            try:
                self._dll.TIMLogout.restype = ctypes.c_int
                self._dll.TIMLogout.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p,
                ]
                self._dll.TIMLogout(None, None)
            except Exception as exc:
                logger.debug("TIMLogout: %s", exc)
            time.sleep(0.5)
            try:
                self._dll.TIMUninit.restype = ctypes.c_int
                self._dll.TIMUninit()
            except Exception as exc:
                logger.debug("TIMUninit: %s", exc)

            self._pump_running = False
            self._running = False
            self._logged_in.clear()
            _set_active_injector(None)
            logger.info("ImSDK shutdown complete")

    def __enter__(self) -> "MessageInjector":
        self.startup()
        return self

    def __exit__(self, *args: object) -> None:
        self.shutdown()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running and self._logged_in.is_set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _login_handler(code: int, desc: ctypes.c_char_p, _ud: ctypes.c_void_p) -> None:
        """Static callback for TIMLogin — dispatched via injector registry."""
        desc_str = desc.decode("utf-8") if desc else ""
        logger.info("TIMLogin callback: code=%d desc=%s", code, desc_str)
        # We need to reach the injector instance.  Since this is a
        # static method, we store the current injector in a module-level
        # slot before calling TIMLogin.  See ``_active_injector``.
        inj = _active_injector
        if inj is not None:
            if code == 0:
                inj._logged_in.set()
            else:
                inj._login_error = desc_str
                inj._logged_in.set()

    @staticmethod
    def _msg_handler(code: int, desc: ctypes.c_char_p, _ud: ctypes.c_void_p) -> None:
        """Static callback for TIMMsgSendMessage."""
        desc_str = desc.decode("utf-8") if desc else ""
        logger.info("TIMMsgSendMessage callback: code=%d desc=%s", code, desc_str)
        inj = _active_injector
        if inj is not None:
            inj._msg_result.append((code, desc_str))

    def _register_recv_callback(self) -> None:
        """Wire TIMAddRecvNewMsgCallback and keep the callback alive."""
        if self._dll is None:
            return

        self._recv_cb = TIMRecvNewMsgCallback(self._recv_new_msg_handler)
        try:
            self._dll.TIMAddRecvNewMsgCallback.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
            ]
            self._dll.TIMAddRecvNewMsgCallback.restype = None
        except AttributeError:
            # Unit-test fakes use normal Python methods, not ctypes functions.
            pass
        self._dll.TIMAddRecvNewMsgCallback(self._recv_cb, None)
        logger.info("TIMAddRecvNewMsgCallback registered")

    def _recv_new_msg_handler(
        self, json_msg_array: ctypes.c_char_p, _ud: ctypes.c_void_p,
    ) -> None:
        """Callback for newly received messages.

        Tencent's C API passes a JSON array string.  Each item is appended to
        ``_received_messages`` and dispatched to registered Python handlers.
        """
        raw = json_msg_array.decode("utf-8", errors="replace") if json_msg_array else "[]"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.exception("Failed to decode TIM receive payload: %r", raw[:500])
            return

        if isinstance(parsed, dict):
            messages = [parsed]
        elif isinstance(parsed, list):
            messages = [msg for msg in parsed if isinstance(msg, dict)]
        else:
            logger.warning("Unexpected TIM receive payload type: %s", type(parsed).__name__)
            return

        with self._recv_condition:
            self._received_messages.extend(messages)
            handlers = list(self._recv_handlers)
            self._recv_condition.notify_all()

        for message in messages:
            logger.info(
                "Received IM message: conv=%s sender=%s",
                message.get("message_conv_id") or message.get("message_conv_id".upper()),
                message.get("message_sender") or message.get("message_sender".upper()),
            )
            for handler in handlers:
                try:
                    handler(message)
                except Exception:
                    logger.exception("Receive handler failed")

    def _msg_pump(self) -> None:
        """Windows message pump (background thread)."""
        while self._pump_running:
            self._pump_once()
            time.sleep(0.05)

    @staticmethod
    def _pump_once() -> None:
        """Dispatch all pending Windows messages for SDK callbacks."""
        user32 = ctypes.windll.user32
        msg = ctypes.wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _send(self, target_id: str, conv_type: int, text: str) -> bool:
        """Send a text message via TIMMsgSendMessage."""
        if self._dll is None or not self.is_running:
            logger.error("Injector not running")
            return False

        self._msg_result.clear()
        self._msg_cb = TIMCommCallback(self._msg_handler)

        msg_json = json.dumps({
            "message_elem_array": [
                {"elem_type": 0, "text_elem_content": text}
            ],
        }, ensure_ascii=False).encode("utf-8")

        msg_buf = ctypes.create_string_buffer(512)

        dll = self._dll
        dll.TIMMsgSendMessage.argtypes = [
            ctypes.c_char_p, ctypes.c_int,
            ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_void_p, ctypes.c_void_p,
        ]
        dll.TIMMsgSendMessage.restype = ctypes.c_int

        ret = dll.TIMMsgSendMessage(
            target_id.encode("utf-8"), conv_type,
            msg_json, msg_buf, self._msg_cb, None,
        )
        msg_id = msg_buf.value.decode("utf-8") if msg_buf.value else "NONE"
        if ret != 0:
            logger.error("TIMMsgSendMessage returned %d (target=%s)", ret, target_id)
            return False

        logger.debug("TIMMsgSendMessage queued: msg_id=%s target=%s", msg_id, target_id)

        # Pump messages while waiting for the callback
        deadline = time.time() + self._CALLBACK_TIMEOUT
        while time.time() < deadline and not self._msg_result:
            self._pump_once()
            time.sleep(0.05)

        if not self._msg_result:
            logger.error("Send callback timed out (target=%s)", target_id)
            return False

        code, desc = self._msg_result[0]
        if code != 0:
            logger.error("Send failed: code=%d desc=%s (target=%s)", code, desc, target_id)
            return False

        logger.info("Message sent: msg_id=%s target=%s", msg_id, target_id)
        return True

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Registry — allows static callbacks to reach the injector instance
# ---------------------------------------------------------------------------
_active_injector: "MessageInjector | None" = None


def _set_active_injector(inj: "MessageInjector | None") -> None:
    global _active_injector
    _active_injector = inj
