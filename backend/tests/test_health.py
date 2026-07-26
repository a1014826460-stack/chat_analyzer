from fastapi.testclient import TestClient
from sqlalchemy import inspect

from server_api.db import create_engine
import server_api.main as main_module
from server_api.main import app, create_app
from server_api.settings import Settings


def test_liveness_endpoint_returns_ok():
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database_and_redis_dependencies(tmp_path):
    class HealthyRedis:
        async def ping(self) -> bool:
            return True

    application = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        redis_factory=lambda _: HealthyRedis(),
    )

    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_service_unavailable_when_redis_is_down(tmp_path):
    class UnavailableRedis:
        async def ping(self) -> bool:
            raise ConnectionError("redis unavailable")

    application = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        redis_factory=lambda _: UnavailableRedis(),
    )

    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_startup_does_not_create_or_modify_database_schema(tmp_path):
    database = tmp_path / "server.db"
    application = create_app(
        database_url=f"sqlite+aiosqlite:///{database}",
        redis_factory=lambda _: object(),
    )

    with TestClient(application):
        pass

    assert not database.exists()


def test_alembic_upgrade_creates_the_full_schema(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    database = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    config = Config("alembic.ini")
    command.upgrade(config, "head")

    async def table_names() -> set[str]:
        engine = create_engine(f"sqlite+aiosqlite:///{database}")
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        await engine.dispose()
        return names

    import asyncio

    assert asyncio.run(table_names()) >= {"activation_codes", "users", "bet_orders", "alembic_version"}


def test_default_app_configuration_reads_the_admin_token_from_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
            admin_bootstrap_token="configured-admin-token",
        ),
    )
    application = main_module.create_app(initialize_schema=True)

    with TestClient(application) as client:
        response = client.post(
            "/v1/admin/activation-codes",
            headers={"X-Admin-Token": "configured-admin-token"},
            json={"activation_code": "CONFIGURED-CODE", "expires_in_seconds": 60},
        )

    assert response.status_code == 201
