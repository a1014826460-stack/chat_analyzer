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


def test_chat_service_receipt_owner_matches_within_original_five_minute_window() -> None:
    from collections import defaultdict
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    now = datetime(2026, 6, 10, 12, 4, 0)
    event = SimpleNamespace(bettor="Alice")
    msg = ChatMessage(
        ts=now,
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="receipt",
    )
    pending = SimpleNamespace(
        username="AliceUser",
        sender_id="alice-1",
        period="8888",
        ts=now - timedelta(minutes=4),
    )

    owner = service._resolve_receipt_owner(
        event,
        msg,
        "8888",
        defaultdict(list, {"alice": [pending]}),
        defaultdict(list),
    )

    assert owner == ("AliceUser", "alice-1")


def test_chat_service_direct_group_marker_scan_uses_original_ten_minute_window() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    service._is_group_member_robot = lambda group, sender_id, username: sender_id.startswith("robot")

    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 0),
            group="GroupA",
            username="Robot",
            sender_id="robot-1",
            content="下注期数 123456",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 10),
            group="GroupA",
            username="Alice",
            sender_id="alice-1",
            content="大100",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 15, 0),
            group="GroupA",
            username="Bob",
            sender_id="bob-1",
            content="大200",
        ),
    ]

    assert service._build_direct_group_period_ranges(messages) == []


def test_chat_service_builds_direct_period_context_from_end_and_interval() -> None:
    from datetime import datetime, timedelta

    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    end = datetime(2026, 6, 10, 12, 3, 30)

    context = service._build_direct_period_context(
        site="pc28",
        period="123456",
        start=None,
        end=end,
        interval_sec=210,
    )

    assert context is not None
    assert context.period == "123456"
    assert context.start == end - timedelta(seconds=210)
    assert context.end == end


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
            "sender_id": "alice-1",
            "row_id": f"GroupA|Alice|123456|{play}|LATEST",
            "source_kind": "direct",
        }
    ]


def test_chat_service_receipt_group_keeps_latest_amount_per_bettor_period_play() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 0),
            group="白羊座交流群",
            username="Alice",
            sender_id="alice-1",
            content="大10 1234",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 20),
            group="白羊座交流群",
            username="Alice",
            sender_id="alice-1",
            content="大20 1234",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=0,
    )

    assert [(row["bettor"], row["period"], row["play"], row["amount"]) for row in rows] == [
        ("Alice", "1234", "大", 20.0)
    ]
    assert stats.totals == {"大": 20.0}


def test_chat_service_analyze_bets_returns_totals_by_group() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services import chat_service as chat_service_module
    from app.services.chat_service import ChatLogService

    play_a, play_b = chat_service_module.PLAY_TYPES[:2]
    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 11, 12, 0, 0),
            group="GroupA",
            username="Alice",
            sender_id="alice-1",
            content=f"{play_a}10 1001",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 11, 12, 0, 5),
            group="GroupB",
            username="Bob",
            sender_id="bob-1",
            content=f"{play_b}20 1001",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=0,
    )

    assert len(rows) == 2
    assert stats.totals == {play_a: 10.0, play_b: 20.0}
    assert stats.totals_by_group == {
        "GroupA": {play_a: 10.0},
        "GroupB": {play_b: 20.0},
    }


def test_stats_result_positional_constructor_keeps_legacy_order() -> None:
    from app.models import StatsResult

    stats = StatsResult({"A": 1.0}, 7, 9)

    assert stats.totals == {"A": 1.0}
    assert stats.matched_messages == 7
    assert stats.exported_records == 9
    assert stats.totals_by_group == {}


def test_chat_service_analyze_bets_splits_same_play_totals_by_group() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services import chat_service as chat_service_module
    from app.services.chat_service import ChatLogService

    play = chat_service_module.PLAY_TYPES[0]
    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 11, 12, 10, 0),
            group="GroupA",
            username="Alice",
            sender_id="alice-1",
            content=f"{play}10 1002",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 11, 12, 10, 5),
            group="GroupB",
            username="Bob",
            sender_id="bob-1",
            content=f"{play}20 1002",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=0,
    )

    assert len(rows) == 2
    assert stats.totals == {play: 30.0}
    assert stats.totals_by_group == {
        "GroupA": {play: 10.0},
        "GroupB": {play: 20.0},
    }


def test_chat_service_direct_group_accumulates_amount_per_bettor_period_play() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    service._is_group_member_robot = lambda group, sender_id, username: sender_id.startswith("robot")
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 0),
            group="普通群A",
            username="Robot",
            sender_id="robot-1",
            content="下注期数 1234",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 10),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="大10",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 20),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="大20",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 30),
            group="普通群A",
            username="Robot",
            sender_id="robot-1",
            content="如下订单已取消 1234",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=0,
    )

    assert [(row["bettor"], row["period"], row["play"], row["amount"]) for row in rows] == [
        ("Alice", "1234", "大", 30.0)
    ]
    assert stats.totals == {"大": 30.0}


def test_chat_service_cancel_removes_receipt_group_latest_row_without_residue() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 0),
            group="白羊座交流群",
            username="Alice",
            sender_id="alice-1",
            content="大10 1234",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 20),
            group="白羊座交流群",
            username="Alice",
            sender_id="alice-1",
            content="大20 1234",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 12, 0, 40),
            group="白羊座交流群",
            username="Alice",
            sender_id="alice-1",
            content="Alice 取消",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=0,
    )

    assert rows == []
    assert stats.totals == {}


def test_storage_service_load_returns_default_on_invalid_json(tmp_path: Path) -> None:
    from app.services.storage_service import JsonStore

    store = JsonStore("broken.json")
    store.path = tmp_path / "broken.json"
    store.path.write_text("{not-json", encoding="utf-8")

    assert store.load({"ok": True}) == {"ok": True}


