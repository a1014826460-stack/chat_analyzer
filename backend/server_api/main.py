from contextlib import asynccontextmanager
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import text

from server_api.api.routes.auth import router as auth_router
from server_api.api.routes.integrations import router as integrations_router
from server_api.api.routes.draws import router as draws_router
from server_api.api.routes.bets import router as bets_router
from server_api.api.routes.strategies import router as strategies_router
from server_api.api.routes.runtime_logs import router as runtime_logs_router
from server_api.api.routes.updates import router as updates_router
from server_api.api.routes.admin import router as admin_router
from server_api.db import create_engine, create_session_factory
from server_api.services.redis_state import InMemoryRedis
from server_api.settings import settings


def create_app(
    *,
    database_url: str | None = None,
    jwt_secret: str | None = None,
    admin_bootstrap_token: str | None = None,
    credential_encryption_secret: str | None = None,
    redis_url: str | None = None,
    redis_factory: Callable[[str], Redis] | None = None,
    initialize_schema: bool = False,
    auth_session_limit: int | None = None,
    auth_session_window_seconds: int | None = None,
    admin_cookie_secure: bool | None = None,
    admin_session_hours: int | None = None,
    license_public_key_pem: str | None = None,
    license_private_key_pem: str | None = None,
    update_release_dir: str | None = None,
    download_release_file: str | None = None,
) -> FastAPI:
    if database_url is None:
        database_url = settings.database_url
    if jwt_secret is None:
        jwt_secret = settings.jwt_secret
    if admin_bootstrap_token is None:
        admin_bootstrap_token = settings.admin_bootstrap_token
    if credential_encryption_secret is None:
        credential_encryption_secret = settings.credential_encryption_secret
    if redis_url is None:
        redis_url = settings.redis_url
    if auth_session_limit is None:
        auth_session_limit = settings.auth_session_limit
    if auth_session_window_seconds is None:
        auth_session_window_seconds = settings.auth_session_window_seconds
    if admin_cookie_secure is None:
        admin_cookie_secure = settings.admin_cookie_secure
    if admin_session_hours is None:
        admin_session_hours = settings.admin_session_hours
    if license_public_key_pem is None:
        license_public_key_pem = settings.license_public_key_pem
    if license_private_key_pem is None:
        license_private_key_pem = settings.license_private_key_pem
    if update_release_dir is None:
        update_release_dir = settings.update_release_dir
    if download_release_file is None:
        download_release_file = settings.download_release_file
    uses_default_redis_factory = redis_factory is None
    if redis_factory is None:
        redis_factory = Redis.from_url

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_engine(database_url)
        if initialize_schema:
            from server_api.db import create_schema

            await create_schema(engine)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.jwt_secret = jwt_secret
        app.state.admin_bootstrap_token = admin_bootstrap_token
        app.state.credential_encryption_secret = credential_encryption_secret
        # SQLite apps are isolated unit-test instances; production always uses Redis.
        app.state.redis = InMemoryRedis() if database_url.startswith("sqlite+") and uses_default_redis_factory else redis_factory(redis_url)
        app.state.auth_session_limit = auth_session_limit
        app.state.auth_session_window_seconds = auth_session_window_seconds
        app.state.admin_cookie_secure = admin_cookie_secure
        app.state.admin_session_hours = admin_session_hours
        app.state.license_public_key_pem = license_public_key_pem
        app.state.license_private_key_pem = license_private_key_pem
        app.state.update_release_dir = update_release_dir
        app.state.download_release_file = download_release_file
        yield
        close = getattr(app.state.redis, "aclose", None)
        if close is not None:
            await close()
        await engine.dispose()

    application = FastAPI(title="StarTrace Server API", version="0.1.0", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory="server_api/static"), name="static")

    @application.middleware("http")
    async def record_request_metrics(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            if hasattr(application.state, "redis") and hasattr(application.state.redis, "incr"):
                await application.state.redis.incr("metrics:api:errors")
            raise
        if hasattr(application.state, "redis") and hasattr(application.state.redis, "incr"):
            await application.state.redis.incr("metrics:api:requests")
            if response.status_code >= 500:
                await application.state.redis.incr("metrics:api:errors")
        return response
    application.include_router(admin_router)
    application.include_router(auth_router)
    application.include_router(integrations_router)
    application.include_router(draws_router)
    application.include_router(bets_router)
    application.include_router(strategies_router)
    application.include_router(runtime_logs_router)
    application.include_router(updates_router)

    @application.get("/download")
    async def public_download_page(request: Request):
        from pathlib import Path
        from fastapi.responses import HTMLResponse

        name = str(request.app.state.download_release_file or "")
        root = Path(str(request.app.state.update_release_dir or "")).resolve()
        candidate = (root / name).resolve()
        if not name or not root.is_dir() or root not in candidate.parents or not candidate.is_file():
            return HTMLResponse("<h1>StarTrace 下载</h1><p>当前暂无可下载的客户端。</p>", status_code=503)
        return HTMLResponse(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>StarTrace 下载</title><body style="font-family:Microsoft YaHei,Arial;background:#f3f6fb;color:#172033;padding:10vh 8vw"><main style="max-width:620px;background:#fff;border-radius:18px;padding:36px;box-shadow:0 8px 28px #253b5920"><h1>StarTrace 普通用户版</h1><p>下载并安装客户端后，在激活页面复制机器码，向管理员申请对应激活码。</p><p><a style="display:inline-block;background:#167f8a;color:#fff;text-decoration:none;padding:12px 20px;border-radius:10px" href="/download/{name}">下载 {name}</a></p></main></body></html>''')

    @application.get("/download/{file_name}")
    async def public_download_file(file_name: str, request: Request):
        from pathlib import Path
        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        if file_name != str(request.app.state.download_release_file or ""):
            raise HTTPException(status_code=404, detail="下载文件不存在")
        root = Path(str(request.app.state.update_release_dir or "")).resolve()
        candidate = (root / file_name).resolve()
        if not root.is_dir() or root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=404, detail="下载文件不存在")
        return FileResponse(candidate, filename=file_name, media_type="application/octet-stream")

    @application.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready")
    async def readiness() -> dict[str, str]:
        try:
            async with application.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            await application.state.redis.ping()
        except Exception as exc:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok"}

    return application


app = create_app()
