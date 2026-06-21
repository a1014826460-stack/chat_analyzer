from __future__ import annotations

import argparse
import os
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
    # Ensure the auto-generated embedded-keys module is included.
    embedded_keys = ROOT / "app" / "_embedded_keys.py"
    if embedded_keys.exists():
        command.extend(["--hidden-import", "app._embedded_keys"])
    if ICON_PATH.exists():
        command.extend(["--icon", str(ICON_PATH)])
    command.append(str(APP_ENTRY))
    return command


def _ensure_license_keys() -> None:
    """Read license key files and inject them directly into build_config.py.

    Environment variables set via os.environ are NOT visible at runtime
    inside a PyInstaller exe (os.getenv runs at *runtime*, not build time).
    Instead, we directly patch build_config.py to contain the key literals.
    """
    key_files = {
        "public": ROOT / "keys" / "license_public.pem",
        "private": ROOT / "keys" / "license_private.pem",
    }
    keys: dict[str, str] = {}
    for kind, key_path in key_files.items():
        env_var = f"STARTRACE_LICENSE_{kind.upper()}_KEY_PEM"
        if os.environ.get(env_var, "").strip():
            keys[kind] = os.environ[env_var].strip()
            continue
        if key_path.is_file():
            keys[kind] = key_path.read_text("utf-8").strip()
            os.environ[env_var] = keys[kind]
            print(f"  Loaded {env_var} from {key_path}")
        else:
            keys[kind] = ""

    # Patch build_config.py to embed the key content as string literals.
    config_path = ROOT / "app" / "build_config.py"
    original = config_path.read_text("utf-8")
    patched = original.replace(
        '_BUILD_PUBLIC_KEY = ""',
        f'_BUILD_PUBLIC_KEY = """{keys.get("public", "")}"""',
    ).replace(
        '_BUILD_PRIVATE_KEY = ""',
        f'_BUILD_PRIVATE_KEY = """{keys.get("private", "")}"""',
    )
    if patched != original:
        config_path.write_text(patched, encoding="utf-8")
        print(f"  Injected license keys into {config_path}")


def _restore_build_config(original: str) -> None:
    config_path = ROOT / "app" / "build_config.py"
    config_path.write_text(original, encoding="utf-8")


def main() -> int:
    args = _parse_args()
    config_path = ROOT / "app" / "build_config.py"
    original_config = config_path.read_text("utf-8")
    _ensure_license_keys()
    command = _build_command(admin=args.admin, clean=args.clean)
    print("Running:", " ".join(command))
    try:
        completed = subprocess.run(command, cwd=ROOT)
    finally:
        _restore_build_config(original_config)
        print("  Restored build_config.py")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
