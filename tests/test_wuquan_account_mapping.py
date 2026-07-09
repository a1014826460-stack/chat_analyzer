from __future__ import annotations

import json

from app.services.wuquan_account_mapping import resolve_im_accid, resolve_login_account


def test_resolve_business_appid_to_im_accid_from_account_manager_list():
    payload = {
        "flutter.AccountManager_AccountList": [
            json.dumps({
                "accid": "A7MYtCxL8",
                "loginResultEntity": {"appid": "lin2225427", "accid": "A7MYtCxL8", "token": "sig-a"},
            }),
            json.dumps({
                "accid": "x1DuArYgV",
                "loginResultEntity": {"appid": "LYGG88888", "accid": "x1DuArYgV", "token": "sig-b"},
            }),
        ]
    }

    assert resolve_im_accid("LYGG88888", payload) == "x1DuArYgV"


def test_resolve_login_account_matches_appid_or_accid_and_returns_token():
    payload = {
        "flutter.SpKeyLoginResult-x1DuArYgV": json.dumps({
            "appid": "LYGG88888",
            "accid": "x1DuArYgV",
            "token": "sig-b",
            "imAppid": "20011216",
        })
    }

    account = resolve_login_account("LYGG88888", payload)

    assert account is not None
    assert account.accid == "x1DuArYgV"
    assert account.appid == "LYGG88888"
    assert account.user_sig == "sig-b"
    assert account.im_appid == "20011216"
    assert resolve_login_account("x1DuArYgV", payload) == account


def test_resolve_login_account_falls_back_to_explicit_accid_with_user_sig():
    from tools.test_web_wss_c2c_message import parse_explicit_sender

    account = parse_explicit_sender(
        from_id="lin2225427",
        from_accid="A7MYtCxL8",
        user_sig="sig-a",
        sdk_app_id="20011216",
    )

    assert account.accid == "A7MYtCxL8"
    assert account.appid == "lin2225427"
    assert account.user_sig == "sig-a"
    assert account.im_appid == "20011216"
