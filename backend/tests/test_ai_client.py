from __future__ import annotations

import socket
from urllib.error import HTTPError

from server_api.services.ai_client import SharedAiClient, SharedAiClientError


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self.body


def test_shared_ai_client_uses_server_key_for_three_door_decision():
    captured = {}

    def opener(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _Response(
            b'{"choices":[{"message":{"content":"{\\"action\\":\\"execute\\",\\"confidence\\":61,\\"reason\\":\\"frequency\\"}"}}]}'
        )

    client = SharedAiClient(
        provider="openai_compatible", base_url="https://model.example", model="model", api_key="server-secret", opener=opener
    )
    result = client.recommend_three_doors(site="pc28", history=[{"period": "1", "result": "大双"}], selected_plays=["大双", "小单", "大单"])

    assert result == {"action": "execute", "confidence": 61, "reason": "frequency"}
    assert captured["headers"]["Authorization"] == "Bearer server-secret"
    assert captured["timeout"] == 30


def test_shared_ai_client_retries_transient_read_timeout_before_failing():
    calls = {"count": 0}

    def opener(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise socket.timeout("The read operation timed out")
        return _Response(
            b'{"choices":[{"message":{"content":"{\\"action\\":\\"skip\\",\\"confidence\\":70,\\"reason\\":\\"retry ok\\"}"}}]}'
        )

    client = SharedAiClient(
        provider="openai_compatible",
        base_url="https://model.example",
        model="model",
        api_key="server-secret",
        opener=opener,
        timeout_seconds=45,
        max_retries=2,
        retry_backoff_seconds=0,
    )

    assert client.recommend_three_doors(site="pc28", history=[], selected_plays=["小单", "大双", "大单"]) == {
        "action": "skip", "confidence": 70, "reason": "retry ok"
    }
    assert calls["count"] == 2


def test_shared_ai_client_reports_authentication_failure_clearly_without_retry():
    calls = {"count": 0}

    def opener(_request, timeout):
        calls["count"] += 1
        raise HTTPError("https://model.example/chat/completions", 401, "Authorization Required", hdrs=None, fp=None)

    client = SharedAiClient(
        provider="openai_compatible",
        base_url="https://model.example",
        model="model",
        api_key="bad-key",
        opener=opener,
        max_retries=3,
        retry_backoff_seconds=0,
    )

    try:
        client.recommend_three_doors(site="pc28", history=[], selected_plays=["小单", "大双", "大单"])
    except SharedAiClientError as exc:
        assert "服务器 AI 密钥无效或鉴权失败" in str(exc)
    else:
        raise AssertionError("expected auth failure")
    assert calls["count"] == 1
