from __future__ import annotations

import urllib.error


class _FakeResponse:
    status = 200

    def __init__(self, body: bytes = b'{"ok": true}') -> None:
        self._body = body
        self.headers = self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def get_content_charset(self):
        return "utf-8"

    def read(self):
        return self._body


def test_history_source_text_request_retries_transient_ssl_or_timeout_errors(monkeypatch):
    from server_api.workers import history_sources

    attempts = {"count": 0}

    def flaky_urlopen(_request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.URLError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
        return _FakeResponse(b'{"recent_records": []}')

    monkeypatch.setattr(history_sources.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(history_sources.time, "sleep", lambda _seconds: None)

    assert history_sources._get_text("https://jnd28-yc.vip/api/dashboard") == '{"recent_records": []}'
    assert attempts["count"] == 2


def test_history_source_text_request_uses_browser_like_headers(monkeypatch):
    from server_api.workers import history_sources

    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(history_sources.urllib.request, "urlopen", fake_urlopen)

    history_sources._get_text("https://jnd28-yc.vip/api/dashboard", headers={"referer": "https://jnd28-yc.vip/"})

    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert "edg/150" in headers["user-agent"].lower()
    assert headers["sec-fetch-site"] == "same-origin"
    assert headers["referer"] == "https://jnd28-yc.vip/"
    assert captured["timeout"] >= 20
