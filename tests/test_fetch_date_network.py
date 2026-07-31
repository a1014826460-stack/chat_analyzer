from __future__ import annotations

import json
import urllib.error


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_fetch_date_request_retries_transient_ssl_eof(monkeypatch):
    from app.utils import fetch_date

    attempts = {"count": 0}

    def flaky_urlopen(_request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.URLError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(fetch_date.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(fetch_date.time, "sleep", lambda _seconds: None)

    assert fetch_date._request_json("https://gaga28.com/api/ajax2.php", data=None, headers=None) == {"ok": True}
    assert attempts["count"] == 2


def test_fetch_date_request_falls_back_to_direct_when_proxy_path_fails(monkeypatch):
    from app.utils import fetch_date

    calls: list[str] = []
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")
    monkeypatch.setattr(fetch_date.time, "sleep", lambda _seconds: None)

    def fake_urlopen(_request, timeout):
        calls.append("env-proxy")
        raise urllib.error.URLError("[SSL: UNEXPECTED_EOF_WHILE_READING]")

    class DirectOpener:
        def open(self, _request, timeout=0):
            calls.append("direct")
            return _FakeResponse({"ok": True})

    monkeypatch.setattr(fetch_date.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(fetch_date.urllib.request, "build_opener", lambda handler: DirectOpener())

    assert fetch_date._request_json("https://gaga28.com/api/ajax2.php", data=None, headers=None) == {"ok": True}
    assert "env-proxy" in calls
    assert calls[-1] == "direct"
