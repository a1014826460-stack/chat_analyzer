from __future__ import annotations

from pathlib import Path

import pytest

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
        if path == "/v1/analysis/frequency?site=pc28&history_count=50&confidence_threshold=60&target_period=1002":
            return {"sample_count": 50, "should_bet": True}
        raise AssertionError((method, path))

    client = ServerApiClient("http://server.test", request=request)
    client.login_with_local_license("machine-code", "activation-code")

    assert client.save_wss_credentials("10001", "accid", "private-sig")["accid_masked"] == "ac***id"
    assert client.frequency_analysis("pc28", history_count=50, confidence_threshold=60, target_period="1002")["sample_count"] == 50
    assert calls[1][2] == {"appid": "10001", "accid": "accid", "user_sig": "private-sig"}
    assert calls[1][3]["Authorization"] == "Bearer token"


def test_server_api_client_fetches_betting_statistics_with_site_and_window():
    from app.services.server_api_client import ServerApiClient

    calls = []

    def request(method, path, payload, headers):
        calls.append((method, path, payload, dict(headers)))
        return {"runtime_state": {"total_rounds": 1}, "ai_statistics": {"settled_count": 1}}

    client = ServerApiClient("http://server", request=request)
    client._access_token = "token"

    result = client.betting_statistics("pc28", ai_window=30)

    assert result["runtime_state"]["total_rounds"] == 1
    assert calls == [("GET", "/v1/bets/statistics?site=pc28&ai_window=30", None, {"Accept": "application/json", "Authorization": "Bearer token"})]



def test_server_api_client_fetches_betting_statistics_since_run_start():
    from datetime import datetime
    from app.services.server_api_client import ServerApiClient

    calls = []
    client = ServerApiClient("http://server", request=lambda method, path, payload, headers: calls.append(path) or {"runtime_state": {}, "ai_statistics": {}})
    client._access_token = "token"
    client.betting_statistics("pc28", ai_window=20, since=datetime(2026, 7, 28, 22, 22, 49))

    assert calls == ["/v1/bets/statistics?site=pc28&ai_window=20&since=2026-07-28T22%3A22%3A49"]


def test_server_api_client_fetches_betting_events_since_run_start():
    from datetime import datetime
    from app.services.server_api_client import ServerApiClient

    calls = []
    client = ServerApiClient("http://server", request=lambda method, path, payload, headers: calls.append(path) or {"items": []})
    client._access_token = "token"

    client.betting_events(after_id=12, limit=50, site="pc28", since=datetime(2026, 7, 28, 22, 22, 49))

    assert calls == ["/v1/bets/events?after_id=12&limit=50&site=pc28&since=2026-07-28T22%3A22%3A49"]


def test_server_api_client_fetches_server_owned_ai_prediction_history():
    calls = []
    client = ServerApiClient("http://server", request=lambda method, path, payload, headers: calls.append(path) or {"items": []})
    client._access_token = "token"

    assert client.ai_prediction_history("pc28", limit=80) == []
    assert calls == ["/v1/bets/ai-history?site=pc28&limit=80"]


def test_server_api_client_fetches_runtime_logs_with_filters_and_cursor():
    calls = []
    client = ServerApiClient("http://server", request=lambda method, path, payload, headers: calls.append(path) or {"items": [{"id": 19}]})
    client._access_token = "token"

    page = client.runtime_logs(level="ERROR", category="exception", keyword="timeout", before_id=20, limit=50)

    assert page["items"] == [{"id": 19}]
    assert calls == ["/v1/runtime-logs?limit=50&level=ERROR&category=exception&keyword=timeout&before_id=20"]


def test_server_api_client_reads_current_draw_through_the_server():
    calls = []
    client = ServerApiClient(
        "http://server",
        request=lambda method, path, payload, headers: calls.append(path)
        or {"current_period": "100", "next_period": "101"},
    )
    client._access_token = "token"

    assert client.current_draw("pc28") == {"current_period": "100", "next_period": "101"}
    assert calls == ["/v1/draws/pc28/current"]


def test_server_api_client_reads_draw_history_through_the_server():
    calls = []
    client = ServerApiClient("http://server", request=lambda method, path, payload, headers: calls.append(path) or {"items": [{"period": "100"}]})
    client._access_token = "token"

    assert client.draw_history("pc28", limit=80) == [{"period": "100"}]
    assert calls == ["/v1/draws/pc28/history?limit=80"]


def test_server_api_client_reads_update_manifest_and_file_through_the_server():
    calls = []
    client = ServerApiClient("http://server", request=lambda method, path, payload, headers: calls.append(path) or {"version": "2.0.0"})
    client._access_token = "token"

    assert client.update_manifest()["version"] == "2.0.0"
    assert client.update_file_path("StarTrace-2.0.0.exe") == "/v1/updates/files/StarTrace-2.0.0.exe"
    assert calls == ["/v1/updates/manifest"]


def test_server_api_client_streams_authenticated_update_to_an_atomic_file(monkeypatch, tmp_path: Path):
    requests = []

    class Response:
        def __init__(self) -> None:
            self.chunks = [b"server-", b"artifact", b""]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size: int) -> bytes:
            assert size == 65536
            return self.chunks.pop(0)

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr("app.services.server_api_client.urlopen", fake_urlopen)
    client = ServerApiClient("https://server.example")
    client._access_token = "jwt-token"
    target = tmp_path / "update.exe"

    client.download_update_file("update.exe", target, expected_size=len(b"server-artifact"))

    assert target.read_bytes() == b"server-artifact"
    assert not target.with_name("update.exe.part").exists()
    assert requests[0][0].get_header("Authorization") == "Bearer jwt-token"


def test_server_api_client_removes_partial_update_when_response_exceeds_signed_size(monkeypatch, tmp_path: Path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size: int) -> bytes:
            return b"too-large"

    monkeypatch.setattr("app.services.server_api_client.urlopen", lambda request, timeout: Response())
    client = ServerApiClient("https://server.example")
    client._access_token = "jwt-token"
    target = tmp_path / "update.exe"

    with pytest.raises(ServerApiError, match="大小"):
        client.download_update_file("update.exe", target, expected_size=3)

    assert not target.exists()
    assert not target.with_name("update.exe.part").exists()
