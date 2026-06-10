from __future__ import annotations

import ast
import hashlib
import py_compile
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CRITICAL_FILES = [
    "app/main.py",
    "app/build_config.py",
    "app/models/__init__.py",
    "app/models/chat.py",
    "app/services/account_resolver.py",
    "app/services/chat_service.py",
    "app/services/license_service.py",
    "app/services/settings_service.py",
    "app/services/storage_service.py",
    "app/ui/chart_window.py",
    "app/ui/license_generator_dialog.py",
    "app/ui/main_window.py",
    "app/ui/main_window_actions.py",
    "app/ui/main_window_blocking.py",
    "app/ui/main_window_data.py",
    "app/ui/main_window_layout.py",
    "app/ui/main_window_realtime.py",
    "app/ui/main_window_theme.py",
    "app/utils/fetch_date.py",
    "app/utils/logging_config.py",
    "app/utils/pathing.py",
    "app/utils/protection.py",
    "app/utils/proxy.py",
    "tools/build.py",
    "tools/runtime_hook_user.py",
    "tools/runtime_hook_admin.py",
]

CHAT_SERVICE_METHODS = {
    "set_group_block_rules",
    "extract_groups",
    "list_groups_from_db",
    "load_messages",
    "load_messages_from_text",
    "load_messages_from_sqlite",
    "load_messages_with_cache",
    "get_cached_cursor",
    "get_cached_raw_cursor",
    "analyze_bets",
    "summarize_bets",
    "filter_blocked_messages",
    "export_filtered_messages",
    "export_stats_excel",
    "export_stats_pdf",
    "extract_bet_visual_data",
}

MAIN_WINDOW_DATA_METHODS = {
    "_load_initial_state",
    "_apply_initial_splitter_sizes",
    "_resolve_database",
    "_load_groups_from_current_source",
    "_pick_manual_data_source",
    "_load_manual_data_source",
    "_compute_load_signature",
    "_build_load_options",
    "_run_load_pipeline",
    "_apply_load_result",
    "_load_filtered_messages",
    "_handle_load_result_ready",
    "_update_chart_data",
    "_gather_parse_options",
}


def _compile_file(rel_path: str) -> None:
    py_compile.compile(ROOT / rel_path, doraise=True)


def _parse_module(rel_path: str) -> ast.Module:
    return ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))


def _class_method_names(module: ast.Module, class_name: str) -> set[str]:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"class {class_name} not found")


def test_critical_modules_compile() -> None:
    for rel_path in CRITICAL_FILES:
        _compile_file(rel_path)


def test_chat_service_public_api_present() -> None:
    module = _parse_module("app/services/chat_service.py")
    method_names = _class_method_names(module, "ChatLogService")
    missing = sorted(CHAT_SERVICE_METHODS - method_names)
    assert not missing, missing


def test_main_window_data_public_api_present() -> None:
    module = _parse_module("app/ui/main_window_data.py")
    method_names = _class_method_names(module, "MainWindowDataMixin")
    missing = sorted(MAIN_WINDOW_DATA_METHODS - method_names)
    assert not missing, missing


def test_protection_module_source_compiles_without_syntax_warnings() -> None:
    path = ROOT / "app/utils/protection.py"
    source = path.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, str(path), "exec")


def test_protection_hashes_full_file(tmp_path: Path) -> None:
    import app.utils.protection as protection

    payload = (b"0123456789abcdef" * 5000) + b"tail-marker"
    sample = tmp_path / "sample.bin"
    sample.write_bytes(payload)

    assert protection._c(str(sample)) == hashlib.sha256(payload).hexdigest()


def test_protection_runner_passes_when_checks_succeed(monkeypatch) -> None:
    import app.utils.protection as protection

    observed: list[str] = []

    monkeypatch.setattr(protection, "_d", lambda expected="": observed.append(expected) or True)
    monkeypatch.setattr(protection, "_e", lambda: True)
    monkeypatch.setattr(protection, "_b", lambda fast=False: False)

    assert protection._f(exe_hash="expected-hash", fast=True) is True
    assert observed == ["expected-hash"]


def test_chat_service_parses_common_chinese_play_tokens() -> None:
    from app.services.chat_service import ChatLogService

    service = ChatLogService()

    assert service._parse_bets("大100 小双 200 单 50") == [
        ("大", 100.0),
        ("小双", 200.0),
        ("单", 50.0),
    ]


def test_chat_service_parses_compact_amount_first_and_play_first_tokens() -> None:
    from app.services import chat_service as chat_service_module
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    play_a, play_b, play_c = chat_service_module.PLAY_TYPES[:3]
    content = f"100{play_a} {play_b}20 30{play_c}"

    assert service._parse_compact_bets(content, "Alice") == [
        ("Alice", play_a, 100.0),
        ("Alice", play_b, 20.0),
        ("Alice", play_c, 30.0),
    ]


