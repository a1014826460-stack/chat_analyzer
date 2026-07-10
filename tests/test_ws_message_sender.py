from __future__ import annotations

import base64
import json

from app.services.ws_message_sender import WsMessageSender, encode_frame, decode_frame


def test_encode_frame_matches_websdk_direct_json_bytes():
    frame = encode_frame({"servcmd": "im_open_status.wslogin", "seq": 7}, {"State": "Online"})

    assert isinstance(frame, bytes)
    assert json.loads(frame.decode("utf-8")) == {
        "head": {"servcmd": "im_open_status.wslogin", "seq": 7},
        "body": {"State": "Online"},
    }
    assert b'"type"' not in frame
    assert b'"buffer"' not in frame
    assert decode_frame(frame)["head"]["seq"] == 7


def test_decode_frame_keeps_backward_compatibility_for_old_wrapped_exports():
    inner = json.dumps({"head": {"seq": 8}, "body": {"ok": True}}).encode("utf-8")
    wrapped = json.dumps({"type": 3, "buffer": base64.b64encode(inner).decode("ascii")})

    assert decode_frame(wrapped) == {"head": {"seq": 8}, "body": {"ok": True}}


def test_login_stores_a2_tiny_id_and_status_instid(monkeypatch):
    sent: list[bytes | str] = []

    class FakeWebSocket:
        def connect(self, url, timeout=15, **kwargs):
            self.url = url

        def settimeout(self, timeout):
            self.timeout = timeout

        def send(self, payload, opcode=None):
            sent.append(payload)

        def recv(self):
            req = decode_frame(sent[-1])
            return encode_frame(
                {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                {"ActionStatus": "OK", "A2Key": "a2-key", "TinyId": "tiny-1", "InstId": 12345},
            )

        def close(self):
            pass

    monkeypatch.setattr("app.services.ws_message_sender.websocket.WebSocket", FakeWebSocket)

    sender = WsMessageSender(20011216, "x1DuArYgV", "sig")

    assert sender.startup() is True
    assert sender._a2 == "a2-key"
    assert sender._tiny_id == "tiny-1"
    assert sender._status_instid == 12345
    assert json.loads(sent[0].decode("utf-8"))["head"]["servcmd"] == "im_open_status.wslogin"


def test_group_message_uses_websdk_body_and_checks_body_error(monkeypatch):
    sent: list[bytes | str] = []

    class FakeWebSocket:
        def connect(self, url, timeout=15, **kwargs):
            pass

        def settimeout(self, timeout):
            pass

        def send(self, payload, opcode=None):
            sent.append(payload)

        def recv(self):
            req = decode_frame(sent[-1])
            cmd = req["head"]["servcmd"]
            if cmd == "im_open_status.wslogin":
                return encode_frame(
                    {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                    {"ActionStatus": "OK", "A2Key": "a2-key", "TinyId": "tiny-1", "InstId": 12345},
                )
            assert cmd == "group_open_http_svc.send_group_msg"
            body = req["body"]
            assert body["From_Account"] == "x1DuArYgV"
            assert body["GroupId"] == "207191791"
            assert body["MsgPriority"] == "High"
            assert body["MsgBody"][0]["MsgType"] == "TIMTextElem"
            assert body["MsgBody"][0]["MsgContent"]["Text"] != "hello"
            assert req["head"]["a2"] == "a2-key"
            assert req["head"]["tinyid"] == "tiny-1"
            assert req["head"]["status_instid"] == 12345
            assert req["head"]["tjgID"].startswith("tiny-1-")
            return encode_frame(
                {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                {"ActionStatus": "OK", "ErrorCode": 0},
            )

        def close(self):
            pass

    monkeypatch.setattr("app.services.ws_message_sender.websocket.WebSocket", FakeWebSocket)

    sender = WsMessageSender(20011216, "x1DuArYgV", "sig")
    assert sender.startup() is True
    assert sender.inject_text("207191791", "hello") is True


def test_rpc_returns_false_when_body_rejects_even_if_head_ok(monkeypatch):
    sent: list[bytes | str] = []

    class FakeWebSocket:
        def connect(self, url, timeout=15, **kwargs):
            pass

        def settimeout(self, timeout):
            pass

        def send(self, payload, opcode=None):
            sent.append(payload)

        def recv(self):
            req = decode_frame(sent[-1])
            if req["head"]["servcmd"] == "im_open_status.wslogin":
                return encode_frame(
                    {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                    {"ActionStatus": "OK", "A2Key": "a2-key", "TinyId": "tiny-1", "InstId": 12345},
                )
            return encode_frame(
                {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                {"ActionStatus": "FAIL", "ErrorCode": 20003, "ErrorInfo": "Invalid sender or receiver identifier!"},
            )

        def close(self):
            pass

    monkeypatch.setattr("app.services.ws_message_sender.websocket.WebSocket", FakeWebSocket)

    sender = WsMessageSender(20011216, "x1DuArYgV", "sig")
    assert sender.startup() is True
    assert sender.inject_text("bad-user", "hello", is_group=False) is False



def test_inject_text_reconnects_and_retries_once_after_stale_socket(monkeypatch):
    from app.services import ws_message_sender as module

    sent: list[bytes | str] = []
    sockets = []

    class FakeWebSocket:
        def __init__(self):
            self.index = len(sockets)
            sockets.append(self)
            self.closed = False

        def connect(self, url, timeout=15, **kwargs):
            self.url = url

        def settimeout(self, timeout):
            self.timeout = timeout

        def send(self, payload, opcode=None):
            if self.index == 0 and len(sent) >= 2:
                raise OSError("stale socket")
            sent.append(payload)

        def recv(self):
            req = decode_frame(sent[-1])
            cmd = req["head"]["servcmd"]
            if cmd == "im_open_status.wslogin":
                return encode_frame(
                    {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                    {"ActionStatus": "OK", "A2Key": f"a2-{self.index}", "TinyId": f"tiny-{self.index}", "InstId": 100 + self.index},
                )
            return encode_frame(
                {"seq": req["head"]["seq"], "retcode": 0, "retstr": "ok"},
                {"ActionStatus": "OK", "ErrorCode": 0},
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(module.websocket, "WebSocket", FakeWebSocket)

    sender = WsMessageSender(20011216, "x1DuArYgV", "sig")
    assert sender.startup() is True

    assert sender.inject_text("207191791", "hello") is True
    assert len(sockets) == 2
    assert sockets[0].closed is True
    assert sender._a2 == "a2-1"



def test_ws_inject_bet_formats_without_space(monkeypatch):
    captured = {}

    def fake_inject_text(self, target_id, text, *, is_group=True):
        captured["target_id"] = target_id
        captured["text"] = text
        captured["is_group"] = is_group
        return True

    monkeypatch.setattr(WsMessageSender, "inject_text", fake_inject_text)

    sender = WsMessageSender(20011216, "x1DuArYgV", "sig")
    assert sender.inject_bet("207191791", "?", 100.0) is True
    assert captured == {"target_id": "207191791", "text": "?100", "is_group": True}
