"""Send IM messages via WebSocket (wss://wsssgp.im.qcloud.com).

Uses a separate WebSocket connection with unique instanceid — does NOT
kick the running WuQuan client offline.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import threading
import time

import websocket

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError:
    AES = None
    pad = None

logger = logging.getLogger(__name__)

WS_URL = "wss://wsssgp.im.qcloud.com/binfo"
FRONTEND_AAS_KEY = "666888"


def _encrypt_content(plain: str) -> str:
    """AES-ECB encrypt + Base64, using the same key as WuQuan local DB."""
    if AES is None or pad is None:
        return plain
    key = FRONTEND_AAS_KEY.encode("utf-8")
    if len(key) < 16:
        key = key + (b"\x00" * (16 - len(key)))
    cipher = AES.new(key[:16], AES.MODE_ECB)
    padded = pad(plain.encode("utf-8"), AES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode("ascii")


def _make_instanceid() -> str:
    """Generate a unique instance ID (32-char hex, like WuQuan's)."""
    raw = f"{time.time()}-{random.random()}-python-bot"
    return hashlib.md5(raw.encode()).hexdigest()


class WsMessageSender:
    """Send group/C2C messages via Tencent IM WebSocket protocol."""

    def __init__(
        self,
        sdk_app_id: int,
        identifier: str,
        user_sig: str,
        *,
        tiny_id: str = "144115266725404712",
    ) -> None:
        self._sdk_app_id = sdk_app_id
        self._identifier = identifier
        self._user_sig = user_sig
        self._tiny_id = tiny_id
        self._instanceid = _make_instanceid()
        self._seq = random.randint(1, 99999999)
        self._a2: str | None = None
        self._ws: websocket.WebSocket | None = None
        self._running = False
        self._lock = threading.Lock()
        self._responses: dict[int, dict] = {}
        self._response_events: dict[int, threading.Event] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def startup(self) -> bool:
        """Connect and login. Returns True on success."""
        # Build WebSocket URL
        rand = random.random()
        url = (
            f"{WS_URL}?sdkappid={self._sdk_app_id}"
            f"&instanceid={self._instanceid}"
            f"&random={rand}&platform=7&host=windows&version=-1&sdkversion=3.2.1"
        )
        logger.info("WebSocket connecting: %s...", url[:80])

        self._ws = websocket.WebSocket()
        try:
            self._ws.connect(url, timeout=15)
            self._ws.settimeout(2)  # recv timeout for reader thread
        except Exception as exc:
            logger.error("WebSocket connect failed: %s", exc)
            return False

        self._running = True
        # Start reader thread
        t = threading.Thread(target=self._reader, daemon=True, name="ws-reader")
        t.start()

        # Login
        if not self._login():
            logger.error("WebSocket login failed")
            return False

        logger.info("WebSocket logged in (instanceid=%s)", self._instanceid[:16])
        return True

    def shutdown(self) -> None:
        """Close WebSocket."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    @property
    def is_running(self) -> bool:
        return self._running and self._ws is not None

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        text = f"{play_type} {self._fmt_amount(amount)}"
        return self.inject_text(group_id, text)

    def inject_text(self, target_id: str, text: str, *, is_group: bool = True) -> bool:
        """Send a text message."""
        if is_group:
            return self._send_group_msg(target_id, text)
        else:
            return self._send_c2c_msg(target_id, text)

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    def _send_group_msg(self, group_id: str, text: str) -> bool:
        encrypted = _encrypt_content(text)
        body = {
            "GroupId": group_id,
            "Random": random.randint(1, 0x7FFFFFFF),
            "MsgBody": [
                {"MsgType": "TIMTextElem", "MsgContent": {"Text": encrypted}}
            ],
            "From_Account": self._identifier,
        }
        return self._rpc("group_open_http_svc.send_group_msg", body)

    def _send_c2c_msg(self, user_id: str, text: str) -> bool:
        encrypted = _encrypt_content(text)
        body = {
            "SyncOtherMachine": 2,
            "From_Account": self._identifier,
            "To_Account": user_id,
            "MsgRandom": random.randint(1, 0x7FFFFFFF),
            "MsgBody": [
                {"MsgType": "TIMTextElem", "MsgContent": {"Text": encrypted}}
            ],
        }
        return self._rpc("openim.sendmsg", body)

    # ------------------------------------------------------------------
    # WebSocket protocol
    # ------------------------------------------------------------------

    def _login(self) -> bool:
        self._seq += 1
        seq = self._seq
        head = {
            "ver": "v4",
            "platform": 7,
            "websdkappid": 537048168,
            "websdkversion": "1.7.3",
            "sdkappid": self._sdk_app_id,
            "contenttype": "json",
            "reqtime": int(time.time()),
            "identifier": self._identifier,
            "usersig": self._user_sig,
            "status_instid": random.randint(100000000, 999999999),
            "sdkability": 192371,
            "tjgID": "",
            "servcmd": "im_open_status.wslogin",
            "seq": seq,
        }
        body = {"State": "Online", "is_web_uniapp": 0, "InstType": 0}
        resp = self._rpc_raw(head, body, seq, timeout=10)
        if resp is None:
            return False
        # Extract A2Key from response body
        resp_body = resp.get("body", {})
        self._a2 = resp_body.get("A2Key", "")
        self._tiny_id = resp_body.get("TinyId", self._tiny_id)
        return bool(self._a2)

    def _rpc(self, servcmd: str, body: dict, timeout: float = 15.0) -> bool:
        self._seq += 1
        seq = self._seq
        head = {
            "ver": "v4",
            "platform": 7,
            "websdkappid": 537048168,
            "websdkversion": "1.7.3",
            "a2": self._a2 or "",
            "tinyid": self._tiny_id,
            "sdkappid": self._sdk_app_id,
            "contenttype": "json",
            "reqtime": int(time.time()),
            "identifier": self._identifier,
            "usersig": self._user_sig,
            "status_instid": random.randint(100000000, 999999999),
            "sdkability": 192371,
            "servcmd": servcmd,
            "seq": seq,
        }
        resp = self._rpc_raw(head, body, seq, timeout)
        if resp is None:
            return False
        retcode = resp.get("head", {}).get("retcode", -1)
        return retcode == 0

    def _rpc_raw(
        self, head: dict, body: dict, seq: int, timeout: float = 15.0,
    ) -> dict | None:
        if self._ws is None:
            return None

        inner = json.dumps({"head": head, "body": body}, ensure_ascii=False)
        outer = json.dumps({
            "type": 3,
            "buffer": base64.b64encode(inner.encode("utf-8")).decode("ascii"),
        }, ensure_ascii=False)

        event = threading.Event()
        self._response_events[seq] = event

        try:
            self._ws.send(outer)
        except Exception as exc:
            logger.error("WebSocket send failed: %s", exc)
            self._response_events.pop(seq, None)
            return None

        if not event.wait(timeout=timeout):
            logger.error("WebSocket RPC timeout (seq=%d, cmd=%s)", seq, head.get("servcmd"))
            self._response_events.pop(seq, None)
            return None

        resp = self._responses.pop(seq, None)
        self._response_events.pop(seq, None)
        return resp

    def _reader(self) -> None:
        """Background thread: read WebSocket frames."""
        while self._running and self._ws:
            try:
                msg = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                if self._running:
                    logger.debug("WebSocket reader exiting")
                break

            try:
                outer = json.loads(msg)
                buf = base64.b64decode(outer.get("buffer", ""))
                inner = json.loads(buf.decode("utf-8"))
            except Exception:
                logger.debug("Failed to parse WS frame: %s", str(msg)[:100])
                continue

            h = inner.get("head", {})
            seq = h.get("seq", 0)
            cmd = h.get("servcmd", "")

            if seq in self._response_events:
                self._responses[seq] = inner
                self._response_events[seq].set()
            else:
                logger.debug("WS push: cmd=%s seq=%s", cmd, seq)

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
