from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import random
import ssl
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except ImportError:  # pragma: no cover
    AES = None
    pad = None
    unpad = None

SDK_APP_ID = 20011216
IDENTIFIER = "A7MYtCxL8"
USER_SIG = ""
DEFAULT_GROUP_ID = "207191791"
DEFAULT_TEXT = "小单 1"
FRONTEND_AES_KEY = "666888"
WS_ENDPOINTS = (
    "wss://wsssgp.im.qcloud.com/binfo",
    "wss://wsssgp.my-imcloud.com/binfo",
)


def make_instance_id() -> str:
    raw = f"{time.time()}-{random.random()}-tests-wss"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _aes_key() -> bytes:
    key = FRONTEND_AES_KEY.encode("utf-8")
    return (key + b"\x00" * 16)[:16]


def encrypt_text(text: str) -> str:
    if AES is None or pad is None:
        raise RuntimeError("pycryptodome is required for Tencent IM text encryption")
    cipher = AES.new(_aes_key(), AES.MODE_ECB)
    return base64.b64encode(cipher.encrypt(pad(text.encode("utf-8"), AES.block_size))).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    if AES is None or unpad is None:
        raise RuntimeError("pycryptodome is required for Tencent IM text decryption")
    cipher = AES.new(_aes_key(), AES.MODE_ECB)
    raw = cipher.decrypt(base64.b64decode(ciphertext))
    return unpad(raw, AES.block_size).decode("utf-8")


def encode_frame(head: dict[str, Any], body: dict[str, Any]) -> bytes:
    """Encode exactly like TencentCloudChat WebSDK 3.2.1.

    Playwright frame capture shows the Web SDK sends the inner JSON object
    directly as a binary frame, not the old {type, buffer: base64(json)}
    wrapper used by some captured/proxied views.
    """
    inner = json.dumps({"head": head, "body": body}, ensure_ascii=False, separators=(",", ":"))
    return inner.encode("utf-8")


