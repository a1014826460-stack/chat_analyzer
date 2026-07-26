from __future__ import annotations

from app.services.server_api_client import ServerApiClient, ServerApiError


def test_server_api_client_authenticates_with_local_signed_license_and_confirms_pending_bet():
    calls: list[tuple[str, str, dict | None]] = []

    def request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        calls.append((method, path, payload))
        if path == "/v1/auth/session":
            return {"access_token": "token"}
        if path == "/v1/bets/pending":
            return {"items": [{"id": 7, "status": "pending_confirmation"}]}
        if path == "/v1/bets/7/confirm":
            return {"id": 7, "status": "confirmed"}
        raise AssertionError(path)

    client = ServerApiClient("http://server.test", request=request)
    client.login_with_local_license("machine-code", "signed-local-license")

    assert client.pending_bets() == [{"id": 7, "status": "pending_confirmation"}]
    assert client.confirm_bet(7)["status"] == "confirmed"
    assert calls[0] == ("POST", "/v1/auth/session", {"machine_code": "machine-code", "license_token": "signed-local-license"})


def test_server_api_client_refuses_authenticated_calls_before_login():
    client = ServerApiClient("http://server.test", request=lambda *_: {})

    try:
        client.pending_bets()
    except ServerApiError as exc:
        assert "未登录" in str(exc)
    else:
        raise AssertionError("expected an authentication error")


def test_server_api_client_manages_wss_credentials_and_reads_frequency_analysis():
    calls: list[tuple[str, str, dict | None, dict[str, str]]] = []

    def request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        calls.append((method, path, payload, headers))
        if path == "/v1/auth/session":
            return {"access_token": "token"}
        if path == "/v1/integrations/wss-credentials" and method == "PUT":
            return {"appid": "10001", "accid_masked": "ac***id", "version": 1}
        if path == "/v1/analysis/frequency?site=pc28&history_count=50&confidence_threshold=60":
            return {"sample_count": 50, "should_bet": True}
        raise AssertionError((method, path))

    client = ServerApiClient("http://server.test", request=request)
    client.login("machine-code", "activation-code")

    assert client.save_wss_credentials("10001", "accid", "private-sig")["accid_masked"] == "ac***id"
    assert client.frequency_analysis("pc28", history_count=50, confidence_threshold=60)["sample_count"] == 50
    assert calls[1][2] == {"appid": "10001", "accid": "accid", "user_sig": "private-sig"}
    assert calls[1][3]["Authorization"] == "Bearer token"
