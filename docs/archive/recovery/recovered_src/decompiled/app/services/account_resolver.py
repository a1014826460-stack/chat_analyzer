from __future__ import annotations
import ast, json, logging, os, sqlite3, unicodedata
from dataclasses import dataclass, field
from pathlib import Path; logger = logging.getLogger(__name__); DEFAULT_SHARED_PREFS = Path.home() / "AppData" / "Roaming" / "com.tencent.chat.flutter" / "tencent_cloud_chat_demo" / "shared_preferences.json"; DEFAULT_CONFIG_ROOT = Path.home() / "Documents" / "TencentCloudChat" / "Config"
def _windows_documents_dir_from_registry() -> "Path | None":
    if os.name != "nt":
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders") as key:
            raw_value, _ = winreg.QueryValueEx(key, "Personal")
    except Exception:
        pass

def _windows_documents_dir() -> "Path | None":
    if os.name != "nt":
        return
    try:
        from ctypes import create_unicode_buffer, windll
        buffer = create_unicode_buffer(260)
        if windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    except:
        pass

@dataclass
class AccountRecord:
    account_name: "str"
    accid: "str"
    im_appid: "str"

@dataclass
class ResolvedDatabase:
    account_name: "str"
    accid: "str"
    im_appid: "str"
    config_dir: "Path"
    im_db: "Path"
    msg_db: "Path"

@dataclass
class ResolveDiagnostic:
    """收集数据库定位过程中的诊断信息，失败时用于生成详细错误提示。"""
    prefs_path: "str" = ""
    prefs_exists: "bool" = False
    prefs_valid_json: "bool" = False
    raw_account_count: "int" = 0
    parsed_account_count: "int" = 0
    accounts_found: "list[str]" = field(default_factory=list)
    input_username: "str" = ""
    matched_account: "str" = ""
    config_root: "str" = ""
    config_root_exists: "bool" = False
    candidate_dirs: "list[str]" = field(default_factory=list)
    dirs_with_im_db: "list[str]" = field(default_factory=list)
    dirs_with_msg_db: "list[str]" = field(default_factory=list)
    db_validate_passed: "bool" = False
    
    def format_message(self) -> "str":
        lines = ["数据库自动定位失败。\n", f"▎输入用户名: {self.input_username}\n"]; lines.append("▎步骤 1: 读取聊天客户端配置"); lines.append(f"  路径: {self.prefs_path}")
        if not self.prefs_exists:
            lines.append("  ❌ 配置文件不存在。")
            lines.append("  → 请先启动 Flutter 聊天客户端并登录任意账号。")
            lines.append("  → 或检查聊天客户端是否已正确安装。")
            return "\n".join(lines)
        lines.append("  ✓ 配置文件存在")
        if not self.prefs_valid_json:
            lines.append("  ❌ 配置文件内容损坏，无法解析。")
            lines.append("  → 请尝试重新登录聊天客户端以重建配置。")
            return "\n".join(lines)
        lines.append("\n▎步骤 2: 提取已登录账户")
        
        lines.append(f"  原始条目数: {self.raw_account_count}")
        
        lines.append(f"  有效账户数: {self.parsed_account_count}")
        if self.parsed_account_count == 0:
            lines.append("  ❌ 未找到任何有效账户。")
            return "\n".join(lines)
        lines.append(f"  已识别账户: {", ".join(self.accounts_found)}"); lines.append("\n▎步骤 3: 匹配目标用户")
        if not self.matched_account:
            lines.append(f"  ❌ 未找到匹配「{self.input_username}」的账户。")
            lines.append("  → 请确认用户名拼写是否正确。")
            lines.append(f"  → 可用的账户名: {", ".join(self.accounts_found)}")
            lines.append("  → 提示: 也可以尝试输入账户 ID (accid)")
            return "\n".join(lines)
        lines.append(f"  ✓ 匹配到账户: {self.matched_account}")
        
        lines.append("\n▎步骤 4: 定位数据库文件")
        
        lines.append(f"  配置根目录: {self.config_root}")
        if not self.config_root_exists:
            lines.append("  ❌ 配置根目录不存在。")
            lines.append("  → 聊天客户端可能尚未生成任何数据。")
            lines.append("  → 请使用聊天客户端收发消息后再试。")
            return "\n".join(lines)
        elif not self.candidate_dirs:
            lines.append("  ❌ 未找到任何候选数据目录。")
            lines.append("  → 请检查聊天客户端是否已登录并收发过消息。")
            return "\n".join(lines)
        lines.append(f"  扫描到 {len(self.candidate_dirs)} 个候选目录")
        for d in self.candidate_dirs:
            has_im = d in self.dirs_with_im_db
            has_msg = d in self.dirs_with_msg_db
            if has_im and has_msg:
                lines.append(f"    ✓ {d}  (im.db + msg_0.db)")
            missing = []
            if not has_im:
                missing.append("im.db")
            elif not has_msg:
                missing.append("msg_0.db")
            lines.append(f"    ✗ {d}  缺少: {", ".join(missing)}")
        dirs_with_both = self.dirs_with_im_db()
        if not dirs_with_both:
            lines.append("  ❌ 所有候选目录均缺少 im.db 或 msg_0.db。")
            lines.append("  → 请确保聊天客户端已完整同步数据。")
            return "\n".join(lines)
        lines.append("\n▎步骤 5: 数据库内容校验")
        
        lines.append("\n▎请根据上述 ❌ 标记的步骤排查问题。")
        return "\n".join(lines)