def decode_frame(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    outer = json.loads(raw)
    if isinstance(outer, dict) and "head" in outer and "body" in outer:
        return outer
    # Backward-compatible decoder for Reqable/exported frames that wrap JSON in base64.
    return json.loads(base64.b64decode(outer.get("buffer", "")).decode("utf-8"))


@dataclass
class ImWssClient:
    sdk_app_id: int
    identifier: str
    user_sig: str
    group_id: str = DEFAULT_GROUP_ID
    instance_id: str = field(default_factory=make_instance_id)
    seq_start: int = field(default_factory=lambda: random.randint(1, 99_999_999))
    endpoint: str = WS_ENDPOINTS[0]
    a2: str = ""
    tiny_id: str = ""
    status_instid: int = 0

    @property
    def has_session(self) -> bool:
        return bool(self.a2 and self.tiny_id and self.status_instid)
    websocket: Any = None

    def next_seq(self) -> int:
        self.seq_start += 1
        return self.seq_start

    def build_url(self) -> str:
        return (
            f"{self.endpoint}?sdkappid={self.sdk_app_id}"
            f"&instanceid={self.instance_id}"
            f"&random={random.random()}&platform=7&host=windows&version=-1&sdkversion=3.2.1"
        )

    def build_login_head(self) -> dict[str, Any]:
        seq = self.next_seq()
        return {
            "ver": "v4",
            "platform": 7,
            "websdkappid": 537048168,
            "websdkversion": "1.7.3",
            "status_instid": self.status_instid,
            "sdkappid": self.sdk_app_id,
            "contenttype": "json",
            "reqtime": int(time.time()),
            "identifier": self.identifier,
            "usersig": self.user_sig,
            "sdkability": 192371,
            "tjgID": "",
            "servcmd": "im_open_status.wslogin",
            "seq": seq,
        }

    def build_authed_head(self, servcmd: str, seq: int | None = None, *, tjg_id: str = "") -> dict[str, Any]:
        if seq is None:
            seq = self.next_seq()
        return {
            "ver": "v4",
            "platform": 7,
            "websdkappid": 537048168,
            "websdkversion": "1.7.3",
            "a2": self.a2,
            "tinyid": self.tiny_id,
            "status_instid": self.status_instid,
            "sdkappid": self.sdk_app_id,
            "contenttype": "json",
            "reqtime": int(time.time()),
            "sdkability": 192371,
            "tjgID": tjg_id,
            "servcmd": servcmd,
            "seq": seq,
        }

    async def connect(self) -> None:
        ssl_context = ssl.create_default_context()
        headers = {
            "Origin": "https://www.571919.xyz",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        }
        self.websocket = await websockets.connect(
            self.build_url(),
            additional_headers=headers,
            ssl=ssl_context,
            open_timeout=15,
            ping_interval=None,
        )

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
            self.websocket = None

    async def rpc(self, head: dict[str, Any], body: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected")
        target_seq = head["seq"]
        await self.websocket.send(encode_frame(head, body))
        while True:
            raw = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
            msg = decode_frame(raw)
            msg_head = msg.get("head", {})
            if msg_head.get("seq") == target_seq:
                return msg
            await self.handle_push(msg)

    async def _finish_login_response(self, resp: dict[str, Any], label: str = "IM login") -> dict[str, Any]:
        resp_head = resp.get("head", {})
        resp_body = resp.get("body", {})
        if resp_head.get("retcode") != 0 or resp_body.get("ActionStatus") != "OK":
            raise RuntimeError(f"{label} failed: head={resp_head} body={resp_body}")
        if resp_body.get("A2Key"):
            self.a2 = resp_body["A2Key"]
        if resp_body.get("TinyId"):
            self.tiny_id = str(resp_body["TinyId"])
        if resp_body.get("InstId"):
            self.status_instid = int(resp_body.get("InstId") or 0)
        return resp

    async def login(self) -> dict[str, Any]:
        head = self.build_login_head()
        resp = await self.rpc(head, {"State": "Online", "is_web_uniapp": 0, "InstType": 0}, timeout=20)
        return await self._finish_login_response(resp)

    async def resume_login(self) -> dict[str, Any]:
        if not self.has_session:
            raise RuntimeError("resume_login requires a2, tiny_id and status_instid")
        head = self.build_authed_head("im_open_status.wslogin")
        resp = await self.rpc(head, {"State": "Online", "is_web_uniapp": 0, "InstType": 0}, timeout=20)
        return await self._finish_login_response(resp, label="IM resume login")

    async def heartbeat(self) -> dict[str, Any]:
        return await self.rpc(self.build_authed_head("heartbeat.alive"), {}, timeout=10)

    async def send_group_text(self, text: str) -> dict[str, Any]:
        random_id = random.randint(1, 0x7FFFFFFF)
        body = {
            "From_Account": self.identifier,
            "GroupId": self.group_id,
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
        return await self.rpc(
            self.build_authed_head(
                "group_open_http_svc.send_group_msg",
                tjg_id=f"{self.tiny_id}-{random_id}",
            ),
            body,
            timeout=15,
        )

    async def send_c2c_text(
        self,
        to_account: str,
        text: str,
        *,
        nick: str = "??761042",
        avatar: str = "https://img.e18888.com/path/avatar/20260703/607f2b2b57f04016843913d816d6c7c5.png",
    ) -> dict[str, Any]:
        msg_random = random.randint(1, 0x7FFFFFFF)
        msg_seq = random.randint(1_000_000_000, 2_100_000_000)
        body = {
            "From_Account": self.identifier,
            "To_Account": to_account,
            "MsgSeq": msg_seq,
            "MsgRandom": msg_random,
            "MsgBody": [
                {"MsgType": "TIMTextElem", "MsgContent": {"Text": encrypt_text(text)}}
            ],
            "CloudCustomData": json.dumps(
                {"messageFeature": {"needTyping": 1, "version": 1}},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "From_AccountNick": nick,
            "From_AccountHeadurl": avatar,
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
        return await self.rpc(
            self.build_authed_head("openim.sendmsg", tjg_id=f"{self.tiny_id}-{msg_random}"),
            body,
            timeout=15,
        )

    async def handle_push(self, msg: dict[str, Any]) -> None:
        head = msg.get("head", {})
        if head.get("servcmd") != "im_open_push.msg_push":
            print(f"[push] {head.get('servcmd')} seq={head.get('seq')}")
            return
        body = msg.get("body", {})
        for event in body.get("EventArray", []):
            for group_msg in event.get("GroupMsgArray", []):
                self.print_group_message(group_msg)

    def print_group_message(self, group_msg: dict[str, Any]) -> None:
        group_id = group_msg.get("ToGroupId")
        sender = group_msg.get("From_Account")
        seq = group_msg.get("MsgSeq")
        for elem in group_msg.get("MsgBody", []):
            if elem.get("MsgType") != "TIMTextElem":
                print(f"[recv] group={group_id} from={sender} seq={seq} type={elem.get('MsgType')}")
                continue
            cipher = elem.get("MsgContent", {}).get("Text", "")
            try:
                text = decrypt_text(cipher)
            except Exception:
                text = f"<decrypt failed: {cipher[:80]}>"
            print(f"[recv] group={group_id} from={sender} seq={seq} text={text}")

    async def recv_for(self, seconds: float) -> None:
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.websocket.recv(), timeout=max(0.1, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            await self.handle_push(decode_frame(raw))


async def run_demo(args: argparse.Namespace) -> int:
    client = ImWssClient(
        sdk_app_id=int(args.sdk_app_id),
        identifier=args.accid,
        user_sig=args.user_sig,
        group_id=args.group_id,
        endpoint=args.endpoint,
        a2=args.a2 or "",
        tiny_id=args.tiny_id or "",
        status_instid=int(args.status_instid or 0),
    )
    print(f"[1/4] Connecting WSS: {client.endpoint}")
    await client.connect()
    try:
        print(f"      instanceid={client.instance_id}")
        if args.resume:
            if not client.has_session:
                raise RuntimeError("--resume requires --a2, --tiny-id and --status-instid")
            print("[2/4] IM resume wslogin with existing A2Key ...")
            login_resp = await client.resume_login()
            print(
                "      resume login OK: "
                f"TinyId={client.tiny_id} InstId={client.status_instid} A2KeyLen={len(client.a2)} "
                f"HelloInterval={login_resp.get('body', {}).get('HelloInterval')}"
            )
        else:
            print("[2/4] IM wslogin ...")
            login_resp = await client.login()
            print(
                "      login OK: "
                f"TinyId={client.tiny_id} InstId={client.status_instid} "
                f"HelloInterval={login_resp.get('body', {}).get('HelloInterval')}"
            )
        print("[3/4] Heartbeat ...")
        hb = await client.heartbeat()
        print(f"      heartbeat ret={hb.get('head', {}).get('retcode')} {hb.get('head', {}).get('retstr')}")
        if args.send_c2c:
            print(f"[4/4] Send C2C message to={args.to_account!r} text={args.text!r}")
            resp = await client.send_c2c_text(args.to_account, args.text)
            print("      send head:", json.dumps(resp.get("head", {}), ensure_ascii=False))
            print("      send body:", json.dumps(resp.get("body", {}), ensure_ascii=False)[:2000])
        elif args.send:
            print(f"[4/4] Send group message group={args.group_id!r} text={args.text!r}")
            resp = await client.send_group_text(args.text)
            print("      send head:", json.dumps(resp.get("head", {}), ensure_ascii=False))
            print("      send body:", json.dumps(resp.get("body", {}), ensure_ascii=False)[:2000])
        else:
            print(f"[4/4] Receive messages for {args.listen_seconds}s ...")
            await client.recv_for(args.listen_seconds)
        return 0
    finally:
        await client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tencent IM WSS login/send/receive probe")
    parser.add_argument("--sdk-app-id", default=str(SDK_APP_ID))
    parser.add_argument("--accid", default=IDENTIFIER)
    parser.add_argument("--user-sig", default=USER_SIG, required=not bool(USER_SIG))
    parser.add_argument("--group-id", default=DEFAULT_GROUP_ID)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--endpoint", default=WS_ENDPOINTS[0], choices=WS_ENDPOINTS)
    parser.add_argument("--resume", action="store_true", help="skip usersig wslogin and use existing A2Key/TinyId/InstId")
    parser.add_argument("--a2", default="", help="existing A2Key for --resume")
    parser.add_argument("--tiny-id", default="", help="existing TinyId for --resume")
    parser.add_argument("--status-instid", default="0", help="existing InstId/status_instid for --resume")
    parser.add_argument("--send", action="store_true", help="send group text instead of only listening")
    parser.add_argument("--send-c2c", action="store_true", help="send C2C text through Web WSS openim.sendmsg")
    parser.add_argument("--to-account", default="LYGG88888", help="C2C target IM account/accid")
    parser.add_argument("--listen-seconds", type=float, default=20.0)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_demo(parse_args())))
