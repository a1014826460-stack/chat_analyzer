from __future__ import annotations

import json


def test_local_wss_credentials_exposes_the_canonical_preferences_path():
    from app.services.account_resolver import DEFAULT_SHARED_PREFS as resolver_path
    from app.services.local_wss_credentials import DEFAULT_SHARED_PREFS

    assert DEFAULT_SHARED_PREFS == resolver_path


def test_local_wss_credential_provider_prefers_im_sdk_appid_for_web_wss(tmp_path):
    from app.services.local_wss_credentials import LocalWssCredentialProvider

    prefs = tmp_path / "shared_preferences.json"
    prefs.write_text(json.dumps({
        "flutter.SpKeyLoginResult-accid-a": json.dumps({
            "appid": "business-app",
            "accid": "accid-a",
            "token": "local-user-sig",
            "imAppid": "20011216",
        }),
    }), encoding="utf-8")

    credentials = LocalWssCredentialProvider(prefs).read("accid-a")

    assert credentials.appid == "20011216"
    assert credentials.accid == "accid-a"
    assert credentials.user_sig == "local-user-sig"


def test_local_wss_credential_provider_falls_back_to_business_appid_when_im_appid_absent(tmp_path):
    from app.services.local_wss_credentials import LocalWssCredentialProvider

    prefs = tmp_path / "shared_preferences.json"
    prefs.write_text(json.dumps({
        "flutter.SpKeyLoginResult-accid-a": json.dumps({
            "appid": "business-app", "accid": "accid-a", "token": "local-user-sig",
        }),
    }), encoding="utf-8")

    credentials = LocalWssCredentialProvider(prefs).read("accid-a")

    assert credentials.appid == "business-app"
    assert credentials.accid == "accid-a"
    assert credentials.user_sig == "local-user-sig"
