from __future__ import annotations

import argparse
import os
import re
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
    parser.add_argument(
        "--no-setup",
        action="store_true",
        help="Skip Inno Setup packaging (bare exe only).",
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


def _ensure_license_keys(*, admin: bool) -> None:
    """Read license key files and inject them directly into build_config.py.

    Environment variables set via os.environ are NOT visible at runtime
    inside a PyInstaller exe (os.getenv runs at *runtime*, not build time).
    Instead, we directly patch build_config.py to contain the key literals.
    """
    key_files = {"public": ROOT / "keys" / "license_public.pem"}
    if admin:
        key_files["private"] = ROOT / "keys" / "license_private.pem"
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

    update_public_key = os.environ.get("STARTRACE_UPDATE_PUBLIC_KEY_PEM", "").strip()
    update_public_path = ROOT / "keys" / "update_public.pem"
    if not update_public_key and update_public_path.is_file():
        update_public_key = update_public_path.read_text("utf-8").strip()
        os.environ["STARTRACE_UPDATE_PUBLIC_KEY_PEM"] = update_public_key
        print(f"  Loaded STARTRACE_UPDATE_PUBLIC_KEY_PEM from {update_public_path}")
    if not update_public_key:
        raise RuntimeError("STARTRACE_UPDATE_PUBLIC_KEY_PEM or keys/update_public.pem is required")

    # Patch build_config.py to embed the key content as string literals.
    config_path = ROOT / "app" / "build_config.py"
    original = config_path.read_text("utf-8")
    private_key = keys.get("private", "") if admin else ""
    patched = original.replace(
        '_BUILD_PUBLIC_KEY = ""',
        f'_BUILD_PUBLIC_KEY = """{keys.get("public", "")}"""',
    ).replace(
        '_BUILD_PRIVATE_KEY = ""',
        f'_BUILD_PRIVATE_KEY = """{private_key}"""',
    ).replace(
        '_BUILD_UPDATE_PUBLIC_KEY = ""',
        f'_BUILD_UPDATE_PUBLIC_KEY = """{update_public_key}"""',
    )
    if patched != original:
        config_path.write_text(patched, encoding="utf-8")
        print(f"  Injected license keys into {config_path}")


def _embed_release_metadata() -> None:
    """Embed build-time version metadata so the frozen app needs no environment."""
    config_path = ROOT / "app" / "build_config.py"
    original = config_path.read_text("utf-8")
    version = os.environ.get("STARTRACE_VERSION", build_config.APP_VERSION).strip()
    build_id = os.environ.get("STARTRACE_BUILD_ID", build_config.BUILD_ID).strip()
    server_api_base_url = os.environ.get("STARTRACE_SERVER_API_BASE_URL", "").strip().rstrip("/")
    requires_server_url = '_BUILD_SERVER_API_BASE_URL = ""' in original
    if requires_server_url and not server_api_base_url:
        raise RuntimeError("STARTRACE_SERVER_API_BASE_URL must be set for a packaged client build")
    patched = re.sub(
        r'^APP_VERSION = os\.getenv\("STARTRACE_VERSION", "[^"]*"\)$',
        f'APP_VERSION = "{version}"',
        original,
        flags=re.MULTILINE,
    )
    if requires_server_url:
        patched = patched.replace(
            '_BUILD_SERVER_API_BASE_URL = ""',
            f'_BUILD_SERVER_API_BASE_URL = {server_api_base_url!r}',
        )
    patched = re.sub(
        r'^BUILD_ID = os\.getenv\("STARTRACE_BUILD_ID", "[^"]*"\)$',
        f'BUILD_ID = "{build_id}"',
        patched,
        flags=re.MULTILINE,
    )
    if patched == original:
        raise RuntimeError("Unable to embed release version metadata into build_config.py")
    config_path.write_text(patched, encoding="utf-8")
    print(f"  Embedded release metadata: version={version}, build_id={build_id}")


def _restore_build_config(original: str) -> None:
    config_path = ROOT / "app" / "build_config.py"
    config_path.write_text(original, encoding="utf-8")


_INNO_ISCC = r"C:\Users\Administrator\AppData\Local\Programs\Inno Setup 6\ISCC.exe"


def _build_setup_installer(version: str, *, admin: bool, args) -> None:
    """Compile the PyInstaller artifact into a setup.exe with Inno Setup."""
    if getattr(args, "no_setup", False) or not Path(_INNO_ISCC).is_file():
        print("  Skipping setup.exe (ISCC unavailable or --no-setup)")
        return
    setup_dir = ROOT / "tools" / "installer"
    iss_path = setup_dir / "star_trace.iss"
    dist_dir = ROOT / "dist"
    artifact = dist_dir / (f"StarTrace-Admin-{version}.exe" if admin else f"StarTrace-{version}.exe")
    # Inno Setup appends ".exe" to OutputBaseFilename automatically.
    output_name = f"StarTrace-Admin-Setup-{version}" if admin else f"StarTrace-Setup-{version}"
    define = {
        "MyAppName": f"StarTrace {'(Admin)' if admin else ''}".strip(),
        "MyAppVersion": version,
        "MyAppExe": artifact.name,
        "MyAppOutput": output_name,
        "MyAppAdmin": "true" if admin else "false",
    }
    cmd = [_INNO_ISCC, str(iss_path)]
    for key, value in define.items():
        cmd.append(f"/D{key}={value}")
    print(f"  Running ISCC: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(setup_dir))
    print(f"  Produced {dist_dir / (output_name + '.exe')}")


def main() -> int:
    args = _parse_args()
    config_path = ROOT / "app" / "build_config.py"
    original_config = config_path.read_text("utf-8")
    _ensure_license_keys(admin=args.admin)
    _embed_release_metadata()
    version = os.environ.get("STARTRACE_VERSION", build_config.APP_VERSION).strip()
    command = _build_command(admin=args.admin, clean=args.clean)
    print("Running:", " ".join(command))
    try:
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode == 0:
            _build_setup_installer(version, admin=args.admin, args=args)
    finally:
        _restore_build_config(original_config)
        print("  Restored build_config.py")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
