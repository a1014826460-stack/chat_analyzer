"""Unit tests for ImSDK receive-message callback wiring."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.message_injector import MessageInjector


class FakeDll:
    def __init__(self) -> None:
        self.added = []
        self.removed = []
        self.recv_cb = None

    def TIMAddRecvNewMsgCallback(self, callback, user_data):
        self.added.append((callback, user_data))
        self.recv_cb = callback

    def TIMRemoveRecvNewMsgCallback(self, callback):
        self.removed.append(callback)


def make_injector() -> MessageInjector:
    inj = MessageInjector(Path("dummy.dll"), 20011216, "alice", "sig")
    inj._dll = FakeDll()  # type: ignore[assignment]
    return inj


def test_register_recv_callback_keeps_callable_alive_and_calls_sdk() -> None:
    inj = make_injector()

    inj._register_recv_callback()

    fake = inj._dll
    assert fake.added
    assert fake.recv_cb is inj._recv_cb


def test_recv_callback_decodes_message_array_and_notifies_handlers() -> None:
    inj = make_injector()
    seen = []
    inj.add_recv_handler(seen.append)
    inj._register_recv_callback()

    raw_message = {
        "message_conv_id": "207191791",
        "message_sender": "bob",
        "message_elem_array": [
            {"elem_type": 0, "text_elem_content": "hello"},
        ],
    }
    inj._dll.recv_cb(json.dumps([raw_message], ensure_ascii=False).encode("utf-8"), None)

    assert inj.received_messages == [raw_message]
    assert seen == [raw_message]


def test_wait_for_messages_returns_queued_messages_matching_predicate() -> None:
    inj = make_injector()
    message = {"message_conv_id": "g1", "message_sender": "bob"}
    inj._recv_new_msg_handler(json.dumps([message]).encode("utf-8"), None)

    got = inj.wait_for_messages(timeout=0.1, predicate=lambda msg: msg.get("message_conv_id") == "g1")

    assert got == [message]
