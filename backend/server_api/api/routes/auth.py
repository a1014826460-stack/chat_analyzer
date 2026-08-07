from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.services.auth import AuthorizationError, issue_access_token, open_local_license_session
from server_api.dependencies import bearer
from server_api.services.auth_guard import require_active_token
from server_api.services.redis_state import allow_fixed_window, revoke_token
from server_api.services.runtime_logs import RuntimeLogService


router = APIRouter()


class SessionRequest(BaseModel):
    machine_code: str = Field(min_length=8, max_length=512)
    license_token: str = Field(min_length=1, max_length=8192)


async def get_session(request: Request):
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if x_admin_token != request.app.state.admin_bootstrap_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员令牌无效")


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
        user, device, authorization = await open_local_license_session(
            session,
            machine_code=payload.machine_code,
            license_token=payload.license_token,
            public_key_pem=request.app.state.license_public_key_pem,
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    token = issue_access_token(user_id=user.id, device_id=device.id, jwt_secret=request.app.state.jwt_secret)
    await RuntimeLogService(session).write(
        user_id=user.id,
        level="INFO",
        category="user_action",
        message="用户登录成功",
        details={"device_id": device.id},
        service_name="api",
    )
    await session.commit()
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
