from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import BetOrder, DrawResult, StrategyEvent

DEFAULT_ODDS: dict[str, float] = {
    "大": 1.98,
    "小": 1.98,
    "单": 1.98,
    "双": 1.98,
    "小单": 3.68,
    "大双": 3.68,
    "小双": 4.28,
    "大单": 4.28,
}

_DECISION_RE = re.compile(r"三门\s+([^；;，,]+(?:[,，][^；;，,]+){0,3})")


async def betting_statistics(
    session: AsyncSession, *, user_id: int, site: str, ai_window: int = 20, since=None
) -> dict[str, Any]:
    order_conditions = [BetOrder.user_id == user_id, BetOrder.site == site]
    if since is not None:
        order_conditions.append(BetOrder.created_at >= since)
    orders = (await session.scalars(
        select(BetOrder).where(*order_conditions).order_by(BetOrder.period, BetOrder.id)
    )).all()
    periods = {order.period for order in orders if order.status in {"sent", "confirmed", "sending"}}
    results = {
        row.period: row.result
        for row in (await session.scalars(select(DrawResult).where(DrawResult.site == site, DrawResult.period.in_(periods)))).all()
    } if periods else {}
    runtime = _runtime_state(orders, results)
    event_conditions = [
        StrategyEvent.user_id == user_id,
        StrategyEvent.site == site,
        StrategyEvent.event_type == "ai_execute",
    ]
    if since is not None:
        event_conditions.append(StrategyEvent.created_at >= since)
    events = (await session.scalars(
        select(StrategyEvent).where(*event_conditions).order_by(StrategyEvent.period, StrategyEvent.id)
    )).all()
    ai_statistics = _ai_statistics(events, results, max(1, int(ai_window)))
    return {"runtime_state": runtime, "ai_statistics": ai_statistics}


def _runtime_state(orders: list[BetOrder], results: dict[str, str]) -> dict[str, Any]:
    settled_by_period: dict[str, list[BetOrder]] = defaultdict(list)
    pending_staked = 0.0
    for order in orders:
        if order.status not in {"sent", "confirmed", "sending"}:
            continue
        if order.period in results:
            settled_by_period[order.period].append(order)
        else:
            pending_staked += float(order.amount)

    total_staked = total_payout = total_profit = 0.0
    total_rounds = win_rounds = lose_rounds = 0
    consecutive_wins = consecutive_losses = 0
    max_consecutive_wins = max_consecutive_losses = 0
    for period in sorted(settled_by_period, key=_period_sort_key):
        bets = settled_by_period[period]
        result = results[period]
        staked = sum(float(order.amount) for order in bets)
        payout = sum(float(order.amount) * DEFAULT_ODDS.get(order.play_type, 1.0) for order in bets if _bet_wins(order.play_type, result))
        profit = payout - staked
        total_staked += staked
        total_payout += payout
        total_profit += profit
        total_rounds += 1
        if profit > 0:
            win_rounds += 1
            consecutive_wins += 1
            consecutive_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
        else:
            lose_rounds += 1
            consecutive_losses += 1
            consecutive_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

    return {
        "current_step": 0,
        "pending_staked": pending_staked,
        "total_staked": total_staked,
        "total_payout": total_payout,
        "total_profit": total_profit,
        "total_rounds": total_rounds,
        "win_rounds": win_rounds,
        "lose_rounds": lose_rounds,
        "consecutive_wins": consecutive_wins,
        "consecutive_losses": consecutive_losses,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
        "martingale_peak_step": 0,
        "martingale_peak_amount": 0.0,
        "martingale_peak_site": "",
        "martingale_peak_period": "",
        "martingale_peak_at": None,
        "halted": False,
        "halt_reason": "",
    }


def _ai_statistics(events: list[StrategyEvent], results: dict[str, str], window: int) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    for event in events:
        if event.period in seen_periods or event.period not in results:
            continue
        seen_periods.add(event.period)
        plays = _plays_from_ai_execute_message(event.message)
        actual = results[event.period]
        direction_hit = any(_bet_wins(play, actual) for play in plays)
        exact_hit = actual in plays
        records.append({"direction_hit": direction_hit, "exact_hit": exact_hit})
    short = records[-window:]
    return {
        "settled_count": len(records),
        "overall": _accuracy(records),
        "short": {"window": window, **_accuracy(short)},
        "streak": _streak(records),
    }


def _plays_from_ai_execute_message(message: str) -> list[str]:
    match = _DECISION_RE.search(str(message or ""))
    if not match:
        return []
    return [part.strip() for part in re.split(r"[,，]", match.group(1)) if part.strip()]


def _accuracy(records: list[dict[str, Any]]) -> dict[str, int | float]:
    count = len(records)
    direction_hits = sum(item["direction_hit"] is True for item in records)
    exact_hits = sum(item["exact_hit"] is True for item in records)
    return {
        "count": count,
        "direction_hits": direction_hits,
        "exact_hits": exact_hits,
        "direction_accuracy": direction_hits / count if count else 0.0,
        "exact_accuracy": exact_hits / count if count else 0.0,
    }


def _streak(records: list[dict[str, Any]]) -> dict[str, str | int]:
    if not records:
        return {"result": "", "count": 0}
    latest_hit = records[-1]["direction_hit"] is True
    count = 0
    for item in reversed(records):
        if (item["direction_hit"] is True) != latest_hit:
            break
        count += 1
    return {"result": "hit" if latest_hit else "miss", "count": count}


def _bet_wins(play_type: str, result: str) -> bool:
    play = str(play_type or "")
    actual = str(result or "")
    return bool(play and actual and (play == actual if len(play) > 1 else play in actual))


def _period_sort_key(period: str) -> tuple[int, int | str]:
    text = str(period or "")
    return (1, int(text)) if text.isdigit() else (0, text)
