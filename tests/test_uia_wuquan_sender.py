from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.uia_wuquan_sender import UiaWuQuanMessageSender


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class Info:
    def __init__(self, control_type, name="", rect=None):
        self.control_type = control_type
        self.name = name
        self.automation_id = ""
        self.class_name = ""
        self.rectangle = rect or Rect(0, 0, 0, 0)


class Control:
    def __init__(self, control_type, name="", rect=None, on_enter=None):
        self.element_info = Info(control_type, name, rect)
        self.actions = []
        self.on_enter = on_enter

    def set_focus(self):
        self.actions.append(("set_focus",))

    def click_input(self):
        self.actions.append(("click_input",))

    def type_keys(self, text, **kwargs):
        self.actions.append(("type_keys", text, kwargs))
        if text == "{ENTER}" and self.on_enter:
            self.on_enter()

    def set_edit_text(self, text):
        self.actions.append(("set_edit_text", text))


class Window:
    def __init__(self, controls):
        self.controls = controls
        self.actions = []

    def descendants(self):
        return list(self.controls)

    def set_focus(self):
        self.actions.append(("set_focus",))

    def type_keys(self, text, **kwargs):
        self.actions.append(("type_keys", text, kwargs))


def _create_msg_db(path: Path, rows=None):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE message (sid TEXT, content TEXT, client_time INTEGER)")
    for row in rows or []:
        con.execute("INSERT INTO message (sid, content, client_time) VALUES (?, ?, ?)", row)
    con.commit()
    con.close()


def _create_im_db(path: Path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE groupinfo (group_id TEXT, group_name TEXT)")
    con.execute("INSERT INTO groupinfo (group_id, group_name) VALUES (?, ?)", ("207191791", "A吸金A"))
    con.commit()
    con.close()


def test_uia_sender_sends_to_current_group_edit_and_verifies_db(tmp_path):
    msg_db = tmp_path / "msg_0.db"
    im_db = tmp_path / "im.db"
    _create_msg_db(msg_db, [])
    _create_im_db(im_db)
    def insert_sent():
        con = sqlite3.connect(msg_db)
        con.execute("INSERT INTO message (sid, content, client_time) VALUES (?, ?, ?)", ("207191791", "小单 1", 123))
        con.commit()
        con.close()
    header = Control("Text", "A吸金A", Rect(10, 10, 100, 40))
    message_edit = Control("Edit", "", Rect(10, 600, 900, 720), on_enter=insert_sent)
    window = Window([header, message_edit])

    sender = UiaWuQuanMessageSender(msg_db_path=msg_db, window_provider=lambda: window, verify_timeout_sec=0)

    assert sender.startup() is True
    assert sender.inject_text("207191791", "小单 1") is True
    assert message_edit.actions == [
        ("set_focus",),
        ("type_keys", "小单 1", {"with_spaces": True}),
        ("type_keys", "{ENTER}", {}),
    ]


def test_uia_sender_resolves_group_name_and_clicks_search_result_before_sending(tmp_path):
    msg_db = tmp_path / "msg_0.db"
    im_db = tmp_path / "im.db"
    _create_msg_db(msg_db, [])
    _create_im_db(im_db)
    def insert_sent():
        con = sqlite3.connect(msg_db)
        con.execute("INSERT INTO message (sid, content, client_time) VALUES (?, ?, ?)", ("207191791", "小单 1", 123))
        con.commit()
        con.close()

    current_header = Control("Text", "其他群", Rect(10, 10, 100, 40))
    search_edit = Control("Edit", "", Rect(10, 40, 300, 80))
    target_result = Control("Text", "A吸金A", Rect(10, 120, 300, 160))
    message_edit = Control("Edit", "", Rect(10, 600, 900, 720), on_enter=insert_sent)
    window = Window([current_header, search_edit, target_result, message_edit])

    sender = UiaWuQuanMessageSender(msg_db_path=msg_db, window_provider=lambda: window, verify_timeout_sec=0)

    assert sender.inject_text("207191791", "小单 1") is True
    assert search_edit.actions[:2] == [("set_focus",), ("set_edit_text", "A吸金A")]
    assert ("click_input",) in target_result.actions
    assert message_edit.actions[-3:] == [
        ("set_focus",),
        ("type_keys", "小单 1", {"with_spaces": True}),
        ("type_keys", "{ENTER}", {}),
    ]


def test_uia_sender_fails_when_target_group_cannot_be_opened(tmp_path):
    msg_db = tmp_path / "msg_0.db"
    _create_msg_db(msg_db)
    window = Window([Control("Text", "其他群", Rect(10, 10, 100, 40)), Control("Edit", "", Rect(10, 600, 900, 720))])
    sender = UiaWuQuanMessageSender(msg_db_path=msg_db, window_provider=lambda: window, verify_timeout_sec=0)

    assert sender.inject_text("missing", "小单 1") is False


def test_uia_wuquan_group_message_tool_exists():
    path = Path("tools/diagnostics/test_uia_wuquan_group_message.py")

    assert path.exists()
    source = path.read_text(encoding="utf-8")
    assert "UiaWuQuanMessageSender" in source
    assert "group_id" in source
    assert "msg_0.db" in source


def test_uia_sender_verifies_text_inside_binary_message_content(tmp_path):
    msg_db = tmp_path / "msg_0.db"
    _create_msg_db(msg_db, [("207191791", b"\x00\x08\xe5\xb0\x8f\xe5\x8d\x95 1\x10\x00", 123)])
    sender = UiaWuQuanMessageSender(msg_db_path=msg_db, window_provider=lambda: None, verify_timeout_sec=0)

    assert sender.verify_local_message("207191791", "小单 1") is True


def test_uia_sender_verifies_encrypted_element_description(tmp_path):
    msg_db = tmp_path / "msg_0.db"
    _create_msg_db(msg_db, [("207191791", b"opaque", 123)])
    con = sqlite3.connect(msg_db)
    con.execute("ALTER TABLE message ADD COLUMN element_descriptions TEXT")
    con.execute("UPDATE message SET element_descriptions = ?", (" tX7ZtbBHhfmNkZ6l7hRFog==",))
    con.commit()
    con.close()
    sender = UiaWuQuanMessageSender(msg_db_path=msg_db, window_provider=lambda: None, verify_timeout_sec=0)

    assert sender.verify_local_message("207191791", "小单 1") is True


def test_uia_sender_verifies_only_messages_after_send_cursor(tmp_path):
    msg_db = tmp_path / "msg_0.db"
    _create_msg_db(msg_db, [("207191791", "小单 100", 100)])
    sender = UiaWuQuanMessageSender(msg_db_path=msg_db, window_provider=lambda: None, verify_timeout_sec=0)

    cursor = sender.capture_message_cursor("207191791")
    assert sender.verify_local_message("207191791", "小单 100", after_cursor=cursor) is False

    con = sqlite3.connect(msg_db)
    con.execute("INSERT INTO message (sid, content, client_time) VALUES (?, ?, ?)", ("207191791", "小单 100", 101))
    con.commit()
    con.close()

    assert sender.verify_local_message("207191791", "小单 100", after_cursor=cursor) is True
