"""Administrator-only setup, JSON APIs, and server-rendered console pages."""
from __future__ import annotations

import hashlib
import html
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.api.routes.auth import get_session
from server_api.db import ActivationCode, AdminUser, DeviceSession, RuntimeLogEvent
from server_api.services.admin_auth import AdminAuthService, AdminAuthorizationError
from server_api.services.admin_management import activation_token, create_codes, dashboard_metrics, list_admin_audit, list_orders, list_users
from server_api.services.auth import revoke_activation_code
from server_api.services.redis_state import allow_fixed_window
from server_api.services.ai_settings import load_ai_configuration, save_ai_configuration


router = APIRouter()
templates = Jinja2Templates(directory="server_api/templates")
Session = Annotated[AsyncSession, Depends(get_session)]
COOKIE_NAME = "startrace_admin"


class SetupRequest(BaseModel):
    bootstrap_token: str = Field(min_length=16, max_length=512)
    username: str = Field(default="admin", min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    captcha_id: str = Field(min_length=16, max_length=128)
    captcha_code: str = Field(min_length=4, max_length=8)


class CreateCodesRequest(BaseModel):
    machine_code: str | None = Field(default=None, min_length=8, max_length=512)
    activation_code: str | None = Field(default=None, min_length=1, max_length=512)
    expires_in_seconds: int | None = Field(default=None, ge=1, le=315360000)
    expires_in_days: int = Field(default=1, ge=1, le=3650)
    max_devices: int = Field(default=1, ge=1, le=1)


class ExtendCodeRequest(BaseModel):
    days: int = Field(default=1, ge=1, le=3650)


class AiSettingsRequest(BaseModel):
    provider: str = Field(default="openai_compatible", pattern="^openai_compatible$")
    base_url: str = Field(default="https://api.deepseek.com/v1", min_length=8, max_length=512)
    model: str = Field(default="deepseek-v4-flash", min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=2048)


def _service(request: Request, session: AsyncSession) -> AdminAuthService:
    return AdminAuthService(
        session, bootstrap_token=request.app.state.admin_bootstrap_token,
        encryption_secret=request.app.state.credential_encryption_secret,
        session_hours=request.app.state.admin_session_hours,
    )


async def current_admin(request: Request, session: Session) -> AdminUser:
    admin = await _service(request, session).current_admin(request.cookies.get(COOKIE_NAME))
    if admin is None:
        raise HTTPException(status_code=401, detail="管理员登录已失效")
    return admin


Admin = Annotated[AdminUser, Depends(current_admin)]


async def current_admin_or_legacy_bootstrap(
    request: Request, session: Session, x_admin_token: Annotated[str | None, Header()] = None,
) -> AdminUser | None:
    admin = await _service(request, session).current_admin(request.cookies.get(COOKIE_NAME))
    if admin is not None:
        return admin
    if not await _service(request, session).has_admin() and x_admin_token == request.app.state.admin_bootstrap_token:
        return None
    raise HTTPException(status_code=401, detail="管理员登录已失效")


def _set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token, max_age=request.app.state.admin_session_hours * 3600,
        httponly=True, samesite="lax", secure=request.app.state.admin_cookie_secure, path="/",
    )


def _captcha_code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))


def _captcha_svg(code: str) -> str:
    safe_code = html.escape(code)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="52" viewBox="0 0 160 52" role="img" aria-label="图形验证码">'
        '<rect width="160" height="52" rx="10" fill="#17233d"/>'
        '<path d="M8 38L48 12M54 43L104 8M110 43L151 15" stroke="#4c6fae" stroke-width="2" opacity=".55"/>'
        f'<text x="80" y="35" text-anchor="middle" font-family="Arial,sans-serif" font-size="26" font-weight="700" letter-spacing="5" fill="#e7f0ff">{safe_code}</text>'
        '</svg>'
    )


@router.get("/v1/admin/captcha")
async def captcha(request: Request):
    code = _captcha_code()
    captcha_id = secrets.token_urlsafe(24)
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    await request.app.state.redis.set(f"admin:captcha:{captcha_id}", digest, ex=300)
    return {"captcha_id": captcha_id, "image_svg": _captcha_svg(code)}


