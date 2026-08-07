from __future__ import annotations

from dataclasses import dataclass
import base64
import os


def _license_public_key() -> str:
    encoded = os.getenv("LICENSE_PUBLIC_KEY_PEM_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
    return os.getenv("LICENSE_PUBLIC_KEY_PEM", "")


def _license_private_key() -> str:
    encoded = os.getenv("LICENSE_PRIVATE_KEY_PEM_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
    return os.getenv("LICENSE_PRIVATE_KEY_PEM", "")


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
    admin_cookie_secure: bool = os.getenv("ADMIN_COOKIE_SECURE", "false").strip().lower() == "true"
    admin_session_hours: int = int(os.getenv("ADMIN_SESSION_HOURS", "24"))
    auth_session_limit: int = int(os.getenv("AUTH_SESSION_LIMIT", "10"))
    auth_session_window_seconds: int = int(os.getenv("AUTH_SESSION_WINDOW_SECONDS", "60"))
    license_public_key_pem: str = _license_public_key()
    license_private_key_pem: str = _license_private_key()
    ai_provider: str = os.getenv("AI_PROVIDER", "openai_compatible")
    ai_base_url: str = os.getenv("AI_BASE_URL", "")
    ai_model: str = os.getenv("AI_MODEL", "")
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "45"))
    ai_max_retries: int = int(os.getenv("AI_MAX_RETRIES", "2"))
    ai_retry_backoff_seconds: float = float(os.getenv("AI_RETRY_BACKOFF_SECONDS", "1"))
    ai_decision_enabled: bool = os.getenv("AI_DECISION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    update_release_dir: str = os.getenv("UPDATE_RELEASE_DIR", "")
    download_release_file: str = os.getenv("DOWNLOAD_RELEASE_FILE", "")


settings = Settings()
