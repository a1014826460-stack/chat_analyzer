from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from server_api.dependencies import current_user_id


router = APIRouter()
UserId = Annotated[int, Depends(current_user_id)]
MAX_UPDATE_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024


def _release_file(request: Request, name: str) -> Path:
    root = Path(str(request.app.state.update_release_dir or "")).resolve()
    candidate = (root / name).resolve()
    if not root.is_dir() or root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="更新文件不存在")
    return candidate


def _load_manifest(request: Request) -> dict:
    path = _release_file(request, "latest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="更新清单不可用") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="更新清单格式无效")
    url = value.get("url")
    if not isinstance(url, str) or not Path(urlparse(url).path).name:
        raise HTTPException(status_code=503, detail="更新清单文件无效")
    size = value.get("size")
    sha256 = value.get("sha256")
    signature = value.get("signature")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 < size <= MAX_UPDATE_ARTIFACT_BYTES
        or not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None
        or not isinstance(signature, str)
        or not signature.strip()
    ):
        raise HTTPException(status_code=503, detail="更新清单校验信息无效")
    return value


@router.get("/v1/updates/manifest")
async def update_manifest(request: Request, _: UserId):
    return _load_manifest(request)


@router.get("/v1/updates/files/{file_name}")
async def update_file(file_name: str, request: Request, _: UserId):
    manifest_name = Path(urlparse(str(_load_manifest(request)["url"])).path).name
    if file_name != manifest_name:
        raise HTTPException(status_code=404, detail="更新文件不存在")
    return FileResponse(_release_file(request, file_name), filename=file_name, media_type="application/octet-stream")