def test_chat_service_extracts_direct_group_start_and_end_markers() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    service._is_group_member_robot = lambda group, sender_id, username: True
    service._decode_possible_frontend_ciphertext = lambda content: content
    service._extract_period = lambda content: "123456"

    start_msg = ChatMessage(
        ts=datetime(2026, 6, 10, 12, 0, 0),
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="涓嬫敞鏈熸暟 123456",
    )
    end_msg = ChatMessage(
        ts=datetime(2026, 6, 10, 12, 1, 0),
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="濡備笅璁㈠崟宸插彇娑? 123456",
    )

    assert service._extract_direct_group_marker(start_msg) == ("start", "123456")
    assert service._extract_direct_group_marker(end_msg) == ("end", "123456")


def test_chat_service_receipt_owner_prefers_recent_same_period_pending_record() -> None:
    from collections import defaultdict
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    now = datetime(2026, 6, 10, 12, 0, 30)
    event = SimpleNamespace(bettor="Alice")
    msg = ChatMessage(
        ts=now,
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="receipt",
    )
    pending_hit = SimpleNamespace(
        username="AliceUser",
        sender_id="alice-1",
        period="8888",
        ts=now - timedelta(seconds=10),
    )
    pending_miss = SimpleNamespace(
        username="OldUser",
        sender_id="old-1",
        period="7777",
        ts=now - timedelta(seconds=10),
    )

    owner = service._resolve_receipt_owner(
        event,
        msg,
        "8888",
        defaultdict(list, {"alice": [pending_miss, pending_hit]}),
        defaultdict(list),
    )

    assert owner == ("AliceUser", "alice-1")


def test_chat_service_extract_visual_rows_assigns_period_from_direct_group_marker() -> None:
    from datetime import datetime, timedelta

    from app.models import ChatMessage
    from app.services import chat_service as chat_service_module
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    service._is_group_member_robot = lambda group, sender_id, username: sender_id.startswith("robot")

    play = chat_service_module.PLAY_TYPES[0]
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 0),
            group="GroupA",
            username="Robot",
            sender_id="robot-1",
            content="涓嬫敞鏈熸暟 123456",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 10),
            group="GroupA",
            username="Alice",
            sender_id="alice-1",
            content=f"{play}100",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 20),
            group="GroupA",
            username="Robot",
            sender_id="robot-1",
            content="濡備笅璁㈠崟宸插彇娑? 123456",
        ),
    ]

    rows = service.extract_bet_visual_data(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="pc28",
        period_window_start=None,
        period_window_end=datetime(2026, 6, 10, 12, 1, 0) + timedelta(seconds=0),
        period_interval_sec=210,
    )

    assert rows == [
        {
            "time": datetime(2026, 6, 10, 12, 0, 10),
            "group": "GroupA",
            "username": "Alice",
            "bettor": "Alice",
            "play": play,
            "amount": 100.0,
            "kind": "bet",
            "period": "123456",
            "row_id": "1-0",
        }
    ]


def test_storage_service_load_returns_default_on_invalid_json(tmp_path: Path) -> None:
    from app.services.storage_service import JsonStore

    store = JsonStore("broken.json")
    store.path = tmp_path / "broken.json"
    store.path.write_text("{not-json", encoding="utf-8")

    assert store.load({"ok": True}) == {"ok": True}


def test_blocking_mixin_splits_chinese_punctuation() -> None:
    from app.ui.main_window_blocking import MainWindowBlockingMixin

    class DummyBlocking(MainWindowBlockingMixin):
        pass

    dummy = DummyBlocking()

    assert dummy._sanitize_block_names("Alice，Bob；Carol、Dave\nEve") == [
        "Alice",
        "Bob",
        "Carol",
        "Dave",
        "Eve",
    ]


def test_load_filtered_messages_uses_background_worker() -> None:
    from app.models import ParseOptions
    from app.ui.main_window_data import MainWindowDataMixin

    class FakeFuture:
        def __init__(self) -> None:
            self.callbacks: list[object] = []

        def add_done_callback(self, callback) -> None:
            self.callbacks.append(callback)

    class FakeWorker:
        def __init__(self) -> None:
            self.submissions: list[tuple[object, tuple[object, ...]]] = []

        def submit(self, fn, *args):
            self.submissions.append((fn, args))
            return FakeFuture()

    class FakeSignal:
        def __init__(self) -> None:
            self.emitted: list[object] = []

        def emit(self, payload: object) -> None:
            self.emitted.append(payload)

    class DummyStatus:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    class DummyWindow(MainWindowDataMixin):
        pass

    dummy = DummyWindow()
    dummy._data_worker = FakeWorker()
    dummy._load_result_ready = FakeSignal()
    dummy.status_label = DummyStatus()
    dummy._message_load_sequence = 0
    dummy._active_site = "pc28"
    dummy._last_message_cursor = {}
    dummy._build_load_options = lambda incremental: (Path("sample.db"), ParseOptions(), ("sig",), incremental)

    invoked_inline: list[tuple[object, ...]] = []
    dummy._run_load_pipeline = lambda *args: invoked_inline.append(args) or {"ok": True}
    dummy._apply_load_result = lambda result: (_ for _ in ()).throw(AssertionError("should not apply inline"))

    dummy._load_filtered_messages()

    assert invoked_inline == []
    assert len(dummy._data_worker.submissions) == 1
    assert dummy._load_result_ready.emitted == []


