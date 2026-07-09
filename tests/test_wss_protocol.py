from __future__ import annotations

import base64
import json

import tests.tests_wss as wss


def test_encode_frame_matches_websdk_direct_json_binary_frame():
    frame = wss.encode_frame(
        {"servcmd": "im_open_status.wslogin", "seq": 123},
        {"State": "Online"},
    )

    assert isinstance(frame, bytes)
    assert json.loads(frame.decode("utf-8")) == {
        "head": {"servcmd": "im_open_status.wslogin", "seq": 123},
        "body": {"State": "Online"},
    }
    assert wss.decode_frame(frame) == {
        "head": {"servcmd": "im_open_status.wslogin", "seq": 123},
        "body": {"State": "Online"},
    }


def test_build_login_head_uses_reqable_observed_tencent_im_fields():
    client = wss.ImWssClient(
        sdk_app_id=20011216,
        identifier="A7MYtCxL8",
        user_sig="sig",
        seq_start=100,
        instance_id="abc123",
    )

    head = client.build_login_head()

    assert head["ver"] == "v4"
    assert head["platform"] == 7
    assert head["websdkappid"] == 537048168
    assert head["websdkversion"] == "1.7.3"
    assert head["sdkappid"] == 20011216
    assert head["identifier"] == "A7MYtCxL8"
    assert head["usersig"] == "sig"
    assert head["sdkability"] == 192371
    assert head["servcmd"] == "im_open_status.wslogin"
    assert head["seq"] == 101


def test_encrypt_text_uses_frontend_aes_key_and_roundtrips_unicode():
    assert wss.encrypt_text("hello") == "9vmso8yFAuLUMTgcJ2tJig=="

    text = "\u5c0f\u5355 1"
    assert wss.decrypt_text(wss.encrypt_text(text)) == text
