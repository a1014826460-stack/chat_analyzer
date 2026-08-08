from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import AutoBetStrategy, BetOrder, StrategyEvent
from server_api.services.draws import analyze, history
from server_api.services.runtime_logs import RuntimeLogService, format_strategy_context


_DECISION_EVENT_TYPES = {"frequency_skip", "ai_error", "ai_skip", "ai_execute"}


def _trend_following_plays(site: str, rows, window: int, threshold: int) -> list[str] | None:
    """Return the reverse play when the latest run of same size reaches threshold."""
    ordered = list(rows)[-max(1, window):]
    if not ordered:
        return None
    tail_base = "大" if str(ordered[-1].result).startswith("大") else "小"
    consecutive = 0
    for row in reversed(ordered):
        base = "大" if str(row.result).startswith("大") else "小"
        if base == tail_base:
            consecutive += 1
        else:
            break
    if consecutive < max(1, threshold):
        return None
    return ["小"] if tail_base == "大" else ["大"]


def _martingale_amount(sequence: list[float], consecutive_losses: int, default: float) -> float:
    steps = [float(value) for value in sequence if float(value) > 0] or [float(default)]
    return steps[min(max(consecutive_losses, 0), len(steps) - 1)]


async def _consecutive_losses(session, *, user_id: int, site: str, play_type: str, limit: int = 10) -> int:
    rows = (await session.scalars(
        select(BetOrder).where(
            BetOrder.user_id == user_id,
            BetOrder.site == site,
            BetOrder.play_type == play_type,
        ).order_by(BetOrder.id.desc()).limit(limit)
    )).all()
    count = 0
    for row in rows:
        if row.result == "lose":
            count += 1
        else:
            break
    return count


async def _add_decision_event_once(
    session: AsyncSession,
    *,
    user_id: int,
    site: str,
    period: str,
    event_type: str,
    message: str,
    group_names: list[str] | None = None,
) -> bool:
    if event_type in _DECISION_EVENT_TYPES:
        existing = await session.scalar(select(StrategyEvent.id).where(
            StrategyEvent.user_id == user_id,
            StrategyEvent.site == site,
            StrategyEvent.period == period,
            StrategyEvent.event_type == event_type,
        ))
        if existing is not None:
            return False
    contextual_message = f"{format_strategy_context(group_names=group_names, site=site, period=period)}{message}"
    session.add(StrategyEvent(
        user_id=user_id, site=site, period=period, event_type=event_type, message=contextual_message
    ))
    await RuntimeLogService(session).write(
        user_id=user_id,
        level="ERROR" if event_type == "ai_error" else "INFO",
        category="strategy",
        message=contextual_message,
        details={"site": site, "period": period, "event_type": event_type, "group_names": group_names or []},
        service_name="strategy_scheduler",
    )
    return True




async def _has_decision_event(session: AsyncSession, *, user_id: int, site: str, period: str) -> bool:
    existing = await session.scalar(select(StrategyEvent.id).where(
        StrategyEvent.user_id == user_id,
        StrategyEvent.site == site,
        StrategyEvent.period == period,
        StrategyEvent.event_type.in_(_DECISION_EVENT_TYPES),
    ))
    return existing is not None

