from __future__ import annotations

import jwt
from fastapi import HTTPException, Request, status

from server_api.services.redis_state import is_token_revoked


async def require_active_token(request: Request, token: str) -> dict[str, object]:
    try:
        payload = jwt.decode(token, request.app.state.jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌无效") from exc
    if await is_token_revoked(request.app.state.redis, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌已注销")
    return payload