def test_chat_service_loads_original_message_table_and_extracts_json_text(tmp_path: Path) -> None:
    import json
    import sqlite3
    from datetime import datetime

    from app.models import ParseOptions
    from app.services.chat_service import ChatLogService

    db_path = tmp_path / "msg_0.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        create table message (
            sid text,
            sender text,
            time integer,
            client_time integer,
            rand integer,
            element_descriptions text,
            content blob
        )
        """
    )
    con.execute(
        "insert into message values (?, ?, ?, ?, ?, ?, ?)",
        (
            "group-1",
            "alice-id",
            0,
            int(datetime(2026, 6, 10, 12, 0, 0).timestamp()),
            7,
            json.dumps({"text": "大100"}, ensure_ascii=False),
            b"",
        ),
    )
    con.commit()
    con.close()

    messages = ChatLogService().load_messages_from_sqlite(
        db_path,
        ParseOptions(
            group_ids=["group-1"],
            start_time=datetime(2026, 6, 10, 12, 0, 0),
            end_time=datetime(2026, 6, 10, 12, 5, 0),
        ),
    )

    assert len(messages) == 1
    assert messages[0].group == "group-1"
    assert messages[0].sender_id == "alice-id"
    assert messages[0].content == "大100"
    assert messages[0].raw_client_time == int(datetime(2026, 6, 10, 12, 0, 0).timestamp())
    assert messages[0].raw_rand == 7


def test_chat_service_sqlite_group_ids_filter_and_nested_content_decode(tmp_path: Path) -> None:
    import json
    import sqlite3
    from datetime import datetime

    from app.models import ParseOptions
    from app.services.chat_service import ChatLogService

    db_path = tmp_path / "msg_0.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        create table message (
            sid text,
            sender text,
            time integer,
            client_time integer,
            rand integer,
            element_descriptions text,
            content blob
        )
        """
    )
    rows = [
        (
            "group-1",
            "alice-id",
            0,
            int(datetime(2026, 6, 10, 12, 0, 0).timestamp() * 1_000_000),
            7,
            "",
            json.dumps({"textElement": {"content": "大100"}}, ensure_ascii=False).encode("utf-8"),
        ),
        (
            "group-2",
            "bob-id",
            0,
            int(datetime(2026, 6, 10, 12, 1, 0).timestamp()),
            8,
            json.dumps({"content": "小100"}, ensure_ascii=False),
            b"",
        ),
    ]
    con.executemany("insert into message values (?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()

    messages = ChatLogService().load_messages_from_sqlite(
        db_path,
        ParseOptions(
            group_ids=["group-1"],
            start_time=datetime(2026, 6, 10, 11, 55, 0),
            end_time=datetime(2026, 6, 10, 12, 5, 0),
        ),
    )

    assert len(messages) == 1
    assert messages[0].group == "group-1"
    assert messages[0].content == "大100"
    assert messages[0].ts == datetime(2026, 6, 10, 12, 0, 0)


def test_chat_service_extracts_plain_sqlite_content_without_base64_helper_crash(tmp_path: Path) -> None:
    import sqlite3
    from datetime import datetime

    from app.models import ParseOptions
    from app.services.chat_service import ChatLogService

    db_path = tmp_path / "msg_0.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        create table message (
            sid text,
            sender text,
            time integer,
            client_time integer,
            rand integer,
            element_descriptions text,
            content blob
        )
        """
    )
    con.execute(
        "insert into message values (?, ?, ?, ?, ?, ?, ?)",
        (
            "group-1",
            "alice-id",
            0,
            int(datetime(2026, 6, 10, 12, 2, 0).timestamp()),
            9,
            "",
            "普通聊天文本",
        ),
    )
    con.commit()
    con.close()

    messages = ChatLogService().load_messages_from_sqlite(
        db_path,
        ParseOptions(
            group_ids=["group-1"],
            start_time=datetime(2026, 6, 10, 12, 0, 0),
            end_time=datetime(2026, 6, 10, 12, 5, 0),
        ),
    )

    assert len(messages) == 1
    assert messages[0].content == "普通聊天文本"


def test_chat_service_sqlite_applies_default_twenty_minute_window(monkeypatch, tmp_path: Path) -> None:
    import sqlite3
    from datetime import datetime, timedelta

    from app.models import ParseOptions
    from app.services import chat_service as chat_service_module
    from app.services.chat_service import ChatLogService

    fixed_now = datetime(2026, 6, 10, 12, 0, 0)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(chat_service_module, "datetime", FixedDateTime)

    db_path = tmp_path / "msg_0.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        create table message (
            sid text,
            sender text,
            time integer,
            client_time integer,
            rand integer,
            element_descriptions text,
            content blob
        )
        """
    )
    rows = [
        (
            "group-1",
            "old-id",
            0,
            int((fixed_now - timedelta(minutes=25)).timestamp()),
            1,
            "",
            "旧消息",
        ),
        (
            "group-1",
            "new-id",
            0,
            int((fixed_now - timedelta(minutes=5)).timestamp()),
            2,
            "",
            "新消息",
        ),
    ]
    con.executemany("insert into message values (?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()

    messages = ChatLogService().load_messages_from_sqlite(db_path, ParseOptions(group_ids=["group-1"]))

    assert [msg.content for msg in messages] == ["新消息"]


def test_chat_service_lists_sqlite_groups_without_loading_messages(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    from app.services.chat_service import ChatLogService

    db_path = tmp_path / "msg_0.db"
    con = sqlite3.connect(db_path)
    con.execute("create table message (sid text)")
    con.executemany("insert into message values (?)", [("group-b",), ("group-a",), ("group-a",)])
    con.commit()
    con.close()

    service = ChatLogService()
    monkeypatch.setattr(
        service,
        "load_messages",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not load messages")),
    )

    groups = service.list_groups_from_db(db_path)

    assert [(group.group_id, group.group_name) for group in groups] == [
        ("group-a", "group-a"),
        ("group-b", "group-b"),
    ]


def test_fetch_date_parses_original_site_payload_shapes() -> None:
    from datetime import datetime

    from app.utils.fetch_date import extract_draw_info, site_label

    pc28 = extract_draw_info(
        "pc28",
        {"issue": [{"qishu": "1001", "time": "2026-06-10 12:00:00", "next": 1781093010}]},
    )
    macao = extract_draw_info(
        "macao",
        {"data": {"drawList": [{"qihao": "2001", "opentime": "2026-06-10 12:03:00"}]}},
    )
    australia = extract_draw_info(
        "australia",
        {"qi": "3001", "next": {"qi": "3002", "sec": 120}},
    )
    norway = extract_draw_info(
        "norway",
        {"lottery_data": [{"expect": "4001", "nextexpect": "4002", "opentime": "2026-06-10 12:06:00", "next": 1781093190}]},
    )

    assert site_label("macao") == "澳门"
    assert site_label("australia") == "澳洲"
    assert site_label("norway") == "挪威"
    assert pc28.current_period == "1001"
    assert pc28.current_time == datetime(2026, 6, 10, 12, 0, 0)
    assert pc28.next_period == "1002"
    assert macao.current_period == "2001"
    assert macao.next_period == "2002"
    assert australia.current_period == "3001"
    assert australia.next_period == "3002"
    assert australia.next_countdown == 120
    assert norway.current_period == "4001"
    assert norway.next_period == "4002"


def test_extract_draw_info_falls_back_to_last_good_pc28_when_issue_list_is_empty() -> None:
    from app.utils import fetch_date

    fetch_date._last_good_draw.clear()
    first = fetch_date.extract_draw_info(
        "pc28",
        {"issue": [{"qishu": "1001", "time": "2026-06-10 12:00:00", "next": 1781093010}]},
    )

    fallback = fetch_date.extract_draw_info("pc28", {"issue": []})

    assert first.current_period == "1001"
    assert fallback.current_period == "1001"
    assert fallback.next_period == "1002"
    assert fallback.next_countdown >= 0


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


def test_main_window_data_load_groups_uses_qt_check_state_enum(tmp_path: Path) -> None:
    import sqlite3

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QListWidget

    from app.ui.main_window_data import MainWindowDataMixin

    db_path = tmp_path / "msg_0.db"
    con = sqlite3.connect(db_path)
    con.execute("create table message (sid text)")
    con.execute("insert into message values (?)", ("group-1",))
    con.commit()
    con.close()

    class DummyWindow(MainWindowDataMixin):
        def _current_source_path(self):
            return db_path

        def _refresh_block_rule_group_selector(self) -> None:
            self.refreshed = True

    app = QApplication.instance() or QApplication([])
    dummy = DummyWindow()
    dummy.group_list = QListWidget()
    dummy.chat_service = __import__("app.services.chat_service", fromlist=["ChatLogService"]).ChatLogService()

    dummy._load_groups_from_current_source()

    assert dummy.group_list.count() == 1
    assert dummy.group_list.item(0).checkState() == Qt.Checked
    assert dummy.refreshed is True


def test_main_window_data_gather_parse_options_includes_group_and_period_context() -> None:
    from PySide6.QtCore import Qt

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyItem:
        def __init__(self, checked: bool, group_id: str, group_name: str) -> None:
            self._checked = checked
            self._group_id = group_id
            self._group_name = group_name

        def checkState(self):
            return Qt.Checked if self._checked else Qt.Unchecked

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


def test_main_window_data_gather_parse_options_does_not_flatten_group_rules_into_global_names() -> None:
    from PySide6.QtCore import Qt

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyItem:
        def __init__(self, checked: bool, group_id: str, group_name: str) -> None:
            self._checked = checked
            self._group_id = group_id
            self._group_name = group_name

        def checkState(self):
            return Qt.Checked if self._checked else Qt.Unchecked

        def data(self, role):
            return {32: self._group_id, 33: self._group_name}.get(role)

        def text(self):
            return self._group_name

    class DummyList:
        def __init__(self) -> None:
            self.items = [DummyItem(True, "g1", "GroupA")]

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
        def _global_block_names(self):
            return []

    dummy = DummyWindow()
    dummy.group_list = DummyList()
    dummy.username_combo = DummyCombo()
    dummy.period_input = DummyText()
    dummy.group_block_rules = {"g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}}
    dummy._active_site = "pc28"

    options = dummy._gather_parse_options()

    assert options.blocked_names == []
    assert options.global_block_names == []
    assert options.blocked_names_by_group == {
        "g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}
    }


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


def test_main_window_data_load_initial_state_restores_period_override_map() -> None:
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
            return None

        def _refresh_block_rule_group_selector(self) -> None:
            return None

        def _refresh_license_banner(self) -> None:
            return None

        def _resolve_database(self, silent=False) -> None:
            self.resolve_called = silent

    dummy = DummyWindow()
    dummy.analysis_page = object()
    dummy.settings = {
        "recent_usernames": ["Alice"],
        "username": "Alice",
        "fallback_db_path": "D:/db.sqlite",
        "query_period_overrides_by_site": {"pc28": "7788"},
    }
    dummy.username_combo = DummyCombo()
    dummy.manual_db_edit = DummyEdit()
    dummy.resolved_path_edit = DummyEdit()
    dummy.period_input = DummyEdit()
    dummy.start_edit = DummyDateTimeEdit()
    dummy.end_edit = DummyDateTimeEdit()
    dummy.tabs = DummyTabs()
    dummy.license_page = object()
    dummy._query_period_override = ""
    dummy._manual_period_override = False
    dummy._query_period_overrides_by_site = {}
    dummy._active_site = "pc28"
    dummy._require_activation = True
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy._query_period_overrides_by_site == {"pc28": "7788"}
    assert dummy.period_input.value == "7788"


def test_main_window_data_load_initial_state_seeds_legacy_period_into_active_site() -> None:
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
            return None

        def _refresh_block_rule_group_selector(self) -> None:
            return None

        def _refresh_license_banner(self) -> None:
            return None

        def _resolve_database(self, silent=False) -> None:
            self.resolve_called = silent

    dummy = DummyWindow()
    dummy.analysis_page = object()
    dummy.settings = {
        "recent_usernames": ["Alice"],
        "username": "Alice",
        "fallback_db_path": "D:/db.sqlite",
        "query_period_override": "7788",
        "manual_period_override": True,
    }
    dummy.username_combo = DummyCombo()
    dummy.manual_db_edit = DummyEdit()
    dummy.resolved_path_edit = DummyEdit()
    dummy.period_input = DummyEdit()
    dummy.start_edit = DummyDateTimeEdit()
    dummy.end_edit = DummyDateTimeEdit()
    dummy.tabs = DummyTabs()
    dummy.license_page = object()
    dummy._query_period_override = "7788"
    dummy._manual_period_override = True
    dummy._query_period_overrides_by_site = {}
    dummy._active_site = "macao"
    dummy._require_activation = True
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy._query_period_overrides_by_site == {"macao": "7788"}
    assert dummy.period_input.value == "7788"


def test_main_window_advanced_time_toggle_shows_filter_frame() -> None:
    from types import SimpleNamespace

    from app.ui.main_window import MainWindow

    class DummyFrame:
        def __init__(self) -> None:
            self.visible = False

        def isVisible(self) -> bool:
            return self.visible

        def setVisible(self, value: bool) -> None:
            self.visible = value

    class DummyButton:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    dummy = SimpleNamespace(
        advanced_time_frame=DummyFrame(),
        advanced_time_toggle=DummyButton(),
    )

    MainWindow._toggle_advanced_time(dummy)

    assert dummy.advanced_time_frame.visible is True
    assert dummy.advanced_time_toggle.text == "- 高级时间筛选"


def test_main_window_layout_splitter_can_expand_left_panel() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    from app.ui.main_window_layout import MainWindowLayoutMixin

    class DummyWindow(QWidget, MainWindowLayoutMixin):
        def __init__(self) -> None:
            super().__init__()
            self.analysis_page = QWidget()
            self._lock_threshold_sec = 20

        def _resolve_database(self, *args, **kwargs):
            return None

        def _pick_manual_data_source(self):
            return None

        def _load_manual_data_source(self):
            return None

        def _toggle_advanced_time(self):
            return None

        def _handle_group_item_changed(self, *args):
            return None

        def _set_checked_state(self, *args):
            return None

        def _invert_checked_state(self, *args):
            return None

        def _on_block_group_changed(self, *args):
            return None

        def _apply_global_block_names_from_editor(self):
            return None

        def _clear_global_block_names(self):
            return None

        def _apply_block_rule_from_editor(self):
            return None

        def _clear_block_rule_for_selected_group(self):
            return None

        def _on_period_input_changed(self):
            return None

        def _on_lock_threshold_changed(self, *args):
            return None

        def _prev_page(self):
            return None

        def _next_page(self):
            return None

    app = QApplication.instance() or QApplication([])
    dummy = DummyWindow()
    dummy._build_analysis_page()
    dummy.analysis_page.resize(1180, 720)
    dummy.analysis_page.show()
    app.processEvents()

    dummy.main_splitter.setSizes([760, 380])
    app.processEvents()

    sizes = dummy.main_splitter.sizes()
    assert sizes[0] >= 700
    assert dummy.main_splitter.widget(1).minimumWidth() <= 380
    dummy.analysis_page.close()


def test_main_window_left_controls_are_not_narrowly_capped() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    from app.ui.main_window_layout import MainWindowLayoutMixin

    class DummyWindow(QWidget, MainWindowLayoutMixin):
        def __init__(self) -> None:
            super().__init__()
            self.analysis_page = QWidget()
            self._lock_threshold_sec = 20

        def _resolve_database(self, *args, **kwargs):
            return None

        def _pick_manual_data_source(self):
            return None

        def _load_manual_data_source(self):
            return None

        def _toggle_advanced_time(self):
            return None

        def _handle_group_item_changed(self, *args):
            return None

        def _set_checked_state(self, *args):
            return None

        def _invert_checked_state(self, *args):
            return None

        def _on_block_group_changed(self, *args):
            return None

        def _apply_global_block_names_from_editor(self):
            return None

        def _clear_global_block_names(self):
            return None

        def _apply_block_rule_from_editor(self):
            return None

        def _clear_block_rule_for_selected_group(self):
            return None

        def _on_period_input_changed(self):
            return None

        def _on_lock_threshold_changed(self, *args):
            return None

        def _prev_page(self):
            return None

        def _next_page(self):
            return None

    app = QApplication.instance() or QApplication([])
    dummy = DummyWindow()
    dummy._build_analysis_page()

    assert dummy.resolved_path_edit.maximumWidth() >= 1600
    assert dummy.manual_db_edit.maximumWidth() >= 1600
    assert dummy.block_names_edit.maximumHeight() <= 110
    assert dummy.block_rule_summary_view.maximumHeight() <= 140
    dummy.analysis_page.close()


def test_main_window_layout_uses_readable_chinese_labels() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget

    from app.ui.main_window_layout import MainWindowLayoutMixin

    class DummyWindow(QWidget, MainWindowLayoutMixin):
        def __init__(self) -> None:
            super().__init__()
            self.analysis_page = QWidget()
            self._lock_threshold_sec = 20

        def _resolve_database(self, *args, **kwargs):
            return None

        def _pick_manual_data_source(self):
            return None

        def _load_manual_data_source(self):
            return None

        def _toggle_advanced_time(self):
            return None

        def _handle_group_item_changed(self, *args):
            return None

        def _set_checked_state(self, *args):
            return None

        def _invert_checked_state(self, *args):
            return None

        def _on_block_group_changed(self, *args):
            return None

        def _apply_global_block_names_from_editor(self):
            return None

        def _clear_global_block_names(self):
            return None

        def _apply_block_rule_from_editor(self):
            return None

        def _clear_block_rule_for_selected_group(self):
            return None

        def _on_period_input_changed(self):
            return None

        def _on_lock_threshold_changed(self, *args):
            return None

        def _prev_page(self):
            return None

        def _next_page(self):
            return None

    app = QApplication.instance() or QApplication([])
    dummy = DummyWindow()
    dummy._build_analysis_page()

    button_texts = {button.text() for button in dummy.analysis_page.findChildren(QPushButton)}

    assert {"自动定位数据库", "浏览", "使用数据源", "全选", "反选", "上一页", "下一页"} <= button_texts
    assert dummy.resolved_path_edit.placeholderText() == "自动解析或手动选择的数据源路径"
    assert dummy.manual_db_edit.placeholderText() == "自动定位失败时选择 msg_0.db / sqlite / txt"
    dummy.analysis_page.close()


def test_realtime_and_chart_status_labels_are_chinese() -> None:
    import os
    from types import SimpleNamespace

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import ChartWindow
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

        def setStyleSheet(self, value: str) -> None:
            self.style = value

    class DummyWindow(MainWindowRealtimeMixin):
        pass

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart.set_status("running")
    chart.set_status_seconds(30)
    assert "实时刷新" in chart.status_label.text()

    dummy = DummyWindow()
    dummy.chart_window = chart
    dummy._active_site = "pc28"
    dummy._draw_infos = {"pc28": SimpleNamespace(next_countdown=30)}
    dummy._stats_locked = False
    dummy.current_visual_rows = [{"group": "G"}]
    dummy.lock_status_label = DummyLabel()
    dummy.auto_refresh_label = DummyLabel()
    dummy._sync_chart_status()

    assert "实时刷新" in dummy.lock_status_label.text
    assert dummy.auto_refresh_label.text == "运行中"


def test_main_window_realtime_period_override_is_stored_per_site() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = ""
            self.blocked = False

        def blockSignals(self, value: bool) -> None:
            self.blocked = value

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

    dummy = SimpleNamespace(
        _active_site="pc28",
        _query_period_overrides_by_site={"pc28": "7788", "macao": "8899"},
        _query_period_override="",
        _manual_period_override=False,
        _draw_infos={
            "pc28": DrawInfo(current_period="1001", next_period="1002"),
            "macao": DrawInfo(current_period="2001", next_period="2002"),
        },
        period_input=DummyPeriodInput(),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
        lock_status_label=SimpleNamespace(setText=lambda value: None),
        auto_refresh_label=SimpleNamespace(setText=lambda value: None, setStyleSheet=lambda value: None),
        chart_window=SimpleNamespace(set_status=lambda *args, **kwargs: None, set_status_seconds=lambda *args, **kwargs: None),
        current_visual_rows=[],
        _stats_locked=False,
        _last_message_cursor={},
        _awaiting_next_period=False,
        _format_countdown=lambda value: "00:00",
        _set_status=lambda *args, **kwargs: None,
        _load_filtered_messages=lambda: None,
        _sync_chart_status=lambda: None,
    )
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._has_manual_period_override = lambda: MainWindowRealtimeMixin._has_manual_period_override(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._refresh_active_site_info = lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy)

    MainWindowRealtimeMixin._refresh_active_site_info(dummy)
    assert dummy.period_input.value == "7788"

    MainWindowRealtimeMixin._select_site(dummy, "macao")
    assert dummy.period_input.value == "8899"
    assert dummy._query_period_overrides_by_site["pc28"] == "7788"


def test_main_window_realtime_select_site_seeds_legacy_period_into_first_selected_site() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = ""

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

    dummy = SimpleNamespace(
        _active_site="",
        _query_period_overrides_by_site={},
        _query_period_override="7788",
        _manual_period_override=True,
        _draw_infos={"macao": DrawInfo(current_period="2001", next_period="2002")},
        period_input=DummyPeriodInput(),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
        lock_status_label=SimpleNamespace(setText=lambda value: None),
        auto_refresh_label=SimpleNamespace(setText=lambda value: None, setStyleSheet=lambda value: None),
        chart_window=SimpleNamespace(set_status=lambda *args, **kwargs: None, set_status_seconds=lambda *args, **kwargs: None),
        current_visual_rows=[],
        _stats_locked=False,
        _last_message_cursor={},
        _awaiting_next_period=False,
        _format_countdown=lambda value: "00:00",
        _set_status=lambda *args, **kwargs: None,
        _load_filtered_messages=lambda: None,
        _sync_chart_status=lambda: None,
        _save_settings=lambda: None,
    )
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._has_manual_period_override = lambda: MainWindowRealtimeMixin._has_manual_period_override(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._refresh_active_site_info = lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy)

    MainWindowRealtimeMixin._select_site(dummy, "macao")

    assert dummy._query_period_overrides_by_site == {"macao": "7788"}
    assert dummy.period_input.value == "7788"


def test_main_window_realtime_select_site_saves_after_legacy_period_migration() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = ""

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

    save_calls: list[str] = []
    dummy = SimpleNamespace(
        _active_site="",
        _query_period_overrides_by_site={},
        _query_period_override="7788",
        _manual_period_override=True,
        _draw_infos={"macao": DrawInfo(current_period="2001", next_period="2002")},
        period_input=DummyPeriodInput(),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
        lock_status_label=SimpleNamespace(setText=lambda value: None),
        auto_refresh_label=SimpleNamespace(setText=lambda value: None, setStyleSheet=lambda value: None),
        chart_window=SimpleNamespace(set_status=lambda *args, **kwargs: None, set_status_seconds=lambda *args, **kwargs: None),
        current_visual_rows=[],
        _stats_locked=False,
        _last_message_cursor={},
        _awaiting_next_period=False,
        _format_countdown=lambda value: "00:00",
        _set_status=lambda *args, **kwargs: None,
        _load_filtered_messages=lambda: None,
        _sync_chart_status=lambda: None,
        _save_settings=lambda: save_calls.append("saved"),
    )
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._has_manual_period_override = lambda: MainWindowRealtimeMixin._has_manual_period_override(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._refresh_active_site_info = lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy)

    MainWindowRealtimeMixin._select_site(dummy, "macao")

    assert save_calls == ["saved"]


def test_main_window_realtime_select_site_preserves_legacy_period_on_previous_site() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = ""

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

    dummy = SimpleNamespace(
        _active_site="pc28",
        _query_period_overrides_by_site={},
        _query_period_override="7788",
        _manual_period_override=True,
        _draw_infos={
            "pc28": DrawInfo(current_period="1001", next_period="1002"),
            "macao": DrawInfo(current_period="2001", next_period="2002"),
        },
        period_input=DummyPeriodInput(),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
        lock_status_label=SimpleNamespace(setText=lambda value: None),
        auto_refresh_label=SimpleNamespace(setText=lambda value: None, setStyleSheet=lambda value: None),
        chart_window=SimpleNamespace(set_status=lambda *args, **kwargs: None, set_status_seconds=lambda *args, **kwargs: None),
        current_visual_rows=[],
        _stats_locked=False,
        _last_message_cursor={},
        _awaiting_next_period=False,
        _format_countdown=lambda value: "00:00",
        _set_status=lambda *args, **kwargs: None,
        _load_filtered_messages=lambda: None,
        _sync_chart_status=lambda: None,
        _save_settings=lambda: None,
    )
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._has_manual_period_override = lambda: MainWindowRealtimeMixin._has_manual_period_override(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._refresh_active_site_info = lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy)

    MainWindowRealtimeMixin._select_site(dummy, "macao")

    assert dummy._query_period_overrides_by_site == {"pc28": "7788"}
    assert dummy._query_period_override == ""
    assert dummy.period_input.value == "2002"


def test_logging_config_debug_sets_root_to_debug(tmp_path: Path, monkeypatch) -> None:
    import logging

    from app.utils import logging_config

    monkeypatch.setattr(logging_config, "user_data_dir", lambda: tmp_path)

    logging_config.configure(debug=True)

    assert logging.getLogger().level == logging.DEBUG
    assert (tmp_path / "chat_analyzer.log").exists()


def test_main_window_status_helper_updates_label_and_logs(caplog) -> None:
    from types import SimpleNamespace

    from app.ui.main_window import MainWindow

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    dummy = SimpleNamespace(status_label=DummyLabel())

    with caplog.at_level("INFO"):
        MainWindow._set_status(dummy, "正在测试按钮反馈", log_level="info")

    assert dummy.status_label.text == "正在测试按钮反馈"
    assert "正在测试按钮反馈" in caplog.text


def test_resolve_database_without_username_reports_readable_feedback(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def currentText(self) -> str:
            return ""

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.ui.main_window_data.QMessageBox.information",
        lambda _parent, title, text: messages.append((title, text)),
    )

    dummy = SimpleNamespace(username_combo=DummyCombo())

    MainWindowDataMixin._resolve_database(dummy, silent=False)

    assert messages == [("缺少用户名", "请先输入用户名。")]


def test_load_manual_data_source_missing_file_reports_readable_feedback(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyEdit:
        def text(self) -> str:
            return "Z:/missing/msg_0.db"

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.ui.main_window_data.QMessageBox.warning",
        lambda _parent, title, text: messages.append((title, text)),
    )

    dummy = SimpleNamespace(manual_db_edit=DummyEdit())

    MainWindowDataMixin._load_manual_data_source(dummy)

    assert messages == [("文件不存在", "选择的数据源不存在。")]


def test_block_rule_save_and_clear_use_readable_feedback() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_blocking import MainWindowBlockingMixin

    class DummyEdit:
        def __init__(self, text: str = "") -> None:
            self._text = text
            self.cleared = False

        def toPlainText(self) -> str:
            return self._text

        def clear(self) -> None:
            self.cleared = True

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    class DummyWindow(MainWindowBlockingMixin):
        def _current_block_group_payload(self):
            return {"group_id": "g1", "group_name": "测试群"}

        def _set_group_block_rules(self, rules):
            self.group_block_rules = rules

        def _refresh_block_rule_summary(self) -> None:
            return None

        def _save_settings(self) -> None:
            return None

        def _reload_messages_after_block_rule_change(self) -> None:
            return None

    dummy = DummyWindow()
    dummy.group_block_rules = {}
    dummy.block_names_edit = DummyEdit("Alice, Bob")
    dummy.block_rule_status_label = DummyLabel()

    MainWindowBlockingMixin._apply_block_rule_from_editor(dummy)
    assert dummy.block_rule_status_label.text == "已保存测试群的 2 个屏蔽名称。"

    MainWindowBlockingMixin._clear_block_rule_for_selected_group(dummy)
    assert dummy.block_names_edit.cleared is True
    assert dummy.block_rule_status_label.text == "已清空测试群的屏蔽名称。"


def test_main_window_actions_save_settings_persists_global_block_names_separately() -> None:
    from app.ui.main_window_actions import MainWindowActionsMixin

    saved_payloads: list[dict[str, object]] = []

    class DummyService:
        def save(self, payload):
            saved_payloads.append(payload)

    class DummyCombo:
        def currentText(self):
            return "Alice"

        def count(self):
            return 1

        def itemText(self, index: int):
            return "Alice"

    class DummyText:
        def text(self):
            return ""

    class DummyWindow(MainWindowActionsMixin):
        def _current_source_path(self):
            return None

        def _selected_group_ids(self):
            return ["g1"]

        def _selected_block_group_key(self):
            return "g1"

        def _global_block_names(self):
            return ["Robot"]

    dummy = DummyWindow()
    dummy.settings_service = DummyService()
    dummy.username_combo = DummyCombo()
    dummy.resolved_path_edit = DummyText()
    dummy.manual_db_edit = DummyText()
    dummy.settings = {"export_dir": "", "proxy_enabled": False, "proxy_http": "", "proxy_https": ""}
    dummy.group_block_rules = {"g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}}
    dummy._lock_threshold_sec = 20
    dummy._is_first_launch = False
    dummy._query_period_overrides_by_site = {}
    dummy._query_period_override = ""
    dummy._manual_period_override = False

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["global_block_names"] == ["Robot"]
    assert payload["blocked_names"] == ["Robot"]
    assert payload["blocked_names_by_group"] == {
        "g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}
    }


def test_main_window_does_not_promote_legacy_blocked_names_when_group_rules_exist(monkeypatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow

    class DummySettingsService:
        def load(self) -> dict:
            return {
                "blocked_names": ["LegacyName"],
                "blocked_names_by_group": {
                    "g1": {"group_id": "g1", "group_name": "GroupA", "names": ["LegacyName"]}
                },
                "lock_threshold_sec": 20,
                "is_first_launch": False,
                "query_period_override": "",
                "manual_period_override": False,
            }

    monkeypatch.setattr("app.ui.main_window.SettingsService", lambda: DummySettingsService())
    monkeypatch.setattr(MainWindow, "_apply_icon", lambda self: None)
    monkeypatch.setattr(MainWindow, "_build_license_page", lambda self: None)
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(MainWindow, "_refresh_license_banner", lambda self: None)
    monkeypatch.setattr(MainWindow, "_activate_and_launch", lambda self: None)
    monkeypatch.setattr("app.ui.main_window.set_proxy_settings", lambda settings: None)

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.global_block_names == []

    window.close()


def test_main_window_preserves_legacy_global_block_names_not_present_in_group_rules(monkeypatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow

    class DummySettingsService:
        def load(self) -> dict:
            return {
                "blocked_names": ["Robot", "LegacyName"],
                "blocked_names_by_group": {
                    "g1": {"group_id": "g1", "group_name": "GroupA", "names": ["LegacyName"]}
                },
                "lock_threshold_sec": 20,
                "is_first_launch": False,
                "query_period_override": "",
                "manual_period_override": False,
            }

    monkeypatch.setattr("app.ui.main_window.SettingsService", lambda: DummySettingsService())
    monkeypatch.setattr(MainWindow, "_apply_icon", lambda self: None)
    monkeypatch.setattr(MainWindow, "_build_license_page", lambda self: None)
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(MainWindow, "_refresh_license_banner", lambda self: None)
    monkeypatch.setattr(MainWindow, "_activate_and_launch", lambda self: None)
    monkeypatch.setattr("app.ui.main_window.set_proxy_settings", lambda settings: None)

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.global_block_names == ["Robot"]

    window.close()


def test_main_window_promotes_legacy_blocked_names_only_when_group_rules_are_empty(monkeypatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow

    class DummySettingsService:
        def load(self) -> dict:
            return {
                "blocked_names": ["LegacyName"],
                "blocked_names_by_group": {},
                "lock_threshold_sec": 20,
                "is_first_launch": False,
                "query_period_override": "",
                "manual_period_override": False,
            }

    monkeypatch.setattr("app.ui.main_window.SettingsService", lambda: DummySettingsService())
    monkeypatch.setattr(MainWindow, "_apply_icon", lambda self: None)
    monkeypatch.setattr(MainWindow, "_build_license_page", lambda self: None)
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(MainWindow, "_refresh_license_banner", lambda self: None)
    monkeypatch.setattr(MainWindow, "_activate_and_launch", lambda self: None)
    monkeypatch.setattr("app.ui.main_window.set_proxy_settings", lambda settings: None)

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.global_block_names == ["LegacyName"]

    window.close()


def test_main_window_actions_save_settings_preserves_existing_unknown_keys() -> None:
    from app.ui.main_window_actions import MainWindowActionsMixin

    saved_payloads: list[dict[str, object]] = []

    class DummyService:
        def save(self, payload):
            saved_payloads.append(payload)

    class DummyCombo:
        def currentText(self):
            return "Alice"

        def count(self):
            return 1

        def itemText(self, index: int):
            return "Alice"

    class DummyText:
        def text(self):
            return ""

    class DummyWindow(MainWindowActionsMixin):
        def _current_source_path(self):
            return None

        def _selected_group_ids(self):
            return ["g1"]

        def _selected_block_group_key(self):
            return "g1"

        def _global_block_names(self):
            return ["Robot"]

    dummy = DummyWindow()
    dummy.settings_service = DummyService()
    dummy.username_combo = DummyCombo()
    dummy.resolved_path_edit = DummyText()
    dummy.manual_db_edit = DummyText()
    dummy.settings = {
        "export_dir": "",
        "proxy_enabled": False,
        "proxy_http": "",
        "proxy_https": "",
        "query_period_overrides_by_site": {"pc28": "7788"},
        "custom_keep": "keep-me",
    }
    dummy.group_block_rules = {"g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}}
    dummy._lock_threshold_sec = 20
    dummy._is_first_launch = False
    dummy._query_period_overrides_by_site = {"pc28": "7788"}
    dummy._query_period_override = ""
    dummy._manual_period_override = False

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["query_period_overrides_by_site"] == {"pc28": "7788"}
    assert payload["custom_keep"] == "keep-me"


def test_main_window_actions_save_settings_preserves_legacy_period_until_migrated() -> None:
    from app.ui.main_window_actions import MainWindowActionsMixin

    saved_payloads: list[dict[str, object]] = []

    class DummyService:
        def save(self, payload):
            saved_payloads.append(payload)

    class DummyCombo:
        def currentText(self):
            return "Alice"

        def count(self):
            return 1

        def itemText(self, index: int):
            return "Alice"

    class DummyText:
        def text(self):
            return ""

    class DummyWindow(MainWindowActionsMixin):
        def _current_source_path(self):
            return None

        def _selected_group_ids(self):
            return ["g1"]

        def _selected_block_group_key(self):
            return "g1"

        def _global_block_names(self):
            return []

    dummy = DummyWindow()
    dummy.settings_service = DummyService()
    dummy.username_combo = DummyCombo()
    dummy.resolved_path_edit = DummyText()
    dummy.manual_db_edit = DummyText()
    dummy.settings = {"export_dir": "", "proxy_enabled": False, "proxy_http": "", "proxy_https": ""}
    dummy.group_block_rules = {}
    dummy._lock_threshold_sec = 20
    dummy._is_first_launch = False
    dummy._query_period_overrides_by_site = {}
    dummy._query_period_override = "7788"
    dummy._manual_period_override = True

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["query_period_overrides_by_site"] == {}
    assert payload["query_period_override"] == "7788"
    assert payload["manual_period_override"] is True


def test_main_window_global_block_ui_uses_chinese_text(monkeypatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window import MainWindow

    monkeypatch.setattr(main_window_realtime, "site_list", lambda: ["pc28"])
    monkeypatch.setattr(main_window_realtime, "site_label", lambda site: "PC28")
    monkeypatch.setattr(
        main_window_realtime,
        "fetch_all_draw_infos",
        lambda: {"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=30)},
    )
    monkeypatch.setattr(
        main_window_realtime,
        "extract_draw_info",
        lambda site: DrawInfo(current_period="1001", next_period="1002", next_countdown=30),
    )

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    label_texts = [label.text() for label in window.findChildren(type(window.active_site_label))]

    assert "全局" in label_texts
    assert window.global_block_save_btn.text() == "保存全局"
    assert window.global_block_clear_btn.text() == "清空全局"
    assert window.global_block_names_edit.placeholderText() == "全局屏蔽名称，每行一个，也可用逗号/分号分隔"
    window.close()


def test_global_block_rule_feedback_uses_chinese_text() -> None:
    from app.ui.main_window_blocking import MainWindowBlockingMixin

    class DummyEdit:
        def __init__(self, text: str = "") -> None:
            self._text = text
            self.value = ""
            self.cleared = False

        def toPlainText(self) -> str:
            return self._text

        def setPlainText(self, value: str) -> None:
            self.value = value

        def clear(self) -> None:
            self.cleared = True

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    class DummySummary:
        def __init__(self) -> None:
            self.text = ""

        def setPlainText(self, value: str) -> None:
            self.text = value

    class DummyWindow(MainWindowBlockingMixin):
        def _save_settings(self) -> None:
            return None

        def _reload_messages_after_block_rule_change(self) -> None:
            return None

    dummy = DummyWindow()
    dummy.global_block_names = []
    dummy.group_block_rules = {}
    dummy.global_block_names_edit = DummyEdit("Robot, Spam")
    dummy.block_rule_status_label = DummyLabel()
    dummy.block_rule_summary_view = DummySummary()

    MainWindowBlockingMixin._apply_global_block_names_from_editor(dummy)
    assert dummy.block_rule_status_label.text == "已保存 2 个全局屏蔽名称。"
    assert dummy.block_rule_summary_view.text == "全局: Robot, Spam"

    MainWindowBlockingMixin._clear_global_block_names(dummy)
    assert dummy.global_block_names_edit.cleared is True
    assert dummy.block_rule_status_label.text == "已清空全局屏蔽名称。"


def test_chat_service_global_block_list_applies_to_all_groups() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 11, 10, 0, 0),
            group="GroupA",
            username="Robot",
            sender_id="robot-a",
            content="澶?0 1001",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 11, 10, 0, 5),
            group="GroupB",
            username="Robot",
            sender_id="robot-b",
            content="澶?0 1001",
        ),
    ]

    filtered = service.filter_blocked_messages(messages, blocked_names=["Robot"], blocked_ids=[])

    assert filtered == []


def test_main_window_safe_buttons_click_without_crashing(monkeypatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

    from app.models import DrawInfo
    from app.services.account_resolver import ResolvedDatabase
    from app.ui import main_window_realtime
    from app.ui.main_window import MainWindow

    monkeypatch.setattr(main_window_realtime, "site_list", lambda: ["pc28"])
    monkeypatch.setattr(main_window_realtime, "site_label", lambda site: "PC28")
    monkeypatch.setattr(
        main_window_realtime,
        "fetch_all_draw_infos",
        lambda: {"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=30)},
    )
    monkeypatch.setattr(
        main_window_realtime,
        "extract_draw_info",
        lambda site: DrawInfo(current_period="1001", next_period="1002", next_countdown=30),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "about", lambda *args, **kwargs: None)

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.account_resolver.resolve = lambda username: ResolvedDatabase(
        account_name=username,
        accid="acc",
        im_appid="app",
        config_dir=Path.cwd(),
        im_db=Path("missing.db"),
        msg_db=Path("missing.db"),
    )
    window.chat_service.list_groups_from_db = lambda source_path: []
    window._load_filtered_messages = lambda: window._set_status("已触发加载消息", "info")
    window.username_combo.setCurrentText("tester")

    excluded = {
        "浏览",
        "Activate",
        "Copy machine code",
    }
    clicked: list[str] = []
    for button in window.findChildren(QPushButton):
        text = button.text()
        if text in excluded:
            continue
        button.click()
        app.processEvents()
        clicked.append(text)

    assert "自动定位数据库" in clicked
    assert "切换" in clicked
    assert window.status_label.text()
    window.close()


def test_license_generator_dialog_buttons_have_readable_feedback() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from app.ui.license_generator_dialog import LicenseGeneratorDialog

    class DummyLicenseService:
        def get_machine_code(self) -> str:
            return "machine-123456"

        def generate_key(self, value: int, machine_code: str, unit: str = "days") -> str:
            return f"KEY-{machine_code}-{unit}-{value}"

    app = QApplication.instance() or QApplication([])
    dialog = LicenseGeneratorDialog(DummyLicenseService())

    button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
    assert {"生成", "复制机器码"} <= button_texts

    for button in dialog.findChildren(QPushButton):
        if button.text() == "生成":
            button.click()
            break
    assert dialog.output_edit.toPlainText().startswith("KEY-machine-123456")
    assert "已为 machine-" in dialog.status_label.text()

    for button in dialog.findChildren(QPushButton):
        if button.text() == "复制机器码":
            button.click()
            break
    assert dialog.status_label.text() == "机器码已复制到剪贴板。"
    dialog.close()
