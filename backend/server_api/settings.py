from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://startrace:startrace@postgres:5432/startrace"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    jwt_secret: str = os.getenv("JWT_SECRET", "development-only-change-me")
    credential_encryption_secret: str = os.getenv(
        "CREDENTIAL_ENCRYPTION_KEY", "development-credential-encryption-secret"
    )
    admin_bootstrap_token: str = os.getenv("ADMIN_BOOTSTRAP_TOKEN", "development-admin-token")
    auth_session_limit: int = int(os.getenv("AUTH_SESSION_LIMIT", "10"))
    auth_session_window_seconds: int = int(os.getenv("AUTH_SESSION_WINDOW_SECONDS", "60"))
    license_public_key_pem: str = os.getenv("LICENSE_PUBLIC_KEY_PEM", "")
    ai_provider: str = os.getenv("AI_PROVIDER", "openai_compatible")
    ai_base_url: str = os.getenv("AI_BASE_URL", "")
    ai_model: str = os.getenv("AI_MODEL", "")
    ai_api_key: str = os.getenv("AI_API_KEY", "")


settings = Settings()