async def schedule_frequency_orders(
    session: AsyncSession,
    *,
    site: str,
    period: str,
    betting_deadline_at: datetime | None = None,
    ai_client=None,
) -> int:
    strategies = (await session.scalars(
        select(AutoBetStrategy).where(AutoBetStrategy.enabled.is_(True), AutoBetStrategy.site == site)
    )).all()
    created = 0
    for strategy in strategies:
        if await _has_decision_event(session, user_id=strategy.user_id, site=site, period=period):
            continue
        group_name_map = json.loads(strategy.target_group_names_json or "{}")
        group_names = [
            str(group_name_map.get(str(group_id), "未命名群组")).strip() or "未命名群组"
            for group_id in json.loads(strategy.target_groups_json)
        ]
        rows = await history(session, site, strategy.history_count)
        plays: list[str] = []
        reason: str = ""
        if strategy.strategy_type == "three_doors":
            analysis = analyze(site, rows, strategy.history_count, strategy.confidence_threshold)
            if not analysis["should_bet"]:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="frequency_skip",
                    message=(
                        f"频率未达阈值：三门 {','.join(analysis['selected_plays'])}，"
                        f"最高 {analysis['highest_selected_probability']:.1f}% < 阈值 {strategy.confidence_threshold}%"
                    ),
                    group_names=group_names,
                )
                continue
            plays = list(analysis["selected_plays"])
            reason = (
                f"排除{analysis['excluded_play']}；压{'、'.join(plays)}，"
                f"最高{analysis['highest_selected_probability']:.1f}%"
            )
        elif strategy.strategy_type == "trend_following":
            trend_plays = _trend_following_plays(site, rows, strategy.observation_window, strategy.trigger_threshold)
            if trend_plays is None:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="frequency_skip",
                    message=(
                        f"趋势未触发：观察 {strategy.observation_window} 期，"
                        f"连续 {strategy.trigger_threshold} 期同结果才反向下注"
                    ),
                    group_names=group_names,
                )
                continue
            plays = trend_plays
            reason = f"连续 {strategy.trigger_threshold} 期同向，反向押 {'、'.join(plays)}"
        else:  # flat / martingale
            plays = [str(play).strip() for play in json.loads(strategy.play_types_json or "[]") if str(play).strip()]
            if not plays:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="frequency_skip",
                    message="未配置押注玩法（play_types 为空）",
                    group_names=group_names,
                )
                continue
            reason = f"策略 {strategy.strategy_type}：押 {'、'.join(plays)}"
        plays = list(dict.fromkeys(plays))

        if ai_client is not None and strategy.strategy_type == "three_doors":
            try:
                decision = ai_client.recommend_three_doors(
                    site=site,
                    history=[{"period": row.period, "result": row.result, "total": row.total}
                             for row in await history(session, site, strategy.history_count)],
                    selected_plays=plays,
                )
            except Exception as exc:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="ai_error",
                    message=f"频率通过：三门 {','.join(plays)}；AI 请求失败，跳过本期：{exc}",
                    group_names=group_names,
                )
                continue
            confidence = int(decision["confidence"])
            reason = str(decision["reason"])
            if decision["action"] != "execute" or confidence < strategy.confidence_threshold:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="ai_skip",
                    message=(f"频率通过：三门 {','.join(plays)}；AI 跳过（置信度 {confidence}/100）：{reason}"),
                    group_names=group_names,
                )
                continue
            await _add_decision_event_once(
                session,
                user_id=strategy.user_id,
                site=site,
                period=period,
                event_type="ai_execute",
                message=f"频率通过：三门 {','.join(plays)}；AI 执行（置信度 {confidence}/100）：{reason}",
                group_names=group_names,
            )
        else:
            # 纯算法模式或非三门策略：频率/条件满足即下注，不依赖 AI。
            await _add_decision_event_once(
                session,
                user_id=strategy.user_id,
                site=site,
                period=period,
                event_type="ai_execute",
                message=(
                    f"频率达标：{reason}；算法决策下注（{strategy.strategy_type}）"
                ),
                group_names=group_names,
            )
        for group_id in json.loads(strategy.target_groups_json):
            for play_type in plays:
                exists = await session.scalar(select(BetOrder.id).where(
                    BetOrder.user_id == strategy.user_id,
                    BetOrder.site == site,
                    BetOrder.period == period,
                    BetOrder.group_id == group_id,
                    BetOrder.play_type == play_type,
                ))
                if exists is not None:
                    continue
                deadline = datetime.utcnow() + timedelta(seconds=30) if strategy.require_confirmation else None
                session.add(BetOrder(
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    group_id=group_id,
                    group_name=str(group_name_map.get(str(group_id), "未命名群组")).strip() or "未命名群组",
                    play_type=play_type,
                    amount=strategy.bet_amount,
                    status="pending_confirmation" if strategy.require_confirmation else "confirmed",
                    confirmation_deadline_at=deadline,
                    betting_deadline_at=betting_deadline_at,
                ))
                created += 1
    await session.commit()
    return created
