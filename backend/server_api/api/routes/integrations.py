from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session
from server_api.dependencies import current_user_id
from server_api.services.credentials import get_credentials, mask_accid, save_credentials


router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(current_user_id)]


class WssCredentialsRequest(BaseModel):
    appid: str = Field(min_length=1, max_length=255)
    accid: str = Field(min_length=1, max_length=255)
    user_sig: str = Field(min_length=1, max_length=4096)

    @field_validator("appid")
    @classmethod
    def appid_must_be_numeric_sdk_appid(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized.isdigit():
            raise ValueError("WSS IM SDK AppID 必须为数字，请同步 imAppid 而不是业务 appid")
        return normalized


def response_payload(row) -> dict[str, object]:
    return {"appid": row.appid, "accid_masked": mask_accid(row.accid), "version": row.version, "updated_at": row.updated_at.isoformat()}


@router.put("/v1/integrations/wss-credentials")
async def put_wss_credentials(payload: WssCredentialsRequest, request: Request, session: Session, user_id: UserId):
    row = await save_credentials(session, user_id=user_id, encryption_secret=request.app.state.credential_encryption_secret, **payload.model_dump())
    return response_payload(row)


@router.get("/v1/integrations/wss-credentials")
async def read_wss_credentials(session: Session, user_id: UserId):
    row = await get_credentials(session, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未配置 WSS 凭据")
    return response_payload(row)
