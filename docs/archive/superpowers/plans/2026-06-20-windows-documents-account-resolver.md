# Windows Documents Account Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make account database auto-location and diagnostics honor the real Windows `Documents` directory even when it has been redirected to another drive.

**Architecture:** Centralize `Documents` path discovery in `app/services/account_resolver.py`, then derive both the constructor default config root and runtime candidate roots from that single ordered source. Add focused tests that monkeypatch the Windows lookup helpers so redirected and fallback behaviors are deterministic.

**Tech Stack:** Python 3, `pathlib`, `pytest`, `monkeypatch`

---

### Task 1: Add failing tests for redirected Windows Documents defaults

**Files:**
- Create: `tests/test_account_resolver.py`
- Modify: `app/services/account_resolver.py`
- Test: `tests/test_account_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.services import account_resolver as resolver_module


def test_account_resolver_default_config_root_uses_windows_documents(monkeypatch) -> None:
    monkeypatch.setattr(resolver_module, "_windows_documents_dir_from_registry", lambda: Path("D:/Profiles/Alice/Documents"))
    monkeypatch.setattr(resolver_module, "_windows_documents_dir", lambda: Path("C:/Ignored/Documents"))

    resolver = resolver_module.AccountResolver(shared_prefs_path=Path("prefs.json"))

    assert resolver.config_root == Path("D:/Profiles/Alice/Documents/TencentCloudChat/Config")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_account_resolver.py::test_account_resolver_default_config_root_uses_windows_documents -v`
Expected: FAIL because `resolver.config_root` still uses the hardcoded home-based default.

- [ ] **Step 3: Write minimal implementation**

```python
def _documents_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    for path in (
        _windows_documents_dir_from_registry(),
        _windows_documents_dir(),
        Path.home() / "Documents",
        Path.home() / "OneDrive" / "Documents",
    ):
        if path:
            candidates.append(Path(path))
    return _dedupe_paths(candidates)


def _default_config_root() -> Path:
    candidates = _candidate_config_roots_from_documents()
    return candidates[0] if candidates else Path.home() / "Documents" / "TencentCloudChat" / "Config"


class AccountResolver:
    def __init__(self, shared_prefs_path: Path = DEFAULT_SHARED_PREFS, config_root: Path | None = None) -> None:
        self.shared_prefs_path = shared_prefs_path
        self.config_root = Path(config_root) if config_root is not None else _default_config_root()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_account_resolver.py::test_account_resolver_default_config_root_uses_windows_documents -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_account_resolver.py app/services/account_resolver.py
git commit -m "test: cover redirected windows documents default"
```

### Task 2: Add failing tests for candidate ordering and fallback behavior

**Files:**
- Modify: `tests/test_account_resolver.py`
- Modify: `app/services/account_resolver.py`
- Test: `tests/test_account_resolver.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from app.services import account_resolver as resolver_module


def test_candidate_config_roots_prioritize_windows_documents(monkeypatch) -> None:
    monkeypatch.setattr(resolver_module, "_windows_documents_dir_from_registry", lambda: Path("D:/Profiles/Alice/Documents"))
    monkeypatch.setattr(resolver_module, "_windows_documents_dir", lambda: Path("E:/Shell/Documents"))
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_account_resolver.py::test_candidate_config_roots_prioritize_windows_documents tests/test_account_resolver.py::test_candidate_config_roots_keep_home_fallback_when_windows_lookup_missing -v`
Expected: FAIL because candidate generation still starts from the existing constructor path instead of a centralized ordered resolver.

- [ ] **Step 3: Write minimal implementation**

```python
def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def _candidate_config_roots_from_documents() -> list[Path]:
    return [docs / "TencentCloudChat" / "Config" for docs in _documents_dir_candidates()]


class AccountResolver:
    def _candidate_config_roots(self) -> list[Path]:
        explicit_root = Path(self.config_root)
        roots = [explicit_root, *_candidate_config_roots_from_documents()]
        return _dedupe_paths(roots)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_account_resolver.py::test_candidate_config_roots_prioritize_windows_documents tests/test_account_resolver.py::test_candidate_config_roots_keep_home_fallback_when_windows_lookup_missing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_account_resolver.py app/services/account_resolver.py
git commit -m "test: cover windows documents candidate ordering"
```

### Task 3: Add failing test for runtime selection and diagnostic alignment

**Files:**
- Modify: `tests/test_account_resolver.py`
- Modify: `app/services/account_resolver.py`
- Test: `tests/test_account_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from app.services.account_resolver import AccountResolver
from app.services import account_resolver as resolver_module


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_account_resolver.py::test_resolve_reports_redirected_config_root_in_diagnostics -v`
Expected: FAIL if the diagnostic still reports the stale home-based config root.

- [ ] **Step 3: Write minimal implementation**

```python
class AccountResolver:
    def _select_config_root(self) -> Path:
        candidates = self._candidate_config_roots()
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0] if candidates else Path(self.config_root)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_account_resolver.py::test_resolve_reports_redirected_config_root_in_diagnostics -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_account_resolver.py app/services/account_resolver.py
git commit -m "fix: align diagnostics with redirected windows documents"
```

### Task 4: Run targeted and broader verification

**Files:**
- Modify: `tests/test_account_resolver.py`
- Modify: `app/services/account_resolver.py`

- [ ] **Step 1: Run focused resolver tests**

Run: `pytest tests/test_account_resolver.py -v`
Expected: PASS for all new resolver tests.

- [ ] **Step 2: Run existing lightweight regression coverage**

Run: `pytest tests/test_source_recovery.py -v`
Expected: PASS with no regressions caused by importing or compiling the updated resolver module.

- [ ] **Step 3: If a test fails, make the smallest code or test fix needed and rerun**

```python
# Keep changes limited to account_resolver.py or tests/test_account_resolver.py
# unless a regression reveals a real dependency elsewhere.
```

- [ ] **Step 4: Commit final verified state**

```bash
git add app/services/account_resolver.py tests/test_account_resolver.py docs/superpowers/specs/2026-06-20-windows-documents-account-resolver-design.md docs/superpowers/plans/2026-06-20-windows-documents-account-resolver.md
git commit -m "fix: honor redirected windows documents for account resolver"
```
