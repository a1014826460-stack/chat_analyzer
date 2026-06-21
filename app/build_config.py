from __future__ import annotations

import os


APP_NAME = "StarTrace"
APP_VERSION = os.getenv("STARTRACE_VERSION", "1.97.0")
BUILD_ID = os.getenv("STARTRACE_BUILD_ID", "startrace_202606180001")

IS_ADMIN_VERSION = False
IS_PRODUCTION = True

CDN_BASE_URL = os.getenv("STARTRACE_CDN_BASE_URL", "").rstrip("/")

# __BUILD_INJECT_LICENSE_PUBLIC_KEY__ — replaced by tools/build.py during packaging
_BUILD_PUBLIC_KEY = ""
_BUILD_PRIVATE_KEY = ""

_epl = os.getenv("STARTRACE_LICENSE_PUBLIC_KEY_PEM", "").strip()
LICENSE_PUBLIC_KEY_PEM = _epl if _epl else _BUILD_PUBLIC_KEY.strip()
_epp = os.getenv("STARTRACE_LICENSE_PRIVATE_KEY_PEM", "").strip()
LICENSE_PRIVATE_KEY_PEM = _epp if _epp else _BUILD_PRIVATE_KEY.strip()
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
