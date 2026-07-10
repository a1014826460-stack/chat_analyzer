"""Send Tencent Cloud Chat messages through the Web WSS protocol.

This sender mirrors the browser/WebSDK path instead of using ImSDK.  It opens a
separate ``wss://wsssgp.im.qcloud.com/binfo`` connection with a unique
``instanceid``, performs ``im_open_status.wslogin`` with the account UserSig,
then sends group or C2C messages with the same JSON-binary frames observed from
TencentCloudChat WebSDK 3.2.1.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import ssl
import threading
import time
from typing import Any

import websocket

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except ImportError:  # pragma: no cover
    AES = None
    pad = None
    unpad = None

logger = logging.getLogger(__name__)

WS_URL = "wss://wsssgp.im.qcloud.com/binfo"
WS_BACKUP_URL = "wss://wsssgp.my-imcloud.com/binfo"
WEBSDK_APP_ID = 537048168
WEBSDK_VERSION = "1.7.3"
SDK_ABILITY = 192371
FRONTEND_AES_KEY = "666888"


def _make_instanceid() -> str:
    raw = f"{time.time()}-{random.random()}-python-web-wss"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _aes_key() -> bytes:
    key = FRONTEND_AES_KEY.encode("utf-8")
    return (key + b"\x00" * 16)[:16]


def encrypt_text(plain: str) -> str:
    """AES-ECB + Base64 used by WuQuan frontend message text."""
    if AES is None or pad is None:
        raise RuntimeError("pycryptodome is required for Web WSS message encryption")
    cipher = AES.new(_aes_key(), AES.MODE_ECB)
    return base64.b64encode(cipher.encrypt(pad(plain.encode("utf-8"), AES.block_size))).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    if AES is None or unpad is None:
        raise RuntimeError("pycryptodome is required for Web WSS message decryption")
    cipher = AES.new(_aes_key(), AES.MODE_ECB)
    return unpad(cipher.decrypt(base64.b64decode(ciphertext)), AES.block_size).decode("utf-8")


def encode_frame(head: dict[str, Any], body: dict[str, Any]) -> bytes:
    """Encode like TencentCloudChat WebSDK: direct JSON binary frame."""
    return json.dumps({"head": head, "body": body}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_frame(raw: str | bytes) -> dict[str, Any]:
    """Decode WebSDK direct JSON frames and older base64 wrapper exports."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    outer = json.loads(raw)
    if isinstance(outer, dict) and "head" in outer and "body" in outer:
        return outer
    if isinstance(outer, dict) and "buffer" in outer:
        return json.loads(base64.b64decode(outer.get("buffer", "")).decode("utf-8"))
    raise ValueError("Unsupported Web WSS frame")


