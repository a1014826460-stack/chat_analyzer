from __future__ import annotations

import importlib.util
from pathlib import Path


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
