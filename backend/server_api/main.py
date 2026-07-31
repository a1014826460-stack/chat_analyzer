from contextlib import asynccontextmanager
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from server_api.api.routes.auth import router as auth_router
from server_api.api.routes.integrations import router as integrations_router
from server_api.api.routes.draws import router as draws_router
from server_api.api.routes.bets import router as bets_router
from server_api.api.routes.strategies import router as strategies_router
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
    license_public_key_pem: str | None = None,
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
    if license_public_key_pem is None:
        license_public_key_pem = settings.license_public_key_pem
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
        app.state.license_public_key_pem = license_public_key_pem
        yield
        close = getattr(app.state.redis, "aclose", None)
        if close is not None:
            await close()
        await engine.dispose()

    application = FastAPI(title="StarTrace Server API", version="0.1.0", lifespan=lifespan)
    application.include_router(auth_router)
    application.include_router(integrations_router)
    application.include_router(draws_router)
    application.include_router(bets_router)
    application.include_router(strategies_router)

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
