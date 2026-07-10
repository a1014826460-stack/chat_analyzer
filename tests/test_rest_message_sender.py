from __future__ import annotations

import json
import sqlite3
from urllib.error import HTTPError

from app.services.rest_message_sender import RestGroupMessageSender


def test_rest_group_message_sender_posts_group_message_with_account_token(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"ActionStatus": "OK", "ErrorCode": 0}).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("app.services.rest_message_sender._random", lambda: 123456)

    sender = RestGroupMessageSender(
        sdk_app_id=1400000000,
        identifier="x1DuArYgV",
        user_sig="token-from-shared-prefs",
        from_account="x1DuArYgV",
    )

    assert sender.startup() is True
    assert sender.inject_bet("207191791", "小单", 100) is True

    assert "group_open_http_svc/send_group_msg" in captured["url"]
    assert "sdkappid=1400000000" in captured["url"]
    assert "identifier=x1DuArYgV" in captured["url"]
    assert "usersig=token-from-shared-prefs" in captured["url"]
    assert "random=123456" in captured["url"]
    assert captured["timeout"] == 10
    assert captured["body"] == {
        "GroupId": "207191791",
        "Random": 123456,
        "From_Account": "x1DuArYgV",
        "MsgBody": [
            {"MsgType": "TIMTextElem", "MsgContent": {"Text": "小单100"}}
        ],
    }


def test_rest_group_message_sender_uses_sgp_im_qcloud_domain_by_default(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"ActionStatus": "OK", "ErrorCode": 0}).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("app.services.rest_message_sender._random", lambda: 123456)

    sender = RestGroupMessageSender(20011216, "x1DuArYgV", "token")

    assert sender.inject_text("207191791", "hello") is True
    assert captured["url"].startswith("https://adminapisgp.im.qcloud.com/")


def test_rest_group_message_sender_returns_false_on_rest_error(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"ActionStatus": "FAIL", "ErrorCode": 10007, "ErrorInfo": "permission denied"}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: FakeResponse())

    sender = RestGroupMessageSender(1400000000, "x1DuArYgV", "token")

    assert sender.inject_text("207191791", "hello") is False

def test_auto_bet_start_source_does_not_import_message_injector_for_tim_login():
    from pathlib import Path

    source = Path("app/ui/main_window_data.py").read_text(encoding="utf-8")
    start = source.index("    def _on_auto_bet_start")
    stop = source.index("    def _on_auto_bet_stop")
    body = source[start:stop]

    assert "from app.services.message_injector import MessageInjector" not in body
    assert "MessageInjector(" not in body
    assert "TIMLogin" not in body
    assert "RemoteIMSender" not in body
    assert "RestGroupMessageSender" not in body
    assert "UiaWuQuanMessageSender" in body
    assert "BackgroundWindowMessageSender" in body


def _create_message_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE message (sid TEXT, content TEXT, client_time INTEGER)")
    con.commit()
    con.close()


def _patch_rest_ok(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"ActionStatus": "OK", "ErrorCode": 0}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: FakeResponse())


def test_rest_group_message_sender_requires_matching_local_msg_db_row_after_rest_ok(tmp_path, monkeypatch):
    db_path = tmp_path / "msg_0.db"
    _create_message_db(db_path)
    _patch_rest_ok(monkeypatch)

    sender = RestGroupMessageSender(
        1400000000,
        "x1DuArYgV",
        "token",
        msg_db_path=db_path,
        verify_timeout_sec=0,
    )

    assert sender.inject_bet("207191791", "小单", 100) is False


def test_rest_group_message_sender_marks_success_only_when_group_content_appears_in_msg_db(tmp_path, monkeypatch):
    db_path = tmp_path / "msg_0.db"
    _create_message_db(db_path)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            con = sqlite3.connect(db_path)
            con.execute(
                "INSERT INTO message (sid, content, client_time) VALUES (?, ?, ?)",
                ("207191791", "小单100", 123456789),
            )
            con.commit()
            con.close()
            return json.dumps({"ActionStatus": "OK", "ErrorCode": 0}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: FakeResponse())

    sender = RestGroupMessageSender(
        1400000000,
        "x1DuArYgV",
        "token",
        msg_db_path=db_path,
        verify_timeout_sec=0,
    )

    assert sender.inject_bet("207191791", "小单", 100) is True


