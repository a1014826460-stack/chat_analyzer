"""Centralized draw crawler and confirmed-order WSS sender."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select

from server_api.db import BetOrder, DrawResult, create_engine, create_session_factory
from server_api.settings import settings
from server_api.services.redis_state import acquire_lock, release_lock
from server_api.services.runtime_logs import RuntimeLogService
from server_api.workers.crawler import crawl_site
from server_api.workers.current_period import fetch_current_period
from server_api.workers.history_sources import fetch_history_records, site_list
from server_api.workers.sender import ProductionWssSender, expire_non_current_confirmed_orders, expire_pending_orders, process_confirmed_order
from server_api.workers.strategy_scheduler import schedule_frequency_orders


logger = logging.getLogger(__name__)


async def run_cycle(
    session_factory,
    *,
    fetch_records: Callable = fetch_history_records,
    sender_factory: Callable = ProductionWssSender,
    history_count: int = 100,
    redis: object | None = None,
) -> None:
    lock_key = "worker:central-cycle"
    if redis is not None and not await acquire_lock(redis, lock_key):
        return
    try:
        await _run_cycle(session_factory, fetch_records, sender_factory, history_count)
    finally:
        if redis is not None:
            await release_lock(redis, lock_key)


def _is_placeholder_secret(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    return normalized in {
        "replace-with-server-ai-key",
        "replace-with-ai-api-key",
        "replace-with-openai-api-key",
        "your-api-key",
        "your_api_key",
        "sk-xxxx",
    } or normalized.startswith("replace-") or normalized.startswith("your-")


def _shared_ai_client_from_settings(config=settings):
    if not config.ai_base_url or not config.ai_model or _is_placeholder_secret(config.ai_api_key):
        return None
    from server_api.services.ai_client import SharedAiClient

    return SharedAiClient(
        provider=config.ai_provider,
        base_url=config.ai_base_url,
        model=config.ai_model,
        api_key=config.ai_api_key,
        timeout_seconds=getattr(config, "ai_timeout_seconds", 45),
        max_retries=getattr(config, "ai_max_retries", 2),
        retry_backoff_seconds=getattr(config, "ai_retry_backoff_seconds", 1),
    )


async def _run_cycle(session_factory, fetch_records: Callable, sender_factory: Callable, history_count: int) -> None:
    ai_client = _shared_ai_client_from_settings(settings)
    current_periods: dict[str, str] = {}
    async with session_factory() as session:
        for site in site_list():
            try:
                await crawl_site(session, site=site, history_count=history_count, fetch_records=fetch_records)
                current = await asyncio.to_thread(fetch_current_period, site)
                if current is not None:
                    current_periods[site] = str(current.period)
                    await schedule_frequency_orders(
                        session,
                        site=site,
                        period=current.period,
                        betting_deadline_at=current.betting_deadline_at,
                        ai_client=ai_client,
                    )
            except Exception:
                logger.exception("crawl failed for site=%s", site)

    async with session_factory() as session:
        await expire_pending_orders(session)
        await expire_non_current_confirmed_orders(session, current_periods)
        order_ids = (await session.scalars(select(BetOrder.id).where(BetOrder.status == "confirmed"))).all()
        for order_id in order_ids:
            await process_confirmed_order(
                session,
                order_id=order_id,
                encryption_secret=settings.credential_encryption_secret,
                sender_factory=sender_factory,
            )
        try:
            import os
            import psutil

            process = psutil.Process()
            await RuntimeLogService(session).write(
                level="INFO",
                category="system",
                message="worker cycle completed",
                details={
                    "pid": os.getpid(),
                    "cpu_percent": process.cpu_percent(interval=None),
                    "memory_bytes": process.memory_info().rss,
                },
                service_name="worker",
            )
            await session.commit()
        except Exception:
            logger.exception("unable to write worker runtime metrics")


async def run_forever(poll_seconds: float = 5.0) -> None:
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url)
    try:
        while True:
            await run_cycle(factory, redis=redis)
            await asyncio.sleep(poll_seconds)
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