class WsMessageSender:
    """MessageInjector-compatible sender backed by Web WSS, not ImSDK."""

    def __init__(
        self,
        sdk_app_id: int | str,
        identifier: str,
        user_sig: str,
        *,
        endpoint: str = WS_URL,
        connect_timeout: float = 15.0,
        rpc_timeout: float = 15.0,
        nick: str = "",
        avatar: str = "",
    ) -> None:
        self._sdk_app_id = int(sdk_app_id)
        self._identifier = str(identifier).strip()
        self._user_sig = str(user_sig).strip()
        self._endpoint = endpoint.rstrip("/")
        self._connect_timeout = float(connect_timeout)
        self._rpc_timeout = float(rpc_timeout)
        self._nick = str(nick or "")
        self._avatar = str(avatar or "")
        self._instanceid = _make_instanceid()
        self._seq = random.randint(1, 99_999_999)
        self._a2 = ""
        self._tiny_id = ""
        self._status_instid = 0
        self._last_rpc_transport_error = False
        self._ws: websocket.WebSocket | None = None
        self._running = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API compatible with other sender implementations
    # ------------------------------------------------------------------

    def startup(self) -> bool:
        if not (self._sdk_app_id and self._identifier and self._user_sig):
            logger.error("Web WSS sender missing sdk_app_id/identifier/user_sig")
            return False
        with self._lock:
            if not self._connect():
                return False
            self._running = True
            if not self._login():
                self.shutdown()
                return False
            hb = self._rpc("heartbeat.alive", {})
            if not hb:
                logger.warning("Web WSS heartbeat failed after login")
            logger.info(
                "Web WSS logged in: accid=%s tinyid=%s instid=%s instanceid=%s",
                self._identifier,
                self._tiny_id,
                self._status_instid,
                self._instanceid[:16],
            )
            return True

    def shutdown(self) -> None:
        with self._lock:
            self._running = False
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None

    @property
    def is_running(self) -> bool:
        return self._running and self._ws is not None

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        return self.inject_text(group_id, f"{play_type}{self._fmt_amount(amount)}", is_group=True)

    def inject_text(self, target_id: str, text: str, *, is_group: bool = True) -> bool:
        if not self.is_running:
            logger.error("Web WSS sender is not running")
            return False

        target = str(target_id)
        message = str(text)
        send_once = self._send_group_msg if is_group else self._send_c2c_msg
        if send_once(target, message):
            return True
        if not self._last_rpc_transport_error:
            return False

        logger.warning("Web WSS transport failed; reconnecting and retrying once")
        if not self._restart_session():
            return False
        return send_once(target, message)

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    def _send_group_msg(self, group_id: str, text: str) -> bool:
        random_id = random.randint(1, 0x7FFFFFFF)
        body: dict[str, Any] = {
            "From_Account": self._identifier,
            "GroupId": group_id,
            "Random": random_id,
            "ClientSeq": random.randint(1, 0x7FFFFFFF),
            "MsgPriority": "High",
            "MsgBody": [
                {"MsgType": "TIMTextElem", "MsgContent": {"Text": encrypt_text(text)}}
            ],
            "CloudCustomData": "",
            "OnlineOnlyFlag": 0,
            "OfflinePushInfo": {
                "PushFlag": 0,
                "Title": "",
                "Desc": "",
                "Ext": "",
                "ApnsInfo": {"BadgeMode": 0},
                "AndroidInfo": {"OPPOChannelID": ""},
            },
            "GroupAtInfo": [],
            "SendMsgControl": [],
            "MsgClientTime": int(time.time()),
            "NeedReadReceipt": 0,
            "SupportMessageExtension": 0,
            "IsRelayMsg": 0,
        }
        return self._rpc(
            "group_open_http_svc.send_group_msg",
            body,
            tjg_id=f"{self._tiny_id}-{random_id}",
        )

    def _send_c2c_msg(self, user_id: str, text: str) -> bool:
        msg_random = random.randint(1, 0x7FFFFFFF)
        body: dict[str, Any] = {
            "From_Account": self._identifier,
            "To_Account": user_id,
            "MsgSeq": random.randint(1_000_000_000, 2_100_000_000),
            "MsgRandom": msg_random,
            "MsgBody": [
                {"MsgType": "TIMTextElem", "MsgContent": {"Text": encrypt_text(text)}}
            ],
            "CloudCustomData": json.dumps(
                {"messageFeature": {"needTyping": 1, "version": 1}},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "From_AccountNick": self._nick,
            "From_AccountHeadurl": self._avatar,
            "OfflinePushInfo": {
                "PushFlag": 0,
                "Title": "",
                "Desc": "",
                "Ext": "",
                "ApnsInfo": {"BadgeMode": 0},
                "AndroidInfo": {"OPPOChannelID": ""},
            },
            "SendMsgControl": [],
            "MsgClientTime": int(time.time()),
            "IsNeedReadReceipt": 0,
            "SupportMessageExtension": 0,
            "IsRelayMsg": 0,
        }
        return self._rpc("openim.sendmsg", body, tjg_id=f"{self._tiny_id}-{msg_random}")

    # ------------------------------------------------------------------
    # Web WSS protocol
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        return (
            f"{self._endpoint}?sdkappid={self._sdk_app_id}"
            f"&instanceid={self._instanceid}"
            f"&random={random.random()}&platform=7&host=windows&version=-1&sdkversion=3.2.1"
        )

    def _restart_session(self) -> bool:
        with self._lock:
            self._running = False
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
            self._ws = None
            self._a2 = ""
            self._tiny_id = ""
            self._status_instid = 0
            self._last_rpc_transport_error = False
            self._instanceid = _make_instanceid()
            if not self._connect():
                return False
            self._running = True
            if not self._login():
                self.shutdown()
                return False
            hb = self._rpc("heartbeat.alive", {})
            if not hb:
                logger.warning("Web WSS heartbeat failed after reconnect")
            logger.info(
                "Web WSS reconnected: accid=%s tinyid=%s instid=%s instanceid=%s",
                self._identifier,
                self._tiny_id,
                self._status_instid,
                self._instanceid[:16],
            )
            return True

    def _connect(self) -> bool:
        try:
            self._ws = websocket.WebSocket(sslopt={"cert_reqs": ssl.CERT_REQUIRED})
        except TypeError:
            # Lightweight test doubles may not accept websocket-client kwargs.
            self._ws = websocket.WebSocket()
        headers = [
            "Origin: https://www.571919.xyz",
            "Cache-Control: no-cache",
            "Pragma: no-cache",
            "Accept-Language: zh-CN,zh;q=0.9",
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        ]
        try:
            self._ws.connect(self._build_url(), timeout=self._connect_timeout, header=headers)
            self._ws.settimeout(self._rpc_timeout)
            return True
        except Exception as exc:
            logger.error("Web WSS connect failed: %s", exc)
            self._ws = None
            return False

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _base_head(self, servcmd: str, seq: int, *, tjg_id: str = "") -> dict[str, Any]:
        head: dict[str, Any] = {
            "ver": "v4",
            "platform": 7,
            "websdkappid": WEBSDK_APP_ID,
            "websdkversion": WEBSDK_VERSION,
            "sdkappid": self._sdk_app_id,
            "contenttype": "json",
            "reqtime": int(time.time()),
            "sdkability": SDK_ABILITY,
            "tjgID": tjg_id,
            "servcmd": servcmd,
            "seq": seq,
        }
        if self._a2:
            head.update({"a2": self._a2, "tinyid": self._tiny_id, "status_instid": self._status_instid})
        else:
            head.update({"status_instid": self._status_instid, "identifier": self._identifier, "usersig": self._user_sig})
        return head

    def _login(self) -> bool:
        seq = self._next_seq()
        head = self._base_head("im_open_status.wslogin", seq)
        body = {"State": "Online", "is_web_uniapp": 0, "InstType": 0}
        resp = self._rpc_raw(head, body, seq, timeout=max(self._rpc_timeout, 20.0))
        if not self._response_ok(resp):
            logger.error("Web WSS login rejected: %s", resp)
            return False
        resp_body = resp.get("body", {}) if isinstance(resp, dict) else {}
        self._a2 = str(resp_body.get("A2Key") or "")
        self._tiny_id = str(resp_body.get("TinyId") or "")
        self._status_instid = int(resp_body.get("InstId") or 0)
        return bool(self._a2 and self._tiny_id and self._status_instid)

    def _rpc(self, servcmd: str, body: dict[str, Any], *, tjg_id: str = "", timeout: float | None = None) -> bool:
        with self._lock:
            seq = self._next_seq()
            head = self._base_head(servcmd, seq, tjg_id=tjg_id)
            self._last_rpc_transport_error = False
            resp = self._rpc_raw(head, body, seq, timeout=timeout or self._rpc_timeout)
            self._last_rpc_transport_error = resp is None
            ok = self._response_ok(resp)
            if not ok:
                logger.error("Web WSS RPC rejected cmd=%s resp=%s", servcmd, resp)
            return ok

    def _rpc_raw(
        self,
        head: dict[str, Any],
        body: dict[str, Any],
        seq: int,
        timeout: float = 15.0,
    ) -> dict[str, Any] | None:
        if self._ws is None:
            return None
        try:
            self._ws.send(encode_frame(head, body), opcode=websocket.ABNF.OPCODE_BINARY)
        except TypeError:
            # Test doubles or older websocket-client versions may not accept opcode.
            self._ws.send(encode_frame(head, body))
        except Exception as exc:
            logger.error("Web WSS send failed: %s", exc)
            return None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                self._ws.settimeout(remaining)
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                break
            except Exception as exc:
                logger.error("Web WSS recv failed: %s", exc)
                return None
            try:
                msg = decode_frame(raw)
            except Exception:
                logger.debug("Failed to parse Web WSS frame: %s", str(raw)[:120])
                continue
            msg_head = msg.get("head", {})
            if msg_head.get("seq") == seq:
                return msg
            self._handle_push(msg)
        logger.error("Web WSS RPC timeout seq=%s cmd=%s", seq, head.get("servcmd"))
        return None

    @staticmethod
    def _response_ok(resp: dict[str, Any] | None) -> bool:
        if not isinstance(resp, dict):
            return False
        head = resp.get("head", {})
        body = resp.get("body", {})
        if int(head.get("retcode", -1)) != 0:
            return False
        if not isinstance(body, dict):
            return True
        if "ErrorCode" in body and int(body.get("ErrorCode", -1)) != 0:
            return False
        if "ActionStatus" in body and body.get("ActionStatus") != "OK":
            return False
        return True

    def _handle_push(self, msg: dict[str, Any]) -> None:
        head = msg.get("head", {}) if isinstance(msg, dict) else {}
        body = msg.get("body", {}) if isinstance(msg, dict) else {}
        if head.get("servcmd") != "im_open_push.msg_push":
            logger.debug("Web WSS push: cmd=%s seq=%s", head.get("servcmd"), head.get("seq"))
            return
        for event in body.get("EventArray", []) if isinstance(body, dict) else []:
            for group_msg in event.get("GroupMsgArray", []):
                group_id = group_msg.get("ToGroupId")
                sender = group_msg.get("From_Account")
                seq = group_msg.get("MsgSeq")
                logger.debug("Web WSS group push: group=%s from=%s seq=%s", group_id, sender, seq)

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
