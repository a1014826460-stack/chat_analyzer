from __future__ import annotations

import json


def test_local_wss_credential_provider_reads_current_account_without_displaying_or_persisting_secret(tmp_path):
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
