from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.services.auth import AuthorizationError, create_activation_code, issue_access_token, open_local_license_session, open_session, revoke_activation_code
from server_api.dependencies import bearer
from server_api.services.auth_guard import require_active_token
from server_api.services.redis_state import allow_fixed_window, revoke_token


router = APIRouter()


class ActivationCodeRequest(BaseModel):
    activation_code: str = Field(min_length=1, max_length=512)
    expires_in_seconds: int
    max_devices: int = Field(default=1, ge=1, le=100)


class SessionRequest(BaseModel):
    machine_code: str = Field(min_length=8, max_length=512)
    license_token: str | None = Field(default=None, min_length=1, max_length=8192)
    activation_code: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def require_credential(self):
        if not self.license_token and not self.activation_code:
            raise ValueError("缺少本地授权证明")
        return self


async def get_session(request: Request):
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if x_admin_token != request.app.state.admin_bootstrap_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员令牌无效")


@router.post("/v1/admin/activation-codes", status_code=status.HTTP_201_CREATED)
async def create_code(payload: ActivationCodeRequest, request: Request, session: Session, _: None = Depends(require_admin)):
    try:
        code = await create_activation_code(session, **payload.model_dump())
    except AuthorizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": code.id, "expires_at": code.expires_at.isoformat(), "max_devices": code.max_devices}


@router.post("/v1/admin/activation-codes/{activation_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_code(activation_id: int, session: Session, _: None = Depends(require_admin)) -> Response:
    if not await revoke_activation_code(session, activation_id):
        raise HTTPException(status_code=404, detail="授权不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/auth/session")
async def create_session(payload: SessionRequest, request: Request, session: Session):
    allowed = await allow_fixed_window(
        request.app.state.redis,
        key=f"rate:auth:machine:{payload.machine_code}",
        limit=request.app.state.auth_session_limit,
        window_seconds=request.app.state.auth_session_window_seconds,
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="认证请求过于频繁")
    try:
        if payload.license_token:
            user, device, authorization = await open_local_license_session(
                session,
                machine_code=payload.machine_code,
                license_token=payload.license_token,
                public_key_pem=request.app.state.license_public_key_pem,
            )
        elif request.app.state.allow_legacy_test_activation and payload.activation_code:
            user, device = await open_session(session, machine_code=payload.machine_code, activation_code=payload.activation_code)
            authorization = await session.get(__import__("server_api.db", fromlist=["ActivationCode"]).ActivationCode, user.activation_id)
        else:
            raise AuthorizationError("仅接受本地签名授权证明")
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    token = issue_access_token(user_id=user.id, device_id=device.id, jwt_secret=request.app.state.jwt_secret)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id, "device_id": device.id, "authorization_id": authorization.id}


@router.delete("/v1/auth/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Response:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少访问令牌")
    payload = await require_active_token(request, credentials.credentials)
    await revoke_token(request.app.state.redis, credentials.credentials, int(payload["exp"]))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
