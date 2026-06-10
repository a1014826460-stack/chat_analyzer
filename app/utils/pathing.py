from __future__ import annotations
from pathlib import Path
import sys
from app.build_config import BUILD_ID, IS_ADMIN_VERSION

def app_dir() -> "Path":
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    
    return Path(__file__).resolve().parents[2]

def user_data_dir() -> "Path":
    if getattr(sys, "frozen", False):
        suffix = "user"
        build_part = ""
    else:
        suffix = "dev_user"
        build_part = ""
    base = Path.home() / f".chat_analyzer_{suffix}{build_part}"; base.mkdir(parents=True, exist_ok=True)
    return base

def resource_path(*parts: "str") -> "Path":
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base.joinpath(*parts)
