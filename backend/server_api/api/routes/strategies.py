from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session
from server_api.db import AutoBetStrategy
from server_api.dependencies import current_user_id
from server_api.services.runtime_logs import RuntimeLogService


router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(current_user_id)]


class AutoBetStrategyRequest(BaseModel):
    enabled: bool = False
    site: str = Field(default="pc28", min_length=1, max_length=32)
    target_groups: list[str] = Field(default_factory=list, max_length=100)
    target_group_names: dict[str, str] = Field(default_factory=dict, max_length=100)
    history_count: int = Field(default=50, ge=1, le=500)
    confidence_threshold: int = Field(default=45, ge=0, le=100)
    require_confirmation: bool = True
    bet_amount: float = Field(default=10, gt=0)
    strategy_type: str = Field(default="three_doors", pattern="^(three_doors|trend_following|flat|martingale)$")
    play_types: list[str] = Field(default_factory=list, max_length=8)
    observation_window: int = Field(default=10, ge=3, le=100)
    trigger_threshold: int = Field(default=3, ge=1, le=20)
    martingale_sequence: list[float] = Field(default_factory=list, max_length=20)


def serialize(row: AutoBetStrategy | None) -> dict[str, object]:
    if row is None:
        return AutoBetStrategyRequest().model_dump()
    return {
        "enabled": row.enabled,
        "site": row.site,
        "target_groups": json.loads(row.target_groups_json),
        "target_group_names": json.loads(row.target_group_names_json or "{}"),
        "history_count": row.history_count,
        "confidence_threshold": row.confidence_threshold,
        "require_confirmation": row.require_confirmation,
        "bet_amount": row.bet_amount,
        "strategy_type": row.strategy_type,
        "play_types": json.loads(row.play_types_json or "[]"),
        "observation_window": row.observation_window,
        "trigger_threshold": row.trigger_threshold,
        "martingale_sequence": json.loads(row.martingale_sequence_json or "[]"),
    }


@router.get("/v1/strategies/auto-bet")
async def get_auto_bet_strategy(session: Session, user_id: UserId):
    return serialize(await session.scalar(select(AutoBetStrategy).where(AutoBetStrategy.user_id == user_id)))


@router.put("/v1/strategies/auto-bet")
async def put_auto_bet_strategy(payload: AutoBetStrategyRequest, session: Session, user_id: UserId):
    row = await session.scalar(select(AutoBetStrategy).where(AutoBetStrategy.user_id == user_id))
    values = payload.model_dump()
    target_groups = values.pop("target_groups")
    target_group_names = values.pop("target_group_names")
    values["play_types_json"] = json.dumps(values.pop("play_types", []), ensure_ascii=False, separators=(",", ":"))
    values["martingale_sequence_json"] = json.dumps(values.pop("martingale_sequence", []), ensure_ascii=False, separators=(",", ":"))
    values["target_groups_json"] = json.dumps(target_groups, ensure_ascii=False, separators=(",", ":"))
    values["target_group_names_json"] = json.dumps(
        {str(group_id): str(target_group_names.get(str(group_id), group_id)).strip() for group_id in target_groups},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if row is None:
        row = AutoBetStrategy(user_id=user_id, **values)
        session.add(row)
        changed = True
    else:
        changed = any(getattr(row, key) != value for key, value in values.items())
        if changed:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.utcnow()
    if changed:
        await RuntimeLogService(session).write(
            user_id=user_id,
            level="INFO",
            category="user_action",
            message="自动下注策略已保存",
            details={"enabled": payload.enabled, "site": payload.site},
        )
    await session.commit()
    await session.refresh(row)
    return serialize(row)
