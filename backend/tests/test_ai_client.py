from __future__ import annotations

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


def test_shared_ai_client_uses_server_key_and_rejects_plays_outside_constraints():
    captured = {}

    def opener(request, timeout):
        captured["headers"] = dict(request.header_items())
        return _Response(
            b'{"choices":[{"message":{"content":"{\\"action\\":\\"bet\\",\\"play_type\\":\\"\\u5927\\u53cc\\",\\"confidence\\":61,\\"reason\\":\\"frequency\\"}"}}]}'
        )

    client = SharedAiClient(
        provider="openai_compatible", base_url="https://model.example", model="model", api_key="server-secret", opener=opener
    )
    result = client.recommend(site="pc28", history=[{"period": "1", "result": "大双"}], allowed_plays=["大双"])

    assert result == {"action": "bet", "play_type": "大双", "confidence": 61, "reason": "frequency"}
    assert captured["headers"]["Authorization"] == "Bearer server-secret"

    try:
        client.recommend(site="pc28", history=[], allowed_plays=["小单"])
    except SharedAiClientError as exc:
        assert "不在允许玩法" in str(exc)
    else:
        raise AssertionError("expected invalid-play rejection")
