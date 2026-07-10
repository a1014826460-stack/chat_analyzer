from __future__ import annotations

import json

import pytest

from app.models.auto_bet import DrawResult, StrategyConfig


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def _config(**overrides) -> StrategyConfig:
    values = {
        "strategy_type": "ai",
        "ai_provider": "openai_compatible",
        "ai_base_url": "https://ai.example/api",
        "ai_model": "test-model",
        "ai_api_key": "secret",
    }
    values.update(overrides)
    return StrategyConfig(**values)


def test_openai_client_posts_chat_completion_and_parses_strict_json():
    from app.services.ai_bet_client import AiBetClient

    captured = {}

    def fake_opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"choices": [{"message": {"content": '{"play_type":"小双","reason":"测试"}'}}]})

    recommendation = AiBetClient(opener=fake_opener).recommend(
        _config(),
        [DrawResult(period="1", site="pc28", result="大单")],
    )

    assert recommendation.play_type == "小双"
    assert recommendation.reason == "测试"
    assert captured["url"] == "https://ai.example/api/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["messages"][1]["content"].startswith("站点: pc28")
    assert captured["timeout"] == 20


def test_anthropic_client_posts_messages_and_reads_text_content():
    from app.services.ai_bet_client import AiBetClient

    captured = {}

    def fake_opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"content": [{"type": "text", "text": '{"play_type":"大","reason":"测试"}'}]})

    recommendation = AiBetClient(opener=fake_opener).recommend(
        _config(ai_provider="anthropic", ai_base_url="https://claude.example"),
        [DrawResult(period="1", site="pc28", result="大单")],
    )

    assert recommendation.play_type == "大"
    assert captured["url"] == "https://claude.example/v1/messages"
    assert captured["headers"]["X-api-key"] == "secret"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["payload"]["model"] == "test-model"


def test_client_rejects_a_response_with_an_unknown_play_type():
    from app.services.ai_bet_client import AiBetClient, AiBetClientError

    def fake_opener(request, timeout):
        return FakeResponse({"choices": [{"message": {"content": '{"play_type":"豹子","reason":"测试"}'}}]})

    with pytest.raises(AiBetClientError, match="非法玩法"):
        AiBetClient(opener=fake_opener).recommend(
            _config(),
            [DrawResult(period="1", site="pc28", result="大单")],
        )


def test_ai_config_round_trip_preserves_provider_and_confirmation_fields():
    config = _config(
        ai_history_count=80,
        ai_require_confirmation=True,
    )

    restored = StrategyConfig.from_dict(config.to_dict())

    assert restored.ai_provider == "openai_compatible"
    assert restored.ai_base_url == "https://ai.example/api"
    assert restored.ai_model == "test-model"
    assert restored.ai_api_key == "secret"
    assert restored.ai_history_count == 80
    assert restored.ai_require_confirmation is True