@router.post("/v1/admin/setup")
async def setup(payload: SetupRequest, request: Request, session: Session):
    try:
        await _service(request, session).setup_admin(payload.bootstrap_token, payload.username, payload.password)
    except AdminAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"username": payload.username.strip()}


@router.post("/v1/admin/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(payload: LoginRequest, request: Request, session: Session):
    allowed = await allow_fixed_window(request.app.state.redis, key=f"rate:admin:{payload.username}", limit=8, window_seconds=300)
    if not allowed:
        raise HTTPException(status_code=429, detail="管理员认证请求过于频繁")
    key = f"admin:captcha:{payload.captcha_id}"
    expected_digest = await request.app.state.redis.get(key)
    if isinstance(expected_digest, bytes):
        expected_digest = expected_digest.decode("ascii")
    supplied_digest = hashlib.sha256(payload.captcha_code.strip().upper().encode("utf-8")).hexdigest()
    if expected_digest is None or not secrets.compare_digest(expected_digest, supplied_digest):
        raise HTTPException(status_code=401, detail="图形验证码无效或已过期")
    await request.app.state.redis.delete(key)
    result = await _service(request, session).login(payload.username, payload.password)
    if result is None:
        raise HTTPException(status_code=401, detail="用户名或密码无效")
    _, token = result
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_cookie(response, request, token)
    return response


@router.post("/v1/admin/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: Session, _: Admin):
    await _service(request, session).logout(request.cookies.get(COOKIE_NAME))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/v1/admin/dashboard")
async def dashboard(request: Request, session: Session, _: Admin):
    return await dashboard_metrics(session, request.app.state.redis)


@router.post("/v1/admin/activation-codes", status_code=status.HTTP_201_CREATED)
async def create_activation_codes(payload: CreateCodesRequest, request: Request, session: Session, admin: Annotated[AdminUser | None, Depends(current_admin_or_legacy_bootstrap)]):
    if admin is None:
        if not payload.activation_code:
            raise HTTPException(status_code=401, detail="管理员登录已失效")
        from server_api.services.auth import create_activation_code
        row = await create_activation_code(session, activation_code=payload.activation_code, expires_in_seconds=payload.expires_in_seconds or payload.expires_in_days * 86400, max_devices=payload.max_devices)
        return {"expires_in_seconds": payload.expires_in_seconds or payload.expires_in_days * 86400, "max_devices": payload.max_devices, "activation_codes": [payload.activation_code], "items": [{"id": row.id, "expires_at": row.expires_at.isoformat()}]}
    try:
        created = await create_codes(session, admin=admin, machine_code=payload.machine_code or "", private_key_pem=request.app.state.license_private_key_pem, expires_in_days=payload.expires_in_days, max_devices=payload.max_devices)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    expires_seconds = payload.expires_in_days * 86400
    return {
        "expires_in_seconds": expires_seconds, "max_devices": 1,
        "activation_codes": [code for _, code in created],
        "items": [{"id": row.id, "expires_at": row.expires_at.isoformat()} for row, _ in created],
    }


@router.post("/v1/admin/activation-codes/{activation_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_code(activation_id: int, session: Session, admin: Annotated[AdminUser | None, Depends(current_admin_or_legacy_bootstrap)]):
    if not await revoke_activation_code(session, activation_id):
        raise HTTPException(status_code=404, detail="授权不存在")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/admin/activation-codes/{activation_id}/extend")
async def extend_code(activation_id: int, payload: ExtendCodeRequest, session: Session, admin: Admin):
    code = await session.get(ActivationCode, activation_id)
    if code is None:
        raise HTTPException(status_code=404, detail="授权不存在")
    base = max(code.expires_at, __import__("datetime").datetime.utcnow())
    code.expires_at = base + timedelta(days=payload.days)
    await session.commit()
    return {"id": code.id, "expires_at": code.expires_at.isoformat()}


@router.get("/v1/admin/users")
async def users(session: Session, _: Admin, keyword: str = ""):
    return {"items": await list_users(session, keyword=keyword)}


@router.delete("/v1/admin/users/{user_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(user_id: int, device_id: int, session: Session, _: Admin):
    device = await session.get(DeviceSession, device_id)
    if device is None or device.user_id != user_id:
        raise HTTPException(status_code=404, detail="设备不存在")
    device.revoked = True
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/admin/orders")
async def orders(session: Session, _: Admin, user_id: int | None = None):
    return {"items": await list_orders(session, user_id=user_id)}


@router.get("/v1/admin/runtime-logs")
async def runtime_logs(session: Session, _: Admin, user_id: int | None = None, limit: int = 100):
    statement = select(RuntimeLogEvent).order_by(RuntimeLogEvent.id.desc()).limit(min(max(limit, 1), 200))
    if user_id:
        statement = statement.where(RuntimeLogEvent.user_id == user_id)
    rows = (await session.scalars(statement)).all()
    return {"items": [{"id": row.id, "user_id": row.user_id, "level": row.level, "category": row.category, "message": row.message, "created_at": row.created_at.isoformat()} for row in rows]}


@router.get("/v1/admin/audit-events")
async def audit_events(session: Session, _: Admin):
    return {"items": await list_admin_audit(session)}


@router.get("/v1/admin/settings/ai")
async def get_ai_settings(request: Request, session: Session, _: Admin):
    config = await load_ai_configuration(session, encryption_secret=request.app.state.credential_encryption_secret)
    if config is None:
        return {"provider": "openai_compatible", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash", "api_key_configured": False}
    return {"provider": config.provider, "base_url": config.base_url, "model": config.model, "api_key_configured": bool(config.api_key)}


@router.put("/v1/admin/settings/ai")
async def put_ai_settings(payload: AiSettingsRequest, request: Request, session: Session, admin: Admin):
    existing = await load_ai_configuration(session, encryption_secret=request.app.state.credential_encryption_secret)
    if not payload.api_key and existing is None:
        raise HTTPException(status_code=422, detail="请填写 AI Token")
    row = await save_ai_configuration(session, encryption_secret=request.app.state.credential_encryption_secret, provider=payload.provider, base_url=payload.base_url, model=payload.model, api_key=payload.api_key)
    await _service(request, session).audit(admin_id=admin.id, action="ai_settings_saved", resource_type="server_ai_configuration", resource_id=str(row.id))
    await session.commit()
    return {"provider": row.provider, "base_url": row.base_url, "model": row.model, "api_key_configured": True}


@router.post("/v1/admin/settings/ai/test")
async def test_ai_settings(payload: AiSettingsRequest, request: Request, session: Session, _: Admin):
    existing = await load_ai_configuration(session, encryption_secret=request.app.state.credential_encryption_secret)
    api_key = payload.api_key or (existing.api_key if existing is not None else "")
    if not api_key:
        raise HTTPException(status_code=422, detail="请先填写或保存 AI Token")
    from server_api.services.ai_client import SharedAiClient, SharedAiClientError
    client = SharedAiClient(provider=payload.provider, base_url=payload.base_url, model=payload.model, api_key=api_key)
    try:
        result = await __import__("asyncio").to_thread(client.recommend_three_doors, site="pc28", history=[], selected_plays=["小单", "大双", "小双"])
    except SharedAiClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": "AI 连接成功", "decision": result}


async def _page_admin(request: Request, session: AsyncSession) -> AdminUser | None:
    return await _service(request, session).current_admin(request.cookies.get(COOKIE_NAME))


@router.get("/admin/setup", response_class=HTMLResponse)
async def setup_page(request: Request, session: Session):
    if await _service(request, session).has_admin():
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request, "admin/setup.html", {"default_username": "admin"})


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", {})


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/{page}", response_class=HTMLResponse)
async def page(page: str = "dashboard", request: Request = None, session: Session = None):
    admin = await _page_admin(request, session)
    if admin is None:
        return RedirectResponse("/admin/login", status_code=303)
    template = {"dashboard": "dashboard.html", "users": "users.html", "codes": "codes.html", "operations": "operations.html", "logs": "operations.html", "settings": "settings.html"}.get(page)
    if template is None:
        raise HTTPException(status_code=404, detail="页面不存在")
    return templates.TemplateResponse(request, f"admin/{template}", {"admin": admin, "page": page})
