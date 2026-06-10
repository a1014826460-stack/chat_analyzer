from __future__ import annotations

import json
import logging
import os
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)
DEFAULT_SHARED_PREFS = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "com.tencent.chat.flutter"
    / "tencent_cloud_chat_demo"
    / "shared_preferences.json"
)
DEFAULT_CONFIG_ROOT = Path.home() / "Documents" / "TencentCloudChat" / "Config"


def _windows_documents_dir_from_registry() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            raw_value, _ = winreg.QueryValueEx(key, "Personal")
        return Path(os.path.expandvars(raw_value))
    except Exception:
        return None


def _windows_documents_dir() -> Path | None:
    if os.name != "nt":
        return None
    try:
        from ctypes import create_unicode_buffer, windll

        buffer = create_unicode_buffer(260)
        if windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    except Exception:
        return None
    return None


@dataclass
class AccountRecord:
    account_name: str
    accid: str
    im_appid: str


@dataclass
class ResolvedDatabase:
    account_name: str
    accid: str
    im_appid: str
    config_dir: Path
    im_db: Path
    msg_db: Path


@dataclass
class ResolveDiagnostic:
    prefs_path: str = ""
    prefs_exists: bool = False
    prefs_valid_json: bool = False
    raw_account_count: int = 0
    parsed_account_count: int = 0
    accounts_found: list[str] = field(default_factory=list)
    input_username: str = ""
    matched_account: str = ""
    config_root: str = ""
    config_root_exists: bool = False
    candidate_dirs: list[str] = field(default_factory=list)
    dirs_with_im_db: list[str] = field(default_factory=list)
    dirs_with_msg_db: list[str] = field(default_factory=list)
    db_validate_passed: bool = False

    def format_message(self) -> str:
        parts = [
            "Database auto-location failed.",
            f"Input username: {self.input_username or '-'}",
            f"Shared preferences: {self.prefs_path or '-'}",
            f"Preferences exists: {self.prefs_exists}",
            f"Preferences valid: {self.prefs_valid_json}",
            f"Accounts found: {', '.join(self.accounts_found) if self.accounts_found else '-'}",
            f"Matched account: {self.matched_account or '-'}",
            f"Config root: {self.config_root or '-'}",
            f"Candidate dirs: {', '.join(self.candidate_dirs) if self.candidate_dirs else '-'}",
        ]
        return "\n".join(parts)


