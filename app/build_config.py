from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "StarTrace"
APP_VERSION = os.getenv("STARTRACE_VERSION", "1.97.0")
BUILD_ID = os.getenv("STARTRACE_BUILD_ID", "startrace_202606180001")

IS_ADMIN_VERSION = False
IS_PRODUCTION = True

CDN_BASE_URL = os.getenv("STARTRACE_CDN_BASE_URL", "").rstrip("/")

# __BUILD_INJECT_LICENSE_PUBLIC_KEY__ — replaced by tools/build.py during packaging
_BUILD_PUBLIC_KEY = ""
_BUILD_PRIVATE_KEY = ""


def _development_key(name: str) -> str:
    """Load local signing keys for source-only development and admin use."""
    if getattr(sys, "frozen", False):
        return ""
    path = Path(__file__).resolve().parents[1] / "keys" / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_epl = os.getenv("STARTRACE_LICENSE_PUBLIC_KEY_PEM", "").strip()
LICENSE_PUBLIC_KEY_PEM = _epl or _BUILD_PUBLIC_KEY.strip() or _development_key("license_public.pem")
_epp = os.getenv("STARTRACE_LICENSE_PRIVATE_KEY_PEM", "").strip()
LICENSE_PRIVATE_KEY_PEM = _epp or _BUILD_PRIVATE_KEY.strip() or _development_key("license_private.pem")
UPDATE_PUBLIC_KEY_PEM = os.getenv("STARTRACE_UPDATE_PUBLIC_KEY_PEM", "").strip()
UPDATE_PRIVATE_KEY_PEM = os.getenv("STARTRACE_UPDATE_PRIVATE_KEY_PEM", "").strip()


def edition_name() -> str:
    return "admin" if IS_ADMIN_VERSION else "user"


def artifact_name() -> str:
    suffix = "-Admin" if IS_ADMIN_VERSION else ""
    return f"{APP_NAME}{suffix}-{APP_VERSION}"


def update_manifest_url() -> str:
    if not CDN_BASE_URL:
        return ""
    return f"{CDN_BASE_URL}/{APP_NAME.lower()}/{edition_name()}/latest.json"
