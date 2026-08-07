"""Centralized draw crawler and confirmed-order WSS sender."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections.abc import Callable

from sqlalchemy import select

from server_api.db import BetOrder, DrawResult, ServiceHeartbeat, create_engine, create_session_factory
from server_api.settings import settings
from server_api.services.redis_state import acquire_lock, release_lock
from server_api.services.runtime_logs import RuntimeLogService
from server_api.services.bet_settlements import settle_new_draws
from server_api.workers.crawler import crawl_site
from server_api.workers.current_period import fetch_current_period
from server_api.workers.history_sources import fetch_history_records, site_list
from server_api.workers.sender import (
    ProductionWssSender,
    expire_non_current_confirmed_orders,
    expire_pending_orders,
    process_confirmed_order,
    write_group_bet_runtime_logs,
)
from server_api.workers.strategy_scheduler import schedule_frequency_orders


logger = logging.getLogger(__name__)


_DRAW_SOURCE_URLS = {
    "pc28": "https://jnd28-yc.vip/api/dashboard",
    "macao": "https://macao.zhifu.qpon/api/openApi/lottery/draw",
    "australia": "https://gaga28.com/api/ajax2.php",
    "norway": "https://p17-qq-server.vqimpic.cc/v1/selfapi/lottery",
}
_SITE_LABELS = {"pc28": "PC28", "macao": "澳门", "australia": "澳洲", "norway": "挪威"}


async def _latest_draw_period(session, site: str) -> str:
    periods = (await session.scalars(
        select(DrawResult.period).where(DrawResult.site == site)
    )).all()
    if not periods:
        return ""
    numeric = [str(period) for period in periods if str(period).isdigit()]
    if numeric:
        return max(numeric, key=lambda value: int(value))
    return max(str(period) for period in periods)


def _is_future_period(target_period: str, latest_draw_period: str) -> bool:
    target = str(target_period or "").strip()
    latest = str(latest_draw_period or "").strip()
    if not target:
        return False
    if not latest:
        return True
    if target.isdigit() and latest.isdigit():
        return int(target) > int(latest)
    return target > latest


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


async def _record_heartbeat(session_factory) -> None:
    async with session_factory() as session:
        heartbeat = await session.get(ServiceHeartbeat, "worker")
        if heartbeat is None:
            heartbeat = ServiceHeartbeat(service_name="worker", status="healthy")
            session.add(heartbeat)
        else:
            heartbeat.status = "healthy"
            heartbeat.updated_at = __import__("datetime").datetime.utcnow()
        await session.commit()


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
    current_periods: dict[str, str] = {}
    async with session_factory() as session:
        ai_client = None
        if getattr(settings, "ai_decision_enabled", False):
            from server_api.services.ai_settings import load_ai_configuration
            from server_api.services.ai_client import SharedAiClient

            saved_ai = await load_ai_configuration(session, encryption_secret=settings.credential_encryption_secret)
            ai_client = (
                SharedAiClient(provider=saved_ai.provider, base_url=saved_ai.base_url, model=saved_ai.model, api_key=saved_ai.api_key,
                               timeout_seconds=settings.ai_timeout_seconds, max_retries=settings.ai_max_retries,
                               retry_backoff_seconds=settings.ai_retry_backoff_seconds)
                if saved_ai is not None else _shared_ai_client_from_settings(settings)
            )
        for site in site_list():
            started = time.perf_counter()
            try:
                records_written = await crawl_site(
                    session,
                    site=site,
                    history_count=history_count,
                    fetch_records=fetch_records,
                )
                current = await asyncio.to_thread(fetch_current_period, site)
                if current is not None:
                    latest_draw_period = await _latest_draw_period(session, site)
                    if _is_future_period(str(current.period), latest_draw_period):
                        current_periods[site] = str(current.period)
                        await schedule_frequency_orders(
                            session,
                            site=site,
                            period=current.period,
                            betting_deadline_at=current.betting_deadline_at,
                            ai_client=ai_client,
                        )
                    else:
                        await RuntimeLogService(session).write(
                            level="WARN",
                            category="strategy",
                            message=(
                                f"{_SITE_LABELS.get(site, site)} 目标期已过期："
                                f"下一期 {current.period}，最新已开奖 {latest_draw_period}，拒绝下注"
                            ),
                            details={
                                "site": site,
                                "target_period": str(current.period),
                                "latest_draw_period": latest_draw_period,
                            },
                            service_name="period_guard",
                        )
                await RuntimeLogService(session).write(
                    level="DEBUG",
                    category="third_party",
                    message=f"{_SITE_LABELS.get(site, site)} 外部开奖同步成功",
                    details={
                        "site": site,
                        "operation": "draw_sync",
                        "records_written": records_written,
                        "current_period": str(current.period) if current is not None else "",
                    },
                    request_url=_DRAW_SOURCE_URLS.get(site),
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    status_code=200,
                    service_name="draw_crawler",
                )
                await session.commit()
            except Exception as exc:
                trace = traceback.format_exc()
                logger.exception("crawl failed for site=%s", site)
                try:
                    await session.rollback()
                    await RuntimeLogService(session).write(
                        level="ERROR",
                        category="exception",
                        message=f"{_SITE_LABELS.get(site, site)} 外部开奖同步失败：{exc}",
                        details={"site": site, "operation": "draw_sync"},
                        request_url=_DRAW_SOURCE_URLS.get(site),
                        duration_ms=round((time.perf_counter() - started) * 1000),
                        status_code=getattr(exc, "code", None),
                        exception_traceback=trace,
                        service_name="draw_crawler",
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    logger.exception("unable to write draw sync failure log for site=%s", site)

    async with session_factory() as session:
        await settle_new_draws(session)
        await expire_pending_orders(session)
        await expire_non_current_confirmed_orders(session, current_periods)
        order_ids = (await session.scalars(select(BetOrder.id).where(BetOrder.status == "confirmed"))).all()
        for order_id in order_ids:
            await process_confirmed_order(
                session,
                order_id=order_id,
                encryption_secret=settings.credential_encryption_secret,
                sender_factory=sender_factory,
                emit_runtime_log=False,
            )
        await write_group_bet_runtime_logs(session, order_ids)
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
            await _record_heartbeat(factory)
            await asyncio.sleep(poll_seconds)
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
