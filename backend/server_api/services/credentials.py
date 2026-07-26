from __future__ import annotations

import base64
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import WssCredential


def encryption_key_from_secret(secret: str) -> bytes:
    """Derive the Fernet key from an opaque deployment secret."""
    raw = secret.encode("utf-8")[:32].ljust(32, b"0")
    return base64.urlsafe_b64encode(raw)


def mask_accid(value: str) -> str:
    return f"***{value[-4:]}" if len(value) > 4 else "***"


def decrypt_user_sig(encrypted_user_sig: str, encryption_secret: str) -> str:
    cipher = Fernet(encryption_key_from_secret(encryption_secret))
    return cipher.decrypt(encrypted_user_sig.encode("ascii")).decode("utf-8")


async def save_credentials(
    session: AsyncSession, *, user_id: int, appid: str, accid: str, user_sig: str, encryption_secret: str
) -> WssCredential:
    cipher = Fernet(encryption_key_from_secret(encryption_secret))
    row = await session.scalar(select(WssCredential).where(WssCredential.user_id == user_id))
    encrypted = cipher.encrypt(user_sig.encode("utf-8")).decode("ascii")
    if row is None:
        row = WssCredential(user_id=user_id, appid=appid, accid=accid, encrypted_user_sig=encrypted)
        session.add(row)
    else:
        row.appid = appid
        row.accid = accid
        row.encrypted_user_sig = encrypted
        row.version += 1
        row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return row


async def get_credentials(session: AsyncSession, *, user_id: int) -> WssCredential | None:
    return await session.scalar(select(WssCredential).where(WssCredential.user_id == user_id))
