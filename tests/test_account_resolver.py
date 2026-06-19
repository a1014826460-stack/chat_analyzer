from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import account_resolver as resolver_module
from app.services.account_resolver import AccountResolver


def test_account_resolver_default_config_root_uses_windows_documents(monkeypatch) -> None:
    monkeypatch.setattr(
        resolver_module,
        "_windows_documents_dir_from_registry",
        lambda: Path("D:/Profiles/Alice/Documents"),
    )
    monkeypatch.setattr(
        resolver_module,
        "_windows_documents_dir",
        lambda: Path("C:/Ignored/Documents"),
    )

    resolver = resolver_module.AccountResolver(shared_prefs_path=Path("prefs.json"))

    assert resolver.config_root == Path("D:/Profiles/Alice/Documents/TencentCloudChat/Config")


def test_candidate_config_roots_prioritize_windows_documents(monkeypatch) -> None:
    monkeypatch.setattr(
        resolver_module,
        "_windows_documents_dir_from_registry",
        lambda: Path("D:/Profiles/Alice/Documents"),
    )
    monkeypatch.setattr(
        resolver_module,
        "_windows_documents_dir",
        lambda: Path("E:/Shell/Documents"),
    )
    monkeypatch.setattr(resolver_module.Path, "home", classmethod(lambda cls: Path("C:/Users/Alice")))

    resolver = resolver_module.AccountResolver(shared_prefs_path=Path("prefs.json"))

    roots = resolver._candidate_config_roots()

    assert roots[0] == Path("D:/Profiles/Alice/Documents/TencentCloudChat/Config")
    assert roots[1] == Path("E:/Shell/Documents/TencentCloudChat/Config")
    assert Path("C:/Users/Alice/Documents/TencentCloudChat/Config") in roots


def test_candidate_config_roots_keep_home_fallback_when_windows_lookup_missing(monkeypatch) -> None:
    monkeypatch.setattr(resolver_module, "_windows_documents_dir_from_registry", lambda: None)
    monkeypatch.setattr(resolver_module, "_windows_documents_dir", lambda: None)
    monkeypatch.setattr(resolver_module.Path, "home", classmethod(lambda cls: Path("C:/Users/Alice")))

    resolver = resolver_module.AccountResolver(shared_prefs_path=Path("prefs.json"))

    assert resolver._candidate_config_roots()[0] == Path("C:/Users/Alice/Documents/TencentCloudChat/Config")


def test_resolve_reports_redirected_config_root_in_diagnostics(tmp_path, monkeypatch) -> None:
    redirected_docs = tmp_path / "RedirectedDocuments"
    config_root = redirected_docs / "TencentCloudChat" / "Config"
    account_dir = config_root / "20001_6163636964"
    account_dir.mkdir(parents=True)
    (account_dir / "im.db").write_bytes(b"not-a-real-db")
    (account_dir / "msg_0.db").write_bytes(b"")

    prefs_path = tmp_path / "shared_preferences.json"
    prefs_path.write_text(
        json.dumps(
            {
                "flutter.AccountManager_AccountList": [
                    json.dumps(
                        {
                            "accid": "accid",
                            "loginResultEntity": {"imAppid": "20001", "nickName": "Alice"},
                        }
                    )
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(resolver_module, "_windows_documents_dir_from_registry", lambda: redirected_docs)
    monkeypatch.setattr(resolver_module, "_windows_documents_dir", lambda: None)
    monkeypatch.setattr(AccountResolver, "_validate_db", lambda self, im_db, accid, username: False)

    resolver = AccountResolver(shared_prefs_path=prefs_path)

    assert resolver.resolve("Alice") is None
    diagnostic = resolver.get_diagnostic()
    assert diagnostic is not None
    assert diagnostic.config_root == str(config_root)
    assert str(account_dir) in diagnostic.candidate_dirs