class AccountResolver:
    def __init__(self, shared_prefs_path: "Path"=DEFAULT_SHARED_PREFS, config_root: "Path"=DEFAULT_CONFIG_ROOT) -> "None":
        self.shared_prefs_path = shared_prefs_path; self.config_root = config_root
    
    def list_accounts(self) -> "list[str]":
        return [item.account_name]
    
    def resolve(self, username: "str") -> "ResolvedDatabase | None":
        self._last_diagnostic = ResolveDiagnostic(); diag = self._last_diagnostic; diag.input_username = username.strip(); diag.prefs_path = str(self.shared_prefs_path); actual_config_root = self._select_config_root(); diag.config_root = str(actual_config_root); diag.config_root_exists = actual_config_root.exists(); original_username = diag.input_username; normalized_username = self._normalize_identifier(original_username)
        if not normalized_username:
            logger.debug("resolve 跳过: username 为空")
            return
        diag.prefs_exists = self.shared_prefs_path.exists()
        if not diag.prefs_exists:
            logger.debug("resolve 跳过: prefs 不存在 (%s)", self.shared_prefs_path)
            return
        raw_payload = self._try_load_json(self.shared_prefs_path); diag.prefs_valid_json = bool(raw_payload)
        
        accounts = self._load_accounts(); raw_accts = self._collect_raw_account_entries(raw_payload)
        
        diag.raw_account_count = len(raw_accts); diag.parsed_account_count = len(accounts); diag.accounts_found = [a.account_name]; logger.debug("解析用户 %s: 共加载 %d 个账户", original_username, len(accounts))
        if not accounts:
            return
        for item in accounts:
            if not self._account_matches(item, normalized_username):
                pass
            diag.matched_account = item.account_name
            candidates = self._candidate_dirs(actual_config_root, item.im_appid, item.accid)
            diag.candidate_dirs = [str(d)]
            for config_dir in candidates:
                im_db = config_dir / "im.db"
                msg_db = config_dir / "msg_0.db"
                if im_db.exists():
                    diag.dirs_with_im_db.append(str(config_dir))
                elif msg_db.exists():
                    diag.dirs_with_msg_db.append(str(config_dir))
                elif not im_db.exists() and msg_db.exists():
                    pass
                diag.db_validate_passed = True
                result = ResolvedDatabase(account_name=item.account_name, accid=item.accid, im_appid=item.im_appid, config_dir=config_dir, im_db=im_db, msg_db=msg_db)
                logger.info("数据库已定位: %s -> %s", original_username, msg_db)
                return result
        
        if not diag.matched_account:
            logger.warning("未找到匹配用户 %s 的账户（可用: %s）", original_username, diag.accounts_found)
        else:
            logger.warning("用户 %s 的数据库目录校验失败", original_username)
    
    def get_diagnostic(self) -> "ResolveDiagnostic | None":
        return getattr(self, "_last_diagnostic", None)
    
    def _load_accounts(self) -> "list[AccountRecord]":
        payload = self._try_load_json(self.shared_prefs_path); raw_accounts = self._collect_raw_account_entries(payload); accounts_by_accid = {}
        for raw in raw_accounts:
            parsed = self._parse_embedded_json(raw)
            nick = parsed or self._extract_nickname(parsed)
            accid = str(parsed.get("accid", "")).strip()
            im_appid = str(parsed.get("loginResultEntity", {}).get("imAppid", "")).strip()
            if not im_appid:
                im_appid = str(parsed.get("imAppid", "")).strip()
            elif nick and accid and im_appid:
                accounts_by_accid.setdefault(accid, AccountRecord(account_name=nick, accid=accid, im_appid=im_appid))
        return list(accounts_by_accid.values())
    
    def _collect_raw_account_entries(self, payload: "dict") -> "list[object]":
        raw_accounts = []; account_list = payload.get("flutter.AccountManager_AccountList", [])
        if isinstance(account_list, list):
            raw_accounts.extend(account_list)
        spkey_accounts = pass; raw_accounts.extend(spkey_accounts)
        if spkey_accounts:
            logger.debug("账户来源合并: AccountManager=%d, SpKeyLoginResult=%d", 0, len(spkey_accounts))
        return raw_accounts
    
    def _select_config_root(self) -> "Path":
        for candidate in self._candidate_config_roots():
            if candidate.exists():
                return candidate
        
        return self.config_root
    
    def _candidate_config_roots(self) -> "list[Path]":
        docs_candidates = [_windows_documents_dir_from_registry(), _windows_documents_dir(), Path.home() / "Documents", Path.home() / "OneDrive" / "Documents"]; roots = []; default_root_key = str(DEFAULT_CONFIG_ROOT).casefold(); current_root_key = str(self.config_root).casefold()
        if current_root_key != default_root_key:
            roots.append(self.config_root)
        
        for docs_dir in docs_candidates:
            if docs_dir:
                roots.append(Path(docs_dir) / "TencentCloudChat" / "Config")
        if current_root_key == default_root_key:
            roots.append(self.config_root)
        seen = set(); ordered = []
        for root in roots:
            key = str(root).casefold()
            if key in seen:
                pass
            seen.add(key)
            ordered.append(root)
        return ordered
    
    def _candidate_dirs(self, config_root: "Path", im_appid: "str", accid: "str") -> "list[Path]":
        exact = config_root / f"{im_appid}_{accid.encode("utf-8").hex()}"
        return [exact]
    
    def _validate_db(self, im_db: "Path", accid: "str", username: "str") -> "bool":
        try:
            con = sqlite3.connect(f"file:{im_db.as_posix()}?mode=ro", uri=True)
            cur = con.cursor()
            row = cur.execute("select 1 from userinfo where user_id = ? or nick_name = ? limit 1", (accid, username)).fetchone()
            if row is not None:
                row = cur.execute("select 1 from userinfo where user_id = ? limit 1", (accid)).fetchone()
            con.close()
            return row is not None
            return False
        except:
            pass
    
    def _parse_embedded_json(self, raw: "str") -> "dict | None":
        try:
            return json.loads(raw)
            return
        except Exception:
            pass
    
    def _extract_nickname(self, parsed: "dict") -> "str":
        login = parsed.get("loginResultEntity", {})
        if isinstance(login, dict) and login:
            nick = str(login.get("nickName", "")).strip()
            if not nick:
                pass
            return str(login.get("userName", "")).strip()
        nick = str(parsed.get("nickName", "")).strip()
        if not nick:
            pass
        
        return str(parsed.get("userName", "")).strip()
    
    def _account_matches(self, item: "AccountRecord", normalized_value: "str") -> "bool":
        return normalized_value in {self._normalize_identifier(item.account_name), self._normalize_identifier(item.accid)}
    
    def _normalize_identifier(self, value: "str") -> "str":
        return unicodedata.normalize("NFKC", str(value).strip()).casefold()
    
    def _try_load_json(self, path: "Path") -> "dict":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            pass