def test_main_window_data_gather_parse_options_includes_group_and_period_context() -> None:
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyItem:
        def __init__(self, checked: bool, group_id: str, group_name: str) -> None:
            self._checked = checked
            self._group_id = group_id
            self._group_name = group_name

        def checkState(self):
            return 2 if self._checked else 0

        def data(self, role):
            return {32: self._group_id, 33: self._group_name}.get(role)

        def text(self):
            return self._group_name

    class DummyList:
        def __init__(self) -> None:
            self.items = [DummyItem(True, "g1", "GroupA"), DummyItem(False, "g2", "GroupB")]

        def count(self):
            return len(self.items)

        def item(self, index):
            return self.items[index]

    class DummyCombo:
        def currentText(self):
            return "Alice"

    class DummyText:
        def text(self):
            return "9001"

    class DummyWindow(MainWindowDataMixin):
        def _blocked_names(self):
            return ["Blocked"]

    dummy = DummyWindow()
    dummy.group_list = DummyList()
    dummy.username_combo = DummyCombo()
    dummy.period_input = DummyText()
    dummy.group_block_rules = {"groupa": {"names": ["Blocked"]}}
    dummy._active_site = "pc28"

    options = dummy._gather_parse_options()

    assert options.username == "Alice"
    assert options.groups == ["GroupA"]
    assert options.group_ids == ["g1"]
    assert options.blocked_names == ["Blocked"]
    assert options.period_filter == "9001"
    assert options.site == "pc28"
    assert options.period_interval_sec > 0


def test_main_window_data_load_initial_state_restores_period_and_activation_gate() -> None:
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def __init__(self) -> None:
            self.items: list[str] = []
            self.current = ""

        def clear(self) -> None:
            self.items = []

        def addItems(self, values) -> None:
            self.items.extend(values)

        def setCurrentText(self, value: str) -> None:
            self.current = value

    class DummyEdit:
        def __init__(self) -> None:
            self.value = ""

        def setText(self, value: str) -> None:
            self.value = value

    class DummyDateTimeEdit:
        def __init__(self) -> None:
            self.value = None

        def setDateTime(self, value) -> None:
            self.value = value

    class DummyTabs:
        def __init__(self) -> None:
            self.current = None

        def setCurrentWidget(self, widget) -> None:
            self.current = widget

    class DummyLicenseService:
        def is_activated(self) -> bool:
            return False

    class DummyWindow(MainWindowDataMixin):
        def _refresh_block_rule_summary(self) -> None:
            self.block_summary_called = True

        def _refresh_block_rule_group_selector(self) -> None:
            self.block_group_called = True

        def _refresh_license_banner(self) -> None:
            self.license_banner_called = True

        def _resolve_database(self, silent=False) -> None:
            self.resolve_called = silent

    dummy = DummyWindow()
    dummy.analysis_page = object()
    dummy.settings = {
        "recent_usernames": ["Alice", "Bob"],
        "username": "Alice",
        "fallback_db_path": "D:/db.sqlite",
    }
    dummy.username_combo = DummyCombo()
    dummy.manual_db_edit = DummyEdit()
    dummy.resolved_path_edit = DummyEdit()
    dummy.period_input = DummyEdit()
    dummy.start_edit = DummyDateTimeEdit()
    dummy.end_edit = DummyDateTimeEdit()
    dummy.tabs = DummyTabs()
    dummy.license_page = object()
    dummy._manual_period_override = True
    dummy._query_period_override = "7788"
    dummy._require_activation = True
    dummy._active_site = ""
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy.username_combo.items == ["Alice", "Bob"]
    assert dummy.username_combo.current == "Alice"
    assert dummy.manual_db_edit.value == "D:/db.sqlite"
    assert dummy.period_input.value == "7788"
    assert dummy.tabs.current is dummy.license_page


def test_main_window_imports_qmessagebox_for_advanced_time_prompt() -> None:
    import app.ui.main_window as main_window

    assert hasattr(main_window, "QMessageBox")
