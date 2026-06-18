from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import build_config

APP_ENTRY = ROOT / "app" / "main.py"
ASSETS_DIR = ROOT / "assets"
ICON_PATH = ASSETS_DIR / "favicon.ico"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the StarTrace desktop application.")
    parser.add_argument("--admin", action="store_true", help="Build the admin edition.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous PyInstaller work directories before building.",
    )
    return parser.parse_args()


def _runtime_hook(admin: bool) -> Path:
    return ROOT / "tools" / ("runtime_hook_admin.py" if admin else "runtime_hook_user.py")


def _build_name(admin: bool) -> str:
    original_admin = build_config.IS_ADMIN_VERSION
    try:
        build_config.IS_ADMIN_VERSION = admin
        return build_config.artifact_name()
    finally:
        build_config.IS_ADMIN_VERSION = original_admin


def _build_command(admin: bool, clean: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--name",
        _build_name(admin),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ASSETS_DIR};assets",
        "--runtime-hook",
        str(_runtime_hook(admin)),
    ]
    if clean:
        command.append("--clean")
    if ICON_PATH.exists():
        command.extend(["--icon", str(ICON_PATH)])
    command.append(str(APP_ENTRY))
    return command


def main() -> int:
    args = _parse_args()
    command = _build_command(admin=args.admin, clean=args.clean)
    print("Running:", " ".join(command))
    completed = subprocess.run(command, cwd=ROOT)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
