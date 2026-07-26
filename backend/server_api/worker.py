"""Centralized draw crawler and confirmed-order WSS sender."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select

from server_api.db import BetOrder, DrawResult, create_engine, create_session_factory
from server_api.settings import settings
from server_api.services.redis_state import acquire_lock, release_lock
from server_api.workers.crawler import crawl_site
from server_api.workers.current_period import fetch_current_period
from server_api.workers.history_sources import fetch_history_records, site_list
from server_api.workers.sender import ProductionWssSender, expire_pending_orders, process_confirmed_order
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


async def _run_cycle(session_factory, fetch_records: Callable, sender_factory: Callable, history_count: int) -> None:
    async with session_factory() as session:
        for site in site_list():
            try:
                await crawl_site(session, site=site, history_count=history_count, fetch_records=fetch_records)
                current = await asyncio.to_thread(fetch_current_period, site)
                if current is not None:
                    await schedule_frequency_orders(
                        session,
                        site=site,
                        period=current.period,
                        betting_deadline_at=current.betting_deadline_at,
                    )
            except Exception:
                logger.exception("crawl failed for site=%s", site)

    async with session_factory() as session:
        await expire_pending_orders(session)
        order_ids = (await session.scalars(select(BetOrder.id).where(BetOrder.status == "confirmed"))).all()
        for order_id in order_ids:
            await process_confirmed_order(
                session,
                order_id=order_id,
                encryption_secret=settings.credential_encryption_secret,
                sender_factory=sender_factory,
            )


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
