from __future__ import annotations

import sqlite3

from app.services.background_window_sender import BackgroundWindowMessageSender


def _create_message_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE message (sid TEXT, content TEXT, client_time INTEGER)")
    con.commit()
    con.close()


def test_background_window_sender_posts_text_chars_and_enter(monkeypatch, tmp_path):
    calls = []

    class FakeUser32:
        def IsWindow(self, hwnd):
            return True

        def PostMessageW(self, hwnd, msg, wparam, lparam):
            calls.append((hwnd, msg, wparam, lparam))
            return True

    sender = BackgroundWindowMessageSender(
        msg_db_path=None,
        hwnd=100,
        user32=FakeUser32(),
        verify_timeout_sec=0,
    )

    assert sender.inject_text("207191791", "小单 1") is True

    chars = [item[2] for item in calls[:-1]]
    assert chars == [ord(ch) for ch in "小单 1"]
    assert calls[-1][2] == 13


def test_background_window_sender_verifies_local_message_db_after_post(monkeypatch, tmp_path):
    db_path = tmp_path / "msg_0.db"
    _create_message_db(db_path)

    class FakeUser32:
        def IsWindow(self, hwnd):
            return True

        def PostMessageW(self, hwnd, msg, wparam, lparam):
            if wparam == 13:
                con = sqlite3.connect(db_path)
                con.execute(
                    "INSERT INTO message (sid, content, client_time) VALUES (?, ?, ?)",
                    ("207191791", "小单 1", 123),
                )
                con.commit()
                con.close()
            return True

    sender = BackgroundWindowMessageSender(
        msg_db_path=db_path,
        hwnd=100,
        user32=FakeUser32(),
        verify_timeout_sec=0,
    )

    assert sender.inject_text("207191791", "小单 1") is True


def test_background_window_sender_fails_when_db_verification_missing(tmp_path):
    db_path = tmp_path / "msg_0.db"
    _create_message_db(db_path)

    class FakeUser32:
        def IsWindow(self, hwnd):
            return True

        def PostMessageW(self, hwnd, msg, wparam, lparam):
            return True

    sender = BackgroundWindowMessageSender(
        msg_db_path=db_path,
        hwnd=100,
        user32=FakeUser32(),
        verify_timeout_sec=0,
    )

    assert sender.inject_text("207191791", "小单 1") is False
