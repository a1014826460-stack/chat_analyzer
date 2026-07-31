from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tools import build


def test_development_build_config_loads_local_license_signing_keys(monkeypatch):
    monkeypatch.delenv("STARTRACE_LICENSE_PUBLIC_KEY_PEM", raising=False)
    monkeypatch.delenv("STARTRACE_LICENSE_PRIVATE_KEY_PEM", raising=False)
    module_path = Path("app/build_config.py")
    spec = importlib.util.spec_from_file_location("development_build_config", module_path)
    assert spec is not None and spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    assert config.LICENSE_PUBLIC_KEY_PEM.startswith("-----BEGIN PUBLIC KEY-----")
    assert config.LICENSE_PRIVATE_KEY_PEM.startswith("-----BEGIN PRIVATE KEY-----")


def test_packaged_build_requires_centrally_managed_server_url(monkeypatch):
    monkeypatch.delenv("STARTRACE_SERVER_API_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="STARTRACE_SERVER_API_BASE_URL"):
        build._embed_release_metadata()


def test_packaged_build_embeds_server_url_in_build_config(monkeypatch, tmp_path):
    config_path = tmp_path / "app" / "build_config.py"
    config_path.parent.mkdir()
    config_path.write_text(
        'APP_VERSION = os.getenv("STARTRACE_VERSION", "1.0.0")\n'
        'BUILD_ID = os.getenv("STARTRACE_BUILD_ID", "build-1")\n'
        '_BUILD_SERVER_API_BASE_URL = ""\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setenv("STARTRACE_SERVER_API_BASE_URL", "https://207.56.2.71:8080/")

    build._embed_release_metadata()

    assert "_BUILD_SERVER_API_BASE_URL = 'https://207.56.2.71:8080'" in config_path.read_text(encoding="utf-8")