class AccountResolver:
    def __init__(self, shared_prefs_path: Path = DEFAULT_SHARED_PREFS, config_root: Path = DEFAULT_CONFIG_ROOT) -> None:
        self.shared_prefs_path = shared_prefs_path
        self.config_root = config_root
        self._last_diagnostic: ResolveDiagnostic | None = None

    def list_accounts(self) -> list[str]:
        return [item.account_name for item in self._load_accounts()]

    def resolve(self, username: str) -> ResolvedDatabase | None:
        diag = ResolveDiagnostic(input_username=username.strip(), prefs_path=str(self.shared_prefs_path))
        self._last_diagnostic = diag

        normalized_username = self._normalize_identifier(username)
        if not normalized_username:
            return None

        diag.prefs_exists = self.shared_prefs_path.exists()
        if not diag.prefs_exists:
            return None

        payload = self._try_load_json(self.shared_prefs_path)
        diag.prefs_valid_json = payload is not None
        if payload is None:
            return None

        raw_accounts = self._collect_raw_account_entries(payload)
        accounts = self._load_accounts()
        diag.raw_account_count = len(raw_accounts)
        diag.parsed_account_count = len(accounts)
        diag.accounts_found = [item.account_name for item in accounts]

        config_root = self._select_config_root()
        diag.config_root = str(config_root)
        diag.config_root_exists = config_root.exists()

        for account in accounts:
            if not self._account_matches(account, normalized_username):
                continue
            diag.matched_account = account.account_name
            for config_dir in self._candidate_dirs(config_root, account.im_appid, account.accid):
                diag.candidate_dirs.append(str(config_dir))
                im_db = config_dir / "im.db"
                msg_db = config_dir / "msg_0.db"
                if im_db.exists():
                    diag.dirs_with_im_db.append(str(config_dir))
                if msg_db.exists():
                    diag.dirs_with_msg_db.append(str(config_dir))
                if im_db.exists() and msg_db.exists() and self._validate_db(im_db, account.accid, account.account_name):
                    diag.db_validate_passed = True
                    return ResolvedDatabase(
                        account_name=account.account_name,
                        accid=account.accid,
                        im_appid=account.im_appid,
                        config_dir=config_dir,
                        im_db=im_db,
                        msg_db=msg_db,
                    )
        return None

    def get_diagnostic(self) -> ResolveDiagnostic | None:
        return self._last_diagnostic

    def _load_accounts(self) -> list[AccountRecord]:
        payload = self._try_load_json(self.shared_prefs_path)
        if payload is None:
            return []

        accounts_by_accid: dict[str, AccountRecord] = {}
        for raw in self._collect_raw_account_entries(payload):
            parsed = self._parse_embedded_json(raw)
            if not parsed:
                continue
            accid = str(parsed.get("accid", "")).strip()
            login = parsed.get("loginResultEntity", {})
            im_appid = str((login or {}).get("imAppid", "") or parsed.get("imAppid", "")).strip()
            nick = self._extract_nickname(parsed)
            if accid and im_appid and nick:
                accounts_by_accid.setdefault(
                    accid,
                    AccountRecord(account_name=nick, accid=accid, im_appid=im_appid),
                )
        return list(accounts_by_accid.values())

    def _collect_raw_account_entries(self, payload: dict) -> list[object]:
        raw_accounts: list[object] = []
        account_list = payload.get("flutter.AccountManager_AccountList", [])
        if isinstance(account_list, list):
            raw_accounts.extend(account_list)
        for key, value in payload.items():
            if "SpKeyLoginResult" in str(key):
                raw_accounts.append(value)
        return raw_accounts

    def _select_config_root(self) -> Path:
        for candidate in self._candidate_config_roots():
            if candidate.exists():
                return candidate
        return self.config_root

    def _candidate_config_roots(self) -> list[Path]:
        roots = [self.config_root]
        for docs_dir in (
            _windows_documents_dir_from_registry(),
            _windows_documents_dir(),
            Path.home() / "Documents",
            Path.home() / "OneDrive" / "Documents",
        ):
            if docs_dir:
                roots.append(Path(docs_dir) / "TencentCloudChat" / "Config")
        seen: set[str] = set()
        ordered: list[Path] = []
        for root in roots:
            key = str(root).casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(root)
        return ordered

    def _candidate_dirs(self, config_root: Path, im_appid: str, accid: str) -> list[Path]:
        exact = config_root / f"{im_appid}_{accid.encode('utf-8').hex()}"
        fallback = config_root / accid
        return [exact, fallback]

    def _validate_db(self, im_db: Path, accid: str, username: str) -> bool:
        try:
            con = sqlite3.connect(f"file:{im_db.as_posix()}?mode=ro", uri=True)
            cur = con.cursor()
            row = cur.execute(
                "select 1 from userinfo where user_id = ? or nick_name = ? limit 1",
                (accid, username),
            ).fetchone()
            con.close()
            return row is not None
        except Exception:
            return False

    def _parse_embedded_json(self, raw: object) -> dict | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _extract_nickname(self, parsed: dict) -> str:
        login = parsed.get("loginResultEntity", {})
        if isinstance(login, dict):
            for key in ("nickName", "userName"):
                value = str(login.get(key, "")).strip()
                if value:
                    return value
        for key in ("nickName", "userName"):
            value = str(parsed.get(key, "")).strip()
            if value:
                return value
        return ""

    def _account_matches(self, item: AccountRecord, normalized_value: str) -> bool:
        return normalized_value in {
            self._normalize_identifier(item.account_name),
            self._normalize_identifier(item.accid),
        }

    def _try_load_json(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _normalize_identifier(self, value: str) -> str:
        return unicodedata.normalize("NFKC", str(value).strip()).casefold()
