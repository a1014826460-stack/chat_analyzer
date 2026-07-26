from app.services.server_mode_settings import ServerModeSettings


def test_server_mode_settings_round_trip_and_do_not_store_server_token():
    settings = ServerModeSettings.from_dict({
        "enabled": True,
        "base_url": "http://127.0.0.1:8080/",
        "access_token": "must-not-persist",
    })

    assert settings.enabled is True
    assert settings.base_url == "http://127.0.0.1:8080"
    assert settings.to_dict() == {"enabled": True, "base_url": "http://127.0.0.1:8080"}
