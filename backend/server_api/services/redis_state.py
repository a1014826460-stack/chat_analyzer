from __future__ import annotations

import hashlib
from time import time


def token_key(token: str) -> str:
    return f"auth:revoked:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"


async def revoke_token(redis: object, token: str, expires_at: int) -> None:
    ttl = max(1, expires_at - int(time()))
    await redis.set(token_key(token), "1", ex=ttl)


async def is_token_revoked(redis: object, token: str) -> bool:
    return bool(await redis.exists(token_key(token)))


async def allow_fixed_window(
    redis: object, *, key: str, limit: int, window_seconds: int
) -> bool:
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return int(count) <= limit


async def acquire_lock(redis: object, key: str, ttl_seconds: int = 60) -> bool:
    return bool(await redis.set(f"lock:{key}", "1", ex=ttl_seconds, nx=True))


async def release_lock(redis: object, key: str) -> None:
    await redis.delete(f"lock:{key}")


class InMemoryRedis:
    """Minimal async Redis substitute used only by isolated SQLite tests."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float | None]] = {}

    def _get(self, key: str) -> tuple[str, float | None] | None:
        value = self._values.get(key)
        if value is not None and value[1] is not None and value[1] <= time():
            self._values.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and self._get(key) is not None:
            return False
        self._values[key] = (value, time() + ex if ex else None)
        return True

    async def exists(self, key: str) -> int:
        return int(self._get(key) is not None)

    async def get(self, key: str) -> str | None:
        value = self._get(key)
        return value[0] if value is not None else None

    async def incr(self, key: str) -> int:
        value = self._get(key)
        count = int(value[0]) + 1 if value is not None else 1
        expiry = value[1] if value is not None else None
        self._values[key] = (str(count), expiry)
        return count

    async def expire(self, key: str, seconds: int) -> bool:
        value = self._get(key)
        if value is None:
            return False
        self._values[key] = (value[0], time() + seconds)
        return True

    async def delete(self, key: str) -> int:
        return int(self._values.pop(key, None) is not None)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
