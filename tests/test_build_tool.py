from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_build_module():
    path = Path("tools/build.py")
    spec = importlib.util.spec_from_file_location("startrace_build_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_embeds_release_version_and_build_id_before_pyinstaller(monkeypatch, tmp_path):
    build = _load_build_module()
    config_path = tmp_path / "app" / "build_config.py"
    config_path.parent.mkdir()
    config_path.write_text(
        'APP_VERSION = os.getenv("STARTRACE_VERSION", "1.97.0")\n'
        'BUILD_ID = os.getenv("STARTRACE_BUILD_ID", "old")\n'
        '_BUILD_PUBLIC_KEY = ""\n'
        '_BUILD_PRIVATE_KEY = ""\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setenv("STARTRACE_VERSION", "1.99.3")
    monkeypatch.setenv("STARTRACE_BUILD_ID", "startrace_202607150001")

    original = config_path.read_text(encoding="utf-8")
    build._embed_release_metadata()

    embedded = config_path.read_text(encoding="utf-8")
    assert 'APP_VERSION = "1.99.3"' in embedded
    assert 'BUILD_ID = "startrace_202607150001"' in embedded

    build._restore_build_config(original)

    assert config_path.read_text(encoding="utf-8") == original


def test_user_build_embeds_only_the_license_public_key(monkeypatch, tmp_path):
    build = _load_build_module()
    config_path = tmp_path / "app" / "build_config.py"
    config_path.parent.mkdir()
    config_path.write_text(
        '_BUILD_PUBLIC_KEY = ""\n_BUILD_PRIVATE_KEY = ""\n_BUILD_UPDATE_PUBLIC_KEY = ""\n', encoding="utf-8"
    )
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "license_public.pem").write_text("PUBLIC-KEY", encoding="utf-8")
    (keys_dir / "license_private.pem").write_text("PRIVATE-KEY", encoding="utf-8")
    (keys_dir / "update_public.pem").write_text("UPDATE-PUBLIC-KEY", encoding="utf-8")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.delenv("STARTRACE_LICENSE_PUBLIC_KEY_PEM", raising=False)
    monkeypatch.delenv("STARTRACE_LICENSE_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.delenv("STARTRACE_UPDATE_PUBLIC_KEY_PEM", raising=False)

    build._ensure_license_keys(admin=False)

    embedded = config_path.read_text(encoding="utf-8")
    assert 'PUBLIC-KEY' in embedded
    assert 'PRIVATE-KEY' not in embedded
    assert 'UPDATE-PUBLIC-KEY' in embedded


def test_user_build_command_excludes_legacy_embedded_keys_module():
    build = _load_build_module()

    command = build._build_command(admin=False, clean=False)

    assert "app._embedded_keys" not in command


def test_admin_build_embeds_the_license_private_key(monkeypatch, tmp_path):
    build = _load_build_module()
    config_path = tmp_path / "app" / "build_config.py"
    config_path.parent.mkdir()
    config_path.write_text(
        '_BUILD_PUBLIC_KEY = ""\n_BUILD_PRIVATE_KEY = ""\n_BUILD_UPDATE_PUBLIC_KEY = ""\n', encoding="utf-8"
    )
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "license_public.pem").write_text("PUBLIC-KEY", encoding="utf-8")
    (keys_dir / "license_private.pem").write_text("PRIVATE-KEY", encoding="utf-8")
    (keys_dir / "update_public.pem").write_text("UPDATE-PUBLIC-KEY", encoding="utf-8")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.delenv("STARTRACE_LICENSE_PUBLIC_KEY_PEM", raising=False)
    monkeypatch.delenv("STARTRACE_LICENSE_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.delenv("STARTRACE_UPDATE_PUBLIC_KEY_PEM", raising=False)

    build._ensure_license_keys(admin=True)

    embedded = config_path.read_text(encoding="utf-8")
    assert 'PUBLIC-KEY' in embedded
    assert 'PRIVATE-KEY' in embedded
