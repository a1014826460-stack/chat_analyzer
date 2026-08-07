"""Encrypted, administrator-managed AI configuration for server workers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import ServerAiConfiguration
from server_api.services.credentials import encryption_key_from_secret


@dataclass(frozen=True)
class AiConfiguration:
    provider: str
    base_url: str
    model: str
    api_key: str


def _cipher(encryption_secret: str) -> Fernet:
    return Fernet(encryption_key_from_secret(encryption_secret))


async def load_ai_configuration(session: AsyncSession, *, encryption_secret: str) -> AiConfiguration | None:
    row = await session.get(ServerAiConfiguration, 1)
    if row is None:
        return None
    try:
        api_key = _cipher(encryption_secret).decrypt(row.encrypted_api_key.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    return AiConfiguration(provider=row.provider, base_url=row.base_url, model=row.model, api_key=api_key)


async def save_ai_configuration(session: AsyncSession, *, encryption_secret: str, provider: str, base_url: str, model: str, api_key: str) -> ServerAiConfiguration:
    row = await session.get(ServerAiConfiguration, 1)
    if row is None:
        row = ServerAiConfiguration(id=1, provider=provider, base_url=base_url, model=model, encrypted_api_key="")
        session.add(row)
    row.provider = provider
    row.base_url = base_url.rstrip("/")
    row.model = model
    if api_key:
        row.encrypted_api_key = _cipher(encryption_secret).encrypt(api_key.encode("utf-8")).decode("ascii")
    row.updated_at = datetime.utcnow()
    await session.commit()
    return row
