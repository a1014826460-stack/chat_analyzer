from __future__ import annotations

import asyncio
from urllib.error import HTTPError

from sqlalchemy import select


def test_worker_treats_placeholder_ai_key_as_unconfigured():
    from server_api.worker import _shared_ai_client_from_settings

    class Settings:
        ai_provider = "openai_compatible"
        ai_base_url = "https://api.deepseek.com"
        ai_model = "deepseek-chat"
        ai_api_key = "replace-with-server-ai-key"
        ai_timeout_seconds = 45
        ai_max_retries = 2
        ai_retry_backoff_seconds = 0.5

    assert _shared_ai_client_from_settings(Settings()) is None


def test_worker_passes_ai_timeout_and_retry_settings_to_shared_client():
    from server_api.worker import _shared_ai_client_from_settings

    class Settings:
        ai_provider = "openai_compatible"
        ai_base_url = "https://api.deepseek.com"
        ai_model = "deepseek-chat"
        ai_api_key = "sk-real"
        ai_timeout_seconds = 45
        ai_max_retries = 2
        ai_retry_backoff_seconds = 0.5

    client = _shared_ai_client_from_settings(Settings())

    assert client is not None
    assert client.timeout_seconds == 45
    assert client.max_retries == 2
    assert client.retry_backoff_seconds == 0.5


def test_shared_ai_client_reports_authentication_failure_clearly():
    from server_api.services.ai_client import SharedAiClient, SharedAiClientError

    def opener(_request, timeout):
        raise HTTPError("https://model.example/chat/completions", 401, "Authorization Required", hdrs=None, fp=None)

    client = SharedAiClient(
        provider="openai_compatible",
        base_url="https://model.example",
        model="model",
        api_key="bad-key",
        opener=opener,
    )

    try:
        client.recommend_three_doors(site="pc28", history=[], selected_plays=["小单", "大双", "大单"])
    except SharedAiClientError as exc:
        assert "服务器 AI 密钥无效或鉴权失败" in str(exc)
    else:
        raise AssertionError("expected auth failure")


def test_frequency_scheduler_places_algorithm_order_when_ai_key_is_placeholder():
    from server_api.db import AutoBetStrategy, DrawResult, StrategyEvent, create_engine, create_schema, create_session_factory
    from server_api.worker import _shared_ai_client_from_settings
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    class Settings:
        ai_provider = "openai_compatible"
        ai_base_url = "https://api.deepseek.com"
        ai_model = "deepseek-chat"
        ai_api_key = "replace-with-server-ai-key"
        ai_timeout_seconds = 45
        ai_max_retries = 2
        ai_retry_backoff_seconds = 0.5

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=1,
                enabled=True,
                site="pc28",
                target_groups_json='["g1"]',
                history_count=3,
                confidence_threshold=30,
                require_confirmation=False,
                bet_amount=1,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大单", total=15),
            ])
            await session.commit()
            await schedule_frequency_orders(
                session,
                site="pc28",
                period="4",
                ai_client=_shared_ai_client_from_settings(Settings()),
            )
            event = await session.scalar(select(StrategyEvent))
            assert event is not None
            # 纯算法下注模式：AI 未配置时仍执行算法决策
            assert event.event_type == "ai_execute"
            assert "算法决策下注" in event.message
        await engine.dispose()

    asyncio.run(scenario())
