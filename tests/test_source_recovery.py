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


def test_chat_service_treats_machine_nickname_as_direct_group_robot() -> None:
    from app.services.chat_service import ChatLogService

    service = ChatLogService()

    assert service._is_group_member_robot("GroupA", "robot-1", "机器人") is True
    assert service._is_group_member_robot("GroupA", "robot-1", "开奖机器") is True
    assert service._is_group_member_robot("GroupA", "user-1", "Alice") is False


def test_chat_service_direct_group_excludes_machine_nickname_bets() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 17, 19, 20, 11),
            group="威廉古堡3.69-4.29网盘🔥🔥",
            username="机器人",
            sender_id="rm7HObZVI",
            content="大100 小100",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 17, 19, 20, 20),
            group="威廉古堡3.69-4.29网盘🔥🔥",
            username="Alice",
            sender_id="alice-1",
            content="大50",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="20260617230",
        site="australia",
        period_window_start=datetime(2026, 6, 17, 19, 20, 0),
        period_window_end=datetime(2026, 6, 17, 19, 23, 0),
        period_interval_sec=180,
    )

    assert [(row["username"], row["play"], row["amount"]) for row in rows] == [("Alice", "大", 50.0)]
    assert stats.totals == {"大": 50.0}


def test_chat_service_direct_group_uses_first_machine_period_message_as_start_marker() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 17, 19, 19, 55),
            group="蜜雪冰城全天加拿大（4.2-4.6）",
            username="Bob",
            sender_id="bob-1",
            content="大100",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 17, 19, 20, 0),
            group="蜜雪冰城全天加拿大（4.2-4.6）",
            username="机器人",
            sender_id="zdUCgmuiV",
            content="---[S260617335-001]---\n当前260617335，欢迎猜猜",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 17, 19, 20, 5),
            group="蜜雪冰城全天加拿大（4.2-4.6）",
            username="Alice",
            sender_id="alice-1",
            content="小200",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="260617335",
        site="norway",
        period_window_start=datetime(2026, 6, 17, 19, 19, 30),
        period_window_end=datetime(2026, 6, 17, 19, 23, 0),
        period_interval_sec=210,
    )

    assert [(row["username"], row["period"], row["play"], row["amount"]) for row in rows] == [
        ("Alice", "260617335", "小", 200.0)
    ]
    assert stats.totals == {"小": 200.0}


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


def test_chat_service_parses_robot_multiline_receipt_bets() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 13, 18, 22, 22),
            group="摩羯座网盘4.28-3.68",
            username="Robot",
            sender_id="robot-1",
            content=(
                "@雪茜 : \n"
                "下注期数: 3444525\n"
                "下注内容: \n"
                "------------\n"
                "15.150(13.0赔率)\n"
                "大800(1.98赔率)\n"
                "------------\n"
                "余额：3088"
            ),
        ),
        ChatMessage(
            ts=datetime(2026, 6, 13, 18, 22, 24),
            group="摩羯座网盘4.28-3.68",
            username="Robot",
            sender_id="robot-1",
            content=(
                "@朝阳 : \n"
                "下注期数: 3444525\n"
                "下注内容: \n"
                "------------\n"
                "小单2500(3.68赔率)\n"
                "大双2500(3.68赔率)\n"
                "11.500(14.0赔率)\n"
                "------------\n"
                "余额：39292"
            ),
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3444525",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=210,
    )

    assert [(row["bettor"], row["period"], row["play"], row["amount"]) for row in rows] == [
        ("雪茜", "3444525", "15", 150.0),
        ("雪茜", "3444525", "大", 800.0),
        ("朝阳", "3444525", "11", 500.0),
        ("朝阳", "3444525", "大双", 2500.0),
        ("朝阳", "3444525", "小单", 2500.0),
    ]
    assert stats.totals == {
        "15": 150.0,
        "大": 800.0,
        "小单": 2500.0,
        "大双": 2500.0,
        "11": 500.0,
    }
    assert stats.totals_by_group == {
        "摩羯座网盘4.28-3.68": {
            "15": 150.0,
            "大": 800.0,
            "小单": 2500.0,
            "大双": 2500.0,
            "11": 500.0,
        }
    }


def test_chat_service_receipt_group_ignores_period_summary_billboard() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 13, 18, 24, 27),
            group="摩羯座网盘4.28-3.68",
            username="Robot",
            sender_id="robot-1",
            content=(
                "--------[3444525]期--------\n"
                "诗绮 63985【小单5888 小双5888 】\n"
                "福哥 61144【大单4644 大双2500 】\n"
                "洞宇 52342【大双3000 大单3000 小单3000 】"
            ),
        )
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3444525",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=210,
    )

    assert rows == []
    assert stats.totals == {}


def test_chat_service_receipt_group_ignores_online_scoreboard() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 13, 18, 25, 7),
            group="摩羯座网盘4.28-3.68",
            username="Robot",
            sender_id="robot-1",
            content=(
                "---[3444525]---\n"
                "在线人数: 313 人－总分 7712306\n"
                "════════════\n"
                "摩羯9999999 座杀9999998\n"
                "大枣0037720 堰清0045380\n"
                "大爷0000888 柳权0030939"
            ),
        )
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3444525",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=210,
    )

    assert rows == []
    assert stats.totals == {}


def test_chat_service_recognizes_online_scoreboard_as_billboard() -> None:
    from app.services.chat_service import ChatLogService

    content = (
        "---[3444525]---\n"
        "在线人数: 313 人－总分 7712306\n"
        "════════════\n"
        "大枣0037720 雪梅0036427\n"
        "大爷0000888 文燕0000834"
    )

    assert ChatLogService()._looks_like_period_summary_billboard(content) is True


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


def test_chat_service_direct_group_uses_site_window_without_robot_markers() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 55, 12),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="大10",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 58, 5),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="小20",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3445723",
        site="pc28",
        period_window_start=datetime(2026, 6, 10, 17, 55, 0),
        period_window_end=datetime(2026, 6, 10, 17, 58, 30),
        period_interval_sec=210,
        lock_threshold_sec=20,
    )

    assert [(row["bettor"], row["period"], row["play"], row["amount"]) for row in rows] == [
        ("Alice", "3445723", "大", 10.0),
        ("Alice", "3445723", "小", 20.0),
    ]
    assert stats.totals == {"大": 10.0, "小": 20.0}


def test_chat_service_direct_group_excludes_warmup_and_locked_window_messages() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 55, 5),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="大10",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 55, 10),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="小20",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 58, 12),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="单30",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3445723",
        site="pc28",
        period_window_start=datetime(2026, 6, 10, 17, 55, 0),
        period_window_end=datetime(2026, 6, 10, 17, 58, 30),
        period_interval_sec=210,
        lock_threshold_sec=20,
    )

    assert [(row["play"], row["amount"]) for row in rows] == [("小", 20.0)]
    assert stats.totals == {"小": 20.0}


def test_chat_service_cancel_removes_all_current_period_direct_group_rows() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 55, 12),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="大10 小20",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 56, 0),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="取消",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3445723",
        site="pc28",
        period_window_start=datetime(2026, 6, 10, 17, 55, 0),
        period_window_end=datetime(2026, 6, 10, 17, 58, 30),
        period_interval_sec=210,
        lock_threshold_sec=20,
    )

    assert rows == []
    assert stats.totals == {}


def test_chat_service_named_cancel_removes_all_current_period_rows() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 55, 12),
            group="普通群A",
            username="Alice",
            sender_id="alice-1",
            content="大10 小20",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 10, 17, 56, 0),
            group="普通群A",
            username="Robot",
            sender_id="robot-1",
            content="Alice 取消",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3445723",
        site="pc28",
        period_window_start=datetime(2026, 6, 10, 17, 55, 0),
        period_window_end=datetime(2026, 6, 10, 17, 58, 30),
        period_interval_sec=210,
        lock_threshold_sec=20,
    )

    assert rows == []
    assert stats.totals == {}


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


def test_chat_service_sqlite_messages_map_group_id_to_groupinfo_name(tmp_path: Path) -> None:
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
            "900361932",
            "robot-1",
            0,
            int(datetime(2026, 6, 13, 18, 22, 22).timestamp()),
            7,
            "",
            "@雪茜 : \n下注期数: 3444525\n下注内容: \n------------\n15.150(13.0赔率)\n------------\n余额：3088",
        ),
    )
    con.commit()
    con.close()

    im_con = sqlite3.connect(tmp_path / "im.db")
    im_con.execute("create table groupinfo (group_id text, group_name text)")
    im_con.execute("insert into groupinfo values (?, ?)", ("900361932", "摩羯座网盘4.28-3.68"))
    im_con.commit()
    im_con.close()

    messages = ChatLogService().load_messages_from_sqlite(
        db_path,
        ParseOptions(
            group_ids=["900361932"],
            start_time=datetime(2026, 6, 13, 18, 20, 0),
            end_time=datetime(2026, 6, 13, 18, 25, 0),
        ),
    )

    assert len(messages) == 1
    assert messages[0].group == "摩羯座网盘4.28-3.68"


def test_chat_service_sqlite_messages_map_sender_id_to_group_member_nickname(tmp_path: Path) -> None:
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
            "818653745",
            "Qs1xWRFOw",
            0,
            int(datetime(2026, 6, 16, 20, 40, 34).timestamp()),
            7,
            "",
            "27.30",
        ),
    )
    con.commit()
    con.close()

    im_con = sqlite3.connect(tmp_path / "im.db")
    im_con.execute("create table groupinfo (group_id text, group_name text)")
    im_con.execute("create table groupmemberinfo (group_id text, user_id text, remark text, name_card text, nick_name text)")
    im_con.execute("insert into groupinfo values (?, ?)", ("818653745", "金财集团<金财帝国>"))
    im_con.execute(
        "insert into groupmemberinfo values (?, ?, ?, ?, ?)",
        ("818653745", "Qs1xWRFOw", "", "", "丑的惊动了党"),
    )
    im_con.commit()
    im_con.close()

    messages = ChatLogService().load_messages_from_sqlite(
        db_path,
        ParseOptions(
            group_ids=["818653745"],
            start_time=datetime(2026, 6, 16, 20, 40, 0),
            end_time=datetime(2026, 6, 16, 20, 41, 0),
        ),
    )

    assert len(messages) == 1
    assert messages[0].group == "金财集团<金财帝国>"
    assert messages[0].username == "丑的惊动了党"
    assert messages[0].sender_id == "Qs1xWRFOw"


def test_chat_service_extract_message_text_preserves_multiline_receipt_context() -> None:
    from app.services.chat_service import ChatLogService

    raw = (
        "@堰清 : \n"
        "下注期数: 3444525\n"
        "下注内容: \n"
        "------------\n"
        "大单3000(4.28赔率)\n"
        "小双3000(4.28赔率)\n"
        "------------\n"
        "余额：45380"
    )

    text = ChatLogService()._extract_message_text(raw, "")

    assert "@堰清" in text
    assert "下注期数: 3444525" in text
    assert "大单3000" in text
    assert "余额" in text


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


def test_chat_service_sqlite_groups_require_groupinfo_without_scanning_messages(tmp_path: Path, monkeypatch) -> None:
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

    assert groups == []


def test_chat_service_sqlite_default_window_is_five_minutes() -> None:
    from datetime import timedelta

    from app.services import chat_service

    assert chat_service.DEFAULT_SQLITE_LOAD_WINDOW == timedelta(minutes=5)


def test_chat_service_lists_sqlite_groups_with_names_from_sibling_im_db(tmp_path: Path) -> None:
    import sqlite3

    from app.services.chat_service import ChatLogService

    msg_db = tmp_path / "msg_0.db"
    msg_con = sqlite3.connect(msg_db)
    msg_con.execute("create table message (sid text)")
    msg_con.executemany("insert into message values (?)", [("1001",), ("1002",)])
    msg_con.commit()
    msg_con.close()

    im_db = tmp_path / "im.db"
    im_con = sqlite3.connect(im_db)
    im_con.execute("create table groupinfo (group_id text, group_name text)")
    im_con.executemany("insert into groupinfo values (?, ?)", [("1001", "测试一群"), ("1002", "测试二群")])
    im_con.commit()
    im_con.close()

    groups = ChatLogService().list_groups_from_db(msg_db)

    assert [(group.group_id, group.group_name) for group in groups] == [
        ("1001", "测试一群"),
        ("1002", "测试二群"),
    ]


def test_chat_service_sqlite_groups_ignore_message_ids_not_in_groupinfo(tmp_path: Path) -> None:
    import sqlite3

    from app.services.chat_service import ChatLogService

    msg_db = tmp_path / "msg_0.db"
    msg_con = sqlite3.connect(msg_db)
    msg_con.execute("create table message (sid text)")
    msg_con.executemany("insert into message values (?)", [("private-user",), ("1001",)])
    msg_con.commit()
    msg_con.close()

    im_db = tmp_path / "im.db"
    im_con = sqlite3.connect(im_db)
    im_con.execute("create table groupinfo (group_id text, group_name text)")
    im_con.execute("insert into groupinfo values (?, ?)", ("1001", "测试一群"))
    im_con.commit()
    im_con.close()

    groups = ChatLogService().list_groups_from_db(msg_db)

    assert [(group.group_id, group.group_name) for group in groups] == [("1001", "测试一群")]


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
    assert macao.next_countdown == 180
    assert australia.current_period == "3001"
    assert australia.next_period == "3002"
    assert australia.next_countdown == 120
    assert norway.current_period == "4001"
    assert norway.next_period == "4002"


def test_draw_info_exposes_local_schedule_metadata_defaults() -> None:
    from app.models import DrawInfo

    info = DrawInfo(current_period="1001")

    assert info.current_period == "1001"
    assert info.start_time is None
    assert info.interval_sec == 0
    assert info.source == "api"
    assert info.last_api_success_at is None


def test_fetch_date_pc28_sets_schedule_metadata_from_absolute_next_time() -> None:
    from datetime import datetime

    from app.utils.fetch_date import extract_draw_info

    info = extract_draw_info(
        "pc28",
        {"issue": [{"qishu": "1001", "time": "2026-06-10 12:00:00", "next": 1781107410}]},
    )

    assert info.current_period == "1001"
    assert info.next_period == "1002"
    assert info.start_time == datetime(2026, 6, 10, 12, 0, 0)
    assert info.current_time == datetime(2026, 6, 10, 12, 0, 0)
    assert info.next_time == datetime.fromtimestamp(1781107410)
    assert info.interval_sec == 210
    assert info.source == "api"
    assert info.last_api_success_at is not None


def test_fetch_date_macao_without_next_time_derives_schedule_from_interval() -> None:
    from datetime import datetime

    from app.utils.fetch_date import extract_draw_info

    info = extract_draw_info(
        "macao",
        {"data": {"drawList": [{"qihao": "2001", "opentime": "2026-06-10 12:03:00"}]}},
    )

    assert info.current_period == "2001"
    assert info.next_period == "2002"
    assert info.start_time == datetime(2026, 6, 10, 12, 3, 0)
    assert info.next_time == datetime(2026, 6, 10, 12, 6, 0)
    assert info.interval_sec == 180
    assert info.next_countdown >= 0


def test_fetch_date_australia_derives_next_time_from_countdown(monkeypatch) -> None:
    from datetime import datetime

    from app.utils import fetch_date

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 10, 12, 0, 0)

    monkeypatch.setattr(fetch_date, "datetime", FixedDateTime)

    info = fetch_date.extract_draw_info(
        "australia",
        {
            "qi": "3001",
            "time": "2026-06-10 12:00:00",
            "current_time": "2026-06-10 12:00:00",
            "next": {"qi": "3002", "sec": 120},
        },
    )

    assert info.current_period == "3001"
    assert info.next_period == "3002"
    assert info.next_countdown == 120
    assert info.next_time == FixedDateTime(2026, 6, 10, 12, 2, 0)
    assert info.interval_sec == 180


def test_extract_draw_info_falls_back_to_last_good_pc28_when_issue_list_is_empty(monkeypatch) -> None:
    from datetime import datetime

    from app.utils import fetch_date

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 10, 12, 1, 0)

    monkeypatch.setattr(fetch_date, "datetime", FixedDateTime)
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


def test_extract_draw_info_fallback_advances_period_after_elapsed_windows(monkeypatch) -> None:
    from datetime import datetime

    from app.models import DrawInfo
    from app.utils import fetch_date

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 10, 12, 10, 0)

    monkeypatch.setattr(fetch_date, "datetime", FixedDateTime)
    fetch_date._last_good_draw.clear()
    fetch_date._last_good_draw["pc28"] = DrawInfo(
        current_period="1001",
        current_time=FixedDateTime(2026, 6, 10, 12, 0, 0),
        next_countdown=210,
        next_period="1002",
        next_time=FixedDateTime(2026, 6, 10, 12, 3, 30),
        auto_period="1001",
        start_time=FixedDateTime(2026, 6, 10, 12, 0, 0),
        interval_sec=210,
        source="api",
        last_api_success_at=FixedDateTime(2026, 6, 10, 12, 0, 5),
    )

    fallback = fetch_date.extract_draw_info("pc28", {"issue": []})

    assert fallback.current_period == "1003"
    assert fallback.next_period == "1004"
    assert fallback.start_time == FixedDateTime(2026, 6, 10, 12, 7, 0)
    assert fallback.next_time == FixedDateTime(2026, 6, 10, 12, 10, 30)
    assert fallback.source == "inferred"
    assert fallback.last_api_success_at == FixedDateTime(2026, 6, 10, 12, 0, 5)


def test_extract_draw_info_retries_transient_empty_pc28_payload(monkeypatch) -> None:
    from app.utils import fetch_date

    fetch_date._last_good_draw.clear()
    payloads = [
        {"issue": []},
        {"issue": [{"qishu": "1002", "time": "2026-06-10 12:03:30", "next": 1781093220}]},
    ]
    monkeypatch.setitem(fetch_date._FETCHERS, "pc28", lambda: payloads.pop(0))

    info = fetch_date.extract_draw_info("pc28")

    assert info.current_period == "1002"
    assert payloads == []


def test_fetch_date_macao_without_next_time_uses_site_interval_countdown() -> None:
    from app.utils.fetch_date import extract_draw_info

    macao = extract_draw_info(
        "macao",
        {"data": {"drawList": [{"qihao": "2001", "opentime": "2026-06-10 12:03:00"}]}},
    )

    assert macao.next_period == "2002"
    assert macao.next_countdown == 180


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


def test_main_window_run_load_pipeline_syncs_group_block_rules() -> None:
    from pathlib import Path
    from types import SimpleNamespace

    from app.models import ParseOptions, StatsResult
    from app.ui.main_window_data import MainWindowDataMixin

    calls: list[tuple[str, object]] = []

    class DummyService:
        def set_group_block_rules(self, rules):
            calls.append(("rules", rules))

        def load_messages_with_cache(self, source_path, options):
            return []

        def analyze_bets(self, *args):
            calls.append(("analyze", args))
            return [], StatsResult(totals={})

        def get_cached_cursor(self, messages):
            return None

    dummy = SimpleNamespace(
        chat_service=DummyService(),
        _log_load_diagnostics=lambda *args: None,
    )
    options = ParseOptions(
        blocked_names_by_group={
            "g1": {"group_id": "g1", "group_name": "摩羯座网盘4.28-3.68", "names": ["旺达"]}
        }
    )

    MainWindowDataMixin._run_load_pipeline(dummy, Path("sample.db"), options, ("sig",), 1, "pc28", None)

    assert calls[0] == ("rules", options.blocked_names_by_group)


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
    im_con = sqlite3.connect(tmp_path / "im.db")
    im_con.execute("create table groupinfo (group_id text, group_name text)")
    im_con.execute("insert into groupinfo values (?, ?)", ("group-1", "测试群"))
    im_con.commit()
    im_con.close()

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
    assert dummy.group_list.item(0).text() == "测试群"
    assert dummy.group_list.item(0).data(Qt.UserRole) == "group-1"
    assert dummy.group_list.item(0).data(Qt.UserRole + 1) == "测试群"
    assert dummy.group_list.item(0).checkState() == Qt.Checked
    assert dummy.refreshed is True


def test_main_window_data_gather_parse_options_includes_group_and_period_context() -> None:
    from datetime import datetime
    from PySide6.QtCore import Qt

    from app.models import DrawInfo
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
    dummy._draw_infos = {
        "pc28": DrawInfo(
            current_period="9000",
            next_period="9001",
            start_time=datetime(2026, 6, 10, 17, 55, 0),
            next_time=datetime(2026, 6, 10, 17, 58, 30),
            interval_sec=210,
        )
    }
    dummy._lock_threshold_sec = 25

    options = dummy._gather_parse_options()

    assert options.username == ""
    assert options.groups == ["GroupA"]
    assert options.group_ids == ["g1"]
    assert options.blocked_names == ["Blocked"]
    assert options.period_filter == "9001"
    assert options.site == "pc28"
    assert options.period_window_start == datetime(2026, 6, 10, 17, 55, 0)
    assert options.period_window_end == datetime(2026, 6, 10, 17, 58, 30)
    assert options.period_interval_sec == 210
    assert options.lock_threshold_sec == 25


def test_main_window_data_gather_parse_options_includes_active_site_window() -> None:
    from datetime import datetime

    from app.models import DrawInfo
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyList:
        def count(self):
            return 0

    class DummyCombo:
        def currentText(self):
            return ""

    class DummyText:
        def text(self):
            return ""

    class DummyWindow(MainWindowDataMixin):
        pass

    dummy = DummyWindow()
    dummy.group_list = DummyList()
    dummy.username_combo = DummyCombo()
    dummy.period_input = DummyText()
    dummy.group_block_rules = {}
    dummy._active_site = "pc28"
    dummy._draw_infos = {
        "pc28": DrawInfo(
            current_period="3445799",
            next_period="3445800",
            start_time=datetime(2026, 6, 10, 17, 55, 0),
            next_time=datetime(2026, 6, 10, 17, 58, 30),
            interval_sec=210,
        )
    }

    options = dummy._gather_parse_options()

    assert options.period_filter == "3445800"
    assert options.period_window_start == datetime(2026, 6, 10, 17, 55, 0)
    assert options.period_window_end == datetime(2026, 6, 10, 17, 58, 30)
    assert options.period_interval_sec == 210


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


def test_main_window_data_load_initial_state_forces_default_query_period_and_activation_gate() -> None:
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
    dummy._require_activation = True
    dummy._active_site = ""
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy.username_combo.items == ["Alice", "Bob"]
    assert dummy.username_combo.current == "Alice"
    assert dummy.manual_db_edit.value == "D:/db.sqlite"
    assert dummy.period_input.value == ""
    assert dummy.tabs.current is dummy.license_page


def test_main_window_data_load_initial_state_does_not_restore_period_override_map() -> None:
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

    assert dummy._query_period_overrides_by_site == {}
    assert dummy.period_input.value == ""


def test_main_window_data_load_initial_state_restores_advanced_time_filter() -> None:
    from datetime import datetime

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def clear(self) -> None:
            return None

        def addItems(self, _values) -> None:
            return None

    class DummyEdit:
        def __init__(self) -> None:
            self.value = ""

        def setText(self, value: str) -> None:
            self.value = value

    class DummyFrame:
        def __init__(self) -> None:
            self.visible = False

        def setVisible(self, value: bool) -> None:
            self.visible = value

    class DummyDateTimeEdit:
        def __init__(self) -> None:
            self.value = None

        def setDateTime(self, value) -> None:
            self.value = value

    class DummyWindow(MainWindowDataMixin):
        def _refresh_block_rule_group_selector(self) -> None:
            return None

        def _refresh_license_banner(self) -> None:
            return None

        def _sync_chart_status(self) -> None:
            return None

    dummy = DummyWindow()
    dummy.analysis_page = object()
    dummy.settings = {
        "advanced_time_filter_enabled": True,
        "advanced_time_start": "2026-06-12T03:30:00",
        "advanced_time_end": "2026-06-12T03:35:00",
    }
    dummy.username_combo = DummyCombo()
    dummy.manual_db_edit = DummyEdit()
    dummy.resolved_path_edit = DummyEdit()
    dummy.period_input = DummyEdit()
    dummy.advanced_time_frame = DummyFrame()
    dummy.start_edit = DummyDateTimeEdit()
    dummy.end_edit = DummyDateTimeEdit()
    dummy._active_site = ""
    dummy._require_activation = False

    dummy._load_initial_state()

    assert dummy.advanced_time_frame.visible is True
    assert dummy.start_edit.value.toPython() == datetime(2026, 6, 12, 3, 30, 0)
    assert dummy.end_edit.value.toPython() == datetime(2026, 6, 12, 3, 35, 0)


def test_main_window_data_load_initial_state_leaves_period_blank_without_loaded_draw_info() -> None:
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
    dummy._query_period_overrides_by_site = {}
    dummy._active_site = "macao"
    dummy._require_activation = True
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy._query_period_overrides_by_site == {}
    assert dummy.period_input.value == ""


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

    from app.ui.main_window_layout import LEFT_SECTION_MAX_WIDTH, LEFT_SECTION_MIN_WIDTH, MainWindowLayoutMixin

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

    from app.ui.main_window_layout import LEFT_SECTION_MAX_WIDTH, LEFT_SECTION_MIN_WIDTH, MainWindowLayoutMixin

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

    assert dummy.resolved_path_edit.maximumWidth() <= 210
    assert dummy.manual_db_edit.maximumWidth() <= 210
    assert dummy.block_names_edit.maximumHeight() >= 300
    assert dummy.block_rule_summary_view.maximumHeight() >= 300
    dummy.analysis_page.close()


def test_main_window_left_sections_share_width_height_and_expand_policies() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFrame, QGroupBox, QScrollArea, QSizePolicy, QWidget

    from app.ui.main_window_layout import LEFT_SECTION_MAX_WIDTH, LEFT_SECTION_MIN_WIDTH, MainWindowLayoutMixin

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

    left_scroll = dummy.main_splitter.widget(0)
    assert isinstance(left_scroll, QScrollArea)
    assert left_scroll.maximumWidth() >= 1600
    sections = [dummy.analysis_page.findChild(QFrame, "siteFrame")]
    sections.extend(dummy.analysis_page.findChildren(QGroupBox))
    section_names = {section.title() if isinstance(section, QGroupBox) else "线路选择" for section in sections}
    assert {"线路选择", "账号与数据源", "手动数据源", "筛选条件", "屏蔽名单", "状态"} <= section_names
    for section in sections:
        assert section.minimumWidth() == LEFT_SECTION_MIN_WIDTH
        assert section.maximumWidth() == LEFT_SECTION_MAX_WIDTH
        assert section.minimumHeight() >= 140
        assert section.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
        assert section.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert dummy.username_combo.maximumWidth() <= 190
    assert dummy.group_list.minimumWidth() == LEFT_SECTION_MIN_WIDTH
    assert dummy.group_list.maximumWidth() == LEFT_SECTION_MAX_WIDTH
    assert dummy.group_list.minimumHeight() >= 140
    assert dummy.group_list.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert dummy.group_list.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert dummy.global_block_names_edit.minimumWidth() == LEFT_SECTION_MIN_WIDTH
    assert dummy.global_block_names_edit.maximumWidth() == LEFT_SECTION_MAX_WIDTH
    assert dummy.global_block_names_edit.minimumHeight() >= 100
    assert dummy.global_block_names_edit.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert dummy.global_block_names_edit.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    dummy.analysis_page.close()


def test_main_window_splitter_can_drag_left_panel_wider_while_controls_stay_compact() -> None:
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

    dummy.main_splitter.setSizes([500, 680])
    app.processEvents()

    assert dummy.main_splitter.sizes()[0] >= 450
    assert dummy.username_combo.maximumWidth() <= 190
    dummy.analysis_page.close()


def test_main_window_initial_splitter_uses_compact_left_panel() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummySplitter:
        def __init__(self) -> None:
            self.sizes: list[int] = []

        def setSizes(self, sizes: list[int]) -> None:
            self.sizes = sizes

    dummy = SimpleNamespace(main_splitter=DummySplitter())

    MainWindowDataMixin._apply_initial_splitter_sizes(dummy)

    assert dummy.main_splitter.sizes == [240, 1160]


def test_main_window_theme_adds_groupbox_title_padding() -> None:
    from app.ui.main_window import MainWindow

    class DummyWindow:
        def __init__(self) -> None:
            self.stylesheet = ""

        def setStyleSheet(self, value: str) -> None:
            self.stylesheet = value

    dummy = DummyWindow()

    MainWindow._apply_theme(dummy)

    assert "QGroupBox::title" in dummy.stylesheet
    assert "padding" in dummy.stylesheet


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

    assert {"自动定位数据库", "浏览", "使用数据源", "全选", "反选", "原始聊天记录"} <= button_texts
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


def test_main_window_realtime_period_input_ignores_saved_override_map() -> None:
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
    assert dummy.period_input.value == "1002"

    MainWindowRealtimeMixin._select_site(dummy, "macao")
    assert dummy.period_input.value == "2002"
    assert dummy._query_period_overrides_by_site == {}


def test_main_window_realtime_auto_period_clears_stale_override_matching_next_period() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = "3444518"
            self.blocked = False

        def blockSignals(self, value: bool) -> None:
            self.blocked = value

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

        def hasFocus(self) -> bool:
            return False

    saved: list[dict[str, str]] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _query_period_overrides_by_site={"pc28": "3444487"},
        _query_period_override="3444487",
        _manual_period_override=True,
        _draw_infos={"pc28": DrawInfo(current_period="3444517", next_period="3444518")},
        period_input=DummyPeriodInput(),
        _save_settings=lambda: saved.append(dict(dummy._query_period_overrides_by_site)),
    )
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)

    MainWindowRealtimeMixin._on_period_input_changed(dummy)
    MainWindowRealtimeMixin._sync_period_input_from_site(dummy, dummy._draw_infos["pc28"])

    assert dummy._query_period_overrides_by_site == {}
    assert dummy.period_input.value == "3444518"
    assert saved == [{}]


def test_main_window_realtime_period_sync_does_not_overwrite_focused_user_input() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = "3444518"

        def blockSignals(self, value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

        def hasFocus(self) -> bool:
            return True

    dummy = SimpleNamespace(
        _active_site="pc28",
        _query_period_overrides_by_site={"pc28": "3444487"},
        period_input=DummyPeriodInput(),
    )
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)

    MainWindowRealtimeMixin._sync_period_input_from_site(
        dummy,
        DrawInfo(current_period="3444517", next_period="3444518"),
    )

    assert dummy.period_input.value == "3444518"


def test_main_window_realtime_select_site_forces_default_query_period_on_first_selected_site() -> None:
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

    assert dummy._query_period_overrides_by_site == {}
    assert dummy.period_input.value == "2002"


def test_main_window_realtime_select_site_does_not_save_legacy_period_migration() -> None:
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

    assert save_calls == []


def test_main_window_realtime_select_site_does_not_preserve_legacy_period_on_previous_site() -> None:
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

    assert dummy._query_period_overrides_by_site == {}
    assert dummy._query_period_override == ""
    assert dummy.period_input.value == "2002"


def _bind_realtime_countdown_helpers(dummy) -> None:
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy._advance_site_countdown = lambda site, info, now: MainWindowRealtimeMixin._advance_site_countdown(
        dummy, site, info, now
    )
    dummy._submit_site_draw_refresh = lambda site, info: MainWindowRealtimeMixin._submit_site_draw_refresh(
        dummy, site, info
    )
    dummy._handle_single_draw_info_loaded = lambda site, fallback, future: MainWindowRealtimeMixin._handle_single_draw_info_loaded(
        dummy, site, fallback, future
    )
    dummy._apply_single_draw_info = lambda payload: MainWindowRealtimeMixin._apply_single_draw_info(dummy, payload)
    dummy._refreshing_site_set = lambda: MainWindowRealtimeMixin._refreshing_site_set(dummy)
    dummy._draw_retry_count = lambda site: MainWindowRealtimeMixin._draw_retry_count(dummy, site)
    dummy._set_draw_retry_count = lambda site, count: MainWindowRealtimeMixin._set_draw_retry_count(dummy, site, count)
    dummy._clear_draw_retry_count = lambda site: MainWindowRealtimeMixin._clear_draw_retry_count(dummy, site)
    dummy._compare_period_text = lambda left, right: MainWindowRealtimeMixin._compare_period_text(dummy, left, right)
    dummy._is_stale_draw_info = lambda site, info: MainWindowRealtimeMixin._is_stale_draw_info(dummy, site, info)
    dummy._schedule_calibration_retry = lambda site: MainWindowRealtimeMixin._schedule_calibration_retry(dummy, site)
    dummy._update_site_card_widgets = lambda site, info: None
    dummy._extrapolate_next_draw_info = lambda site, info: MainWindowRealtimeMixin._extrapolate_next_draw_info(
        dummy, site, info
    )
    dummy._calibration_due_map = lambda: MainWindowRealtimeMixin._calibration_due_map(dummy)
    dummy._advance_site_locally = lambda site, info, now: MainWindowRealtimeMixin._advance_site_locally(
        dummy, site, info, now
    )
    dummy._schedule_draw_calibration = lambda site, due_at: MainWindowRealtimeMixin._schedule_draw_calibration(
        dummy, site, due_at
    )
    dummy._submit_due_draw_calibrations = lambda now: MainWindowRealtimeMixin._submit_due_draw_calibrations(dummy, now)
    dummy._increment_period_text = lambda period, delta: MainWindowRealtimeMixin._increment_period_text(
        dummy, period, delta
    )


def test_main_window_countdown_zero_advances_locally_and_schedules_calibration(monkeypatch) -> None:
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.models import DrawInfo, StatsResult
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    submitted: list[str] = []
    monkeypatch.setattr(
        main_window_realtime,
        "extract_draw_info",
        lambda site: (_ for _ in ()).throw(AssertionError("countdown zero must not fetch immediately")),
    )

    class DummyWorker:
        def submit(self, func, site):
            submitted.append(site)
            return SimpleNamespace(add_done_callback=lambda callback: None)

    now = datetime(2026, 6, 10, 12, 3, 30)
    replace_calls: list[list[object]] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={},
        _last_message_cursor={"pc28": (10, 20)},
        _query_period_overrides_by_site={},
        _stats_locked=True,
        _awaiting_next_period=True,
        _refreshing_sites=set(),
        _worker=DummyWorker(),
        current_messages=[object()],
        current_visual_rows=[{"period": "1001"}],
        current_stats=StatsResult(totals={"x": 1.0}),
        chart_window=SimpleNamespace(replace_rows=lambda rows: replace_calls.append(list(rows))),
        _update_site_card_widgets=lambda site, info: None,
        _refresh_active_site_info=lambda: None,
        _load_filtered_messages=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    info = DrawInfo(
        current_period="1001",
        next_period="1002",
        current_time=datetime(2026, 6, 10, 12, 0, 0),
        start_time=datetime(2026, 6, 10, 12, 0, 0),
        next_time=now,
        next_countdown=0,
        interval_sec=210,
    )
    dummy._draw_infos["pc28"] = info

    MainWindowRealtimeMixin._advance_site_countdown(dummy, "pc28", info, now)

    advanced = dummy._draw_infos["pc28"]
    assert advanced.current_period == "1002"
    assert advanced.next_period == "1003"
    assert advanced.start_time == now
    assert advanced.next_time == datetime(2026, 6, 10, 12, 7, 0)
    assert advanced.next_countdown == 210
    assert advanced.source == "inferred"
    assert dummy.current_messages == []
    assert dummy.current_visual_rows == []
    assert dummy.current_stats == StatsResult(totals={}, totals_by_group={})
    assert replace_calls == [[]]
    assert dummy._draw_calibration_due_at["pc28"] == now + timedelta(seconds=10)
    assert submitted == []
    assert dummy._refreshing_sites == set()


def test_main_window_countdown_zero_late_tick_preserves_elapsed_seconds() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    now = datetime(2026, 6, 10, 12, 3, 35)
    draw_time = datetime(2026, 6, 10, 12, 3, 30)
    dummy = SimpleNamespace(
        _active_site="macao",
        _draw_infos={},
        _query_period_overrides_by_site={},
        _refreshing_sites=set(),
        _update_site_card_widgets=lambda site, info: None,
        _refresh_active_site_info=lambda: None,
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    info = DrawInfo(
        current_period="2001",
        next_period="2002",
        next_time=draw_time,
        next_countdown=0,
        interval_sec=210,
    )
    dummy._draw_infos["macao"] = info

    MainWindowRealtimeMixin._advance_site_countdown(dummy, "macao", info, now)

    advanced = dummy._draw_infos["macao"]
    assert advanced.current_period == "2002"
    assert advanced.next_time == datetime(2026, 6, 10, 12, 7, 0)
    assert advanced.next_countdown == 205


def test_main_window_countdown_tick_submits_refresh_only_when_countdown_reaches_zero(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    submitted: list[tuple[object, str]] = []
    monkeypatch.setattr(
        main_window_realtime,
        "extract_draw_info",
        lambda site: (_ for _ in ()).throw(AssertionError("network refresh must run in worker")),
    )

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=2)},
        _refresh_active_site_info=lambda: None,
        _refreshing_sites=set(),
    )
    _bind_realtime_countdown_helpers(dummy)

    MainWindowRealtimeMixin._on_countdown_tick(dummy)
    assert submitted == []
    assert dummy._draw_infos["pc28"].next_countdown == 1

    MainWindowRealtimeMixin._on_countdown_tick(dummy)
    assert submitted == []
    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_infos["pc28"].next_period == "1003"
    assert 208 <= dummy._draw_infos["pc28"].next_countdown <= 210
    assert "pc28" in dummy._draw_calibration_due_at
    assert dummy._refreshing_sites == set()


def test_main_window_countdown_tick_updates_all_sites_and_fetches_only_expired(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    monkeypatch.setattr(main_window_realtime, "site_list", lambda: ["pc28", "macao", "australia", "norway"])
    submitted: list[str] = []
    monkeypatch.setattr(
        main_window_realtime,
        "extract_draw_info",
        lambda site: DrawInfo(current_period="9002", next_period="9003", next_countdown=8),
    )

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={
            "pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=3),
            "macao": DrawInfo(current_period="2001", next_period="2002", next_countdown=1),
            "australia": DrawInfo(current_period="3001", next_period="3002", next_countdown=5),
            "norway": DrawInfo(current_period="4001", next_period="4002", next_countdown=1),
        },
        _refresh_active_site_info=lambda: None,
        _render_site_cards=lambda: None,
        _refreshing_sites=set(),
    )
    _bind_realtime_countdown_helpers(dummy)

    MainWindowRealtimeMixin._on_countdown_tick(dummy)

    assert submitted == []
    assert dummy._draw_infos["pc28"].next_countdown == 2
    assert dummy._draw_infos["australia"].next_countdown == 4
    assert dummy._draw_infos["macao"].current_period == "2002"
    assert dummy._draw_infos["macao"].next_period == "2003"
    assert dummy._draw_infos["norway"].current_period == "4002"
    assert dummy._draw_infos["norway"].next_period == "4003"
    assert set(dummy._draw_calibration_due_at) == {"macao", "norway"}


def test_main_window_submits_calibration_only_after_due_time() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    submitted: list[str] = []

    class DummyWorker:
        def submit(self, func, site):
            submitted.append(site)
            return SimpleNamespace(add_done_callback=lambda callback: None)

    due_at = datetime(2026, 6, 10, 12, 3, 40)
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=200)},
        _draw_calibration_due_at={"pc28": due_at},
        _refreshing_sites=set(),
        _worker=DummyWorker(),
    )
    _bind_realtime_countdown_helpers(dummy)

    MainWindowRealtimeMixin._submit_due_draw_calibrations(dummy, datetime(2026, 6, 10, 12, 3, 39))
    assert submitted == []
    assert dummy._draw_calibration_due_at == {"pc28": due_at}

    MainWindowRealtimeMixin._submit_due_draw_calibrations(dummy, due_at)
    assert submitted == ["pc28"]
    assert dummy._refreshing_sites == {"pc28"}
    assert dummy._draw_calibration_due_at == {}


def test_main_window_calibration_submit_failure_schedules_retry_without_fallback() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class FailingWorker:
        def submit(self, func, site):
            raise RuntimeError("executor unavailable")

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=200, source="inferred")},
        _draw_calibration_due_at={},
        _refreshing_sites=set(),
        _worker=FailingWorker(),
    )
    _bind_realtime_countdown_helpers(dummy)

    MainWindowRealtimeMixin._submit_site_draw_refresh(dummy, "pc28", dummy._draw_infos["pc28"])

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._refreshing_sites == set()
    assert "pc28" in dummy._draw_calibration_due_at


def test_main_window_stale_calibration_response_retries_without_rollback() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=200, source="inferred")},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={},
        _draw_calibration_due_at={},
        _update_site_card_widgets=lambda site, info: None,
        _refresh_active_site_info=lambda: None,
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    stale_future = SimpleNamespace(
        result=lambda: DrawInfo(current_period="1001", next_period="1002", next_countdown=5, source="api")
    )

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, stale_future)

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_retry_counts == {"pc28": 1}
    assert dummy._draw_calibration_due_at["pc28"] > datetime.now()
    assert dummy._refreshing_sites == set()


def test_main_window_stale_calibration_after_three_retries_keeps_inferred_issue() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=200, source="inferred")},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={"pc28": 3},
        _draw_calibration_due_at={},
        _update_site_card_widgets=lambda site, info: None,
        _refresh_active_site_info=lambda: None,
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    stale_future = SimpleNamespace(result=lambda: DrawInfo(current_period="1001", next_period="1002", source="api"))

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, stale_future)

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_retry_counts == {}
    assert dummy._draw_calibration_due_at == {}
    assert dummy._refreshing_sites == set()


def test_main_window_same_period_calibration_updates_timing_without_clearing_again() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[object] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=180, source="inferred")},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={"pc28": 1},
        _query_period_overrides_by_site={},
        _update_site_card_widgets=lambda site, info: calls.append(("card", info.next_countdown)),
        _refresh_active_site_info=lambda: calls.append("refresh"),
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    future = SimpleNamespace(
        result=lambda: DrawInfo(
            current_period="1002",
            next_period="1003",
            next_countdown=150,
            next_time=datetime(2026, 6, 10, 12, 7, 0),
            source="api",
        )
    )

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, future)

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_infos["pc28"].next_countdown == 150
    assert dummy._draw_infos["pc28"].source == "api"
    assert dummy._draw_retry_counts == {}
    assert "refresh" in calls


def test_main_window_newer_period_calibration_adopts_api_issue() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo, StatsResult
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[object] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=1, source="inferred")},
        _last_message_cursor={"pc28": (1, 2)},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={},
        _query_period_overrides_by_site={},
        current_messages=[object()],
        current_visual_rows=[{"period": "1003", "play": "x", "amount": 50.0}],
        current_stats=StatsResult(totals={"x": 50.0}),
        chart_window=SimpleNamespace(replace_rows=lambda rows: calls.append(("replace", list(rows)))),
        period_input=SimpleNamespace(hasFocus=lambda: False, blockSignals=lambda value: None, setText=lambda value: calls.append(("period", value))),
        _update_site_card_widgets=lambda site, info: calls.append(("card", info.current_period)),
        _refresh_active_site_info=lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy),
        _sync_chart_status=lambda: calls.append("status"),
        _load_filtered_messages=lambda: calls.append("load"),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
    )
    _bind_realtime_countdown_helpers(dummy)
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)

    future = SimpleNamespace(result=lambda: DrawInfo(current_period="1003", next_period="1004", next_countdown=200, source="api"))

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, future)

    assert dummy._draw_infos["pc28"].current_period == "1003"
    assert dummy.current_messages == []
    assert dummy.current_visual_rows == []
    assert ("replace", []) in calls
    assert "load" in calls


def test_main_window_countdown_refresh_failure_waits_five_seconds_before_retry(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=1)},
        _refresh_active_site_info=lambda: None,
        _render_site_cards=lambda: None,
        _refreshing_sites={"pc28"},
        _draw_retry_counts={},
    )
    _bind_realtime_countdown_helpers(dummy)

    fallback = DrawInfo(current_period="1002", next_period="1003", next_countdown=9)
    future = SimpleNamespace(result=lambda: (_ for _ in ()).throw(ValueError("empty issue list")))
    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", fallback, future)

    assert dummy._draw_infos["pc28"].current_period == "1001"
    assert dummy._draw_infos["pc28"].next_period == "1002"
    assert dummy._draw_infos["pc28"].next_countdown == 1
    assert dummy._draw_retry_counts == {"pc28": 1}
    assert "pc28" in dummy._draw_calibration_due_at
    assert dummy._refreshing_sites == set()


def test_main_window_countdown_refresh_keeps_current_issue_after_three_retries(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="3444964", next_period="3444965", next_countdown=1)},
        _refresh_active_site_info=lambda: None,
        _render_site_cards=lambda: None,
        _refreshing_sites={"pc28"},
        _draw_retry_counts={"pc28": 3},
    )
    _bind_realtime_countdown_helpers(dummy)

    future = SimpleNamespace(result=lambda: (_ for _ in ()).throw(ValueError("empty issue list")))
    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, future)

    assert dummy._draw_infos["pc28"].current_period == "3444964"
    assert dummy._draw_infos["pc28"].next_period == "3444965"
    assert dummy._draw_infos["pc28"].next_countdown == 1
    assert dummy._draw_retry_counts == {}
    assert getattr(dummy, "_draw_calibration_due_at", {}) == {}
    assert dummy._refreshing_sites == set()


def test_main_window_extrapolated_draw_advances_to_next_period() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace()
    dummy._increment_period_text = lambda period, delta: MainWindowRealtimeMixin._increment_period_text(dummy, period, delta)

    info = MainWindowRealtimeMixin._extrapolate_next_draw_info(
        dummy,
        "pc28",
        DrawInfo(current_period="3444964", next_period="3444965", next_countdown=0),
    )

    assert info.current_period == "3444965"
    assert info.next_period == "3444966"
    assert info.auto_period == "3444965"


def test_main_window_apply_new_active_period_resets_cursor_and_loads_next_period() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[str] = []

    class DummyInput:
        def __init__(self) -> None:
            self.value = ""

        def hasFocus(self) -> bool:
            return False

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="3444964", next_period="3444965", next_countdown=0)},
        _last_message_cursor={"pc28": (10, 20)},
        _query_period_overrides_by_site={},
        _stats_locked=True,
        _awaiting_next_period=True,
        _refreshing_sites={"pc28"},
        period_input=DummyInput(),
        _update_site_card_widgets=lambda site, info: calls.append("card"),
        _refresh_active_site_info=lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy),
        _sync_chart_status=lambda: calls.append("status"),
        _load_filtered_messages=lambda: calls.append("load"),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
    )
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)
    dummy._refreshing_site_set = lambda: MainWindowRealtimeMixin._refreshing_site_set(dummy)

    MainWindowRealtimeMixin._apply_single_draw_info(
        dummy,
        ("pc28", DrawInfo(current_period="3444965", next_period="3444966", next_countdown=210), None),
    )

    assert dummy.period_input.value == "3444966"
    assert dummy._last_message_cursor == {}
    assert dummy._stats_locked is False
    assert dummy._awaiting_next_period is False
    assert "load" in calls


def test_main_window_query_period_change_clears_chart_when_current_period_lags() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo, StatsResult
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[str] = []

    class DummyInput:
        def __init__(self) -> None:
            self.value = "3444965"

        def hasFocus(self) -> bool:
            return False

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="3444964", next_period="3444965", next_countdown=0)},
        _last_message_cursor={"pc28": (10, 20)},
        _query_period_overrides_by_site={},
        _stats_locked=True,
        _awaiting_next_period=True,
        _refreshing_sites={"pc28"},
        current_messages=[object()],
        current_visual_rows=[{"period": "3444965", "play": "大", "amount": 100.0}],
        current_stats=StatsResult(totals={"大": 100.0}),
        chart_window=SimpleNamespace(replace_rows=lambda rows: calls.append(("replace", list(rows)))),
        period_input=DummyInput(),
        _update_site_card_widgets=lambda site, info: calls.append("card"),
        _refresh_active_site_info=lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy),
        _sync_chart_status=lambda: calls.append("status"),
        _load_filtered_messages=lambda: calls.append("load"),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
    )
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)
    dummy._refreshing_site_set = lambda: MainWindowRealtimeMixin._refreshing_site_set(dummy)

    MainWindowRealtimeMixin._apply_single_draw_info(
        dummy,
        ("pc28", DrawInfo(current_period="3444964", next_period="3444966", next_countdown=210), None),
    )

    assert dummy.period_input.value == "3444966"
    assert dummy.current_messages == []
    assert dummy.current_visual_rows == []
    assert dummy.current_stats == StatsResult(totals={}, totals_by_group={})
    assert ("replace", []) in calls
    assert "load" in calls


def test_main_window_next_period_update_clears_stale_manual_query_override() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo, StatsResult
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[object] = []

    class DummyInput:
        def __init__(self) -> None:
            self.value = "3445740"

        def hasFocus(self) -> bool:
            return False

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="3445798", next_period="3445799", next_countdown=0)},
        _last_message_cursor={"pc28": (10, 20)},
        _query_period_overrides_by_site={"pc28": "3445740"},
        _query_period_override="3445740",
        _manual_period_override=True,
        _stats_locked=True,
        _awaiting_next_period=True,
        _refreshing_sites={"pc28"},
        current_messages=[object()],
        current_visual_rows=[{"period": "3445740", "play": "大", "amount": 100.0}],
        current_stats=StatsResult(totals={"大": 100.0}),
        chart_window=SimpleNamespace(replace_rows=lambda rows: calls.append(("replace", list(rows)))),
        period_input=DummyInput(),
        _update_site_card_widgets=lambda site, info: calls.append("card"),
        _refresh_active_site_info=lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy),
        _sync_chart_status=lambda: calls.append("status"),
        _load_filtered_messages=lambda: calls.append("load"),
        _save_settings=lambda: calls.append("save"),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
    )
    dummy._default_query_period = lambda info: MainWindowRealtimeMixin._default_query_period(dummy, info)
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)
    dummy._refreshing_site_set = lambda: MainWindowRealtimeMixin._refreshing_site_set(dummy)

    MainWindowRealtimeMixin._apply_single_draw_info(
        dummy,
        ("pc28", DrawInfo(current_period="3445799", next_period="3445800", next_countdown=210), None),
    )

    assert dummy.period_input.value == "3445800"
    assert dummy._query_period_overrides_by_site == {}
    assert dummy._query_period_override == ""
    assert dummy._manual_period_override is False
    assert dummy.current_messages == []
    assert dummy.current_visual_rows == []
    assert ("replace", []) in calls
    assert "load" in calls
    assert "save" in calls


def test_main_window_countdown_refresh_failure_uses_retry_countdown(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    submitted: list[str] = []

    class DummyWorker:
        def submit(self, func, site):
            submitted.append(site)
            return SimpleNamespace(add_done_callback=lambda callback: None)

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=1)},
        _refresh_active_site_info=lambda: None,
        _refreshing_sites=set(),
        _worker=DummyWorker(),
    )
    _bind_realtime_countdown_helpers(dummy)

    MainWindowRealtimeMixin._on_countdown_tick(dummy)
    MainWindowRealtimeMixin._on_countdown_tick(dummy)

    assert submitted == []
    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_infos["pc28"].next_period == "1003"
    assert dummy._draw_infos["pc28"].next_countdown == 210
    assert "pc28" in dummy._draw_calibration_due_at
    assert dummy._refreshing_sites == set()


def test_main_window_refresh_tick_does_not_poll_before_countdown_zero(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[str] = []
    monkeypatch.setattr(main_window_realtime, "extract_draw_info", lambda site: calls.append(site) or DrawInfo(current_period="x"))

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=30)},
        _refresh_active_site_info=lambda: None,
    )

    MainWindowRealtimeMixin._on_refresh_tick(dummy)

    assert calls == []


def test_main_window_message_refresh_tick_loads_messages_and_skips_when_busy() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    calls: list[str] = []
    dummy = SimpleNamespace(
        _message_load_in_progress=False,
        _load_filtered_messages=lambda: calls.append("load"),
    )

    MainWindowDataMixin._on_message_refresh_tick(dummy)
    dummy._message_load_in_progress = True
    MainWindowDataMixin._on_message_refresh_tick(dummy)

    assert calls == ["load"]


def test_main_window_message_refresh_tick_skips_when_active_site_is_locked() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_data import MainWindowDataMixin

    calls: list[str] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="3444964", next_period="3444965", next_countdown=20)},
        _lock_threshold_sec=20,
        _message_load_in_progress=False,
        _load_filtered_messages=lambda: calls.append("load"),
    )

    MainWindowDataMixin._on_message_refresh_tick(dummy)

    assert calls == []


def test_refresh_site_cards_submits_background_fetch_without_blocking(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    monkeypatch.setattr(
        main_window_realtime,
        "fetch_all_draw_infos",
        lambda: (_ for _ in ()).throw(AssertionError("should run only in worker")),
    )
    monkeypatch.setattr(main_window_realtime, "site_list", lambda: ["pc28"])

    submitted: list[object] = []

    class DummyWorker:
        def submit(self, func):
            submitted.append(func)
            return SimpleNamespace(add_done_callback=lambda callback: None)

    class DummyLayout:
        def count(self):
            return 0

        def addWidget(self, *_args):
            return None

    dummy = SimpleNamespace(
        _draw_infos={},
        _site_card_widgets={},
        _worker=DummyWorker(),
        site_cards_layout=DummyLayout(),
        site_status_label=SimpleNamespace(setText=lambda value: None),
        _build_site_card=lambda site, info: (object(), {}),
    )
    dummy._render_site_cards = lambda: MainWindowRealtimeMixin._render_site_cards(dummy)
    dummy._handle_site_cards_loaded = lambda future: MainWindowRealtimeMixin._handle_site_cards_loaded(dummy, future)

    MainWindowRealtimeMixin._refresh_site_cards(dummy)

    assert submitted == [main_window_realtime.fetch_all_draw_infos]


def test_site_cards_loaded_emits_draw_info_for_main_thread_application() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    emitted: list[dict[str, DrawInfo]] = []
    future = SimpleNamespace(result=lambda: {"pc28": DrawInfo(current_period="1001", next_period="1002", next_countdown=88)})
    dummy = SimpleNamespace(_draw_infos_ready=SimpleNamespace(emit=lambda value: emitted.append(value)))

    MainWindowRealtimeMixin._handle_site_cards_loaded(dummy, future)

    assert emitted
    assert emitted[0]["pc28"].current_period == "1001"


def test_apply_draw_infos_updates_site_card_countdown(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    monkeypatch.setattr(main_window_realtime, "site_list", lambda: ["pc28"])

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    widgets = {
        "name": DummyLabel(),
        "period": DummyLabel(),
        "next": DummyLabel(),
        "countdown": DummyLabel(),
    }
    dummy = SimpleNamespace(
        _draw_infos={},
        _active_site="",
        _site_card_widgets={"pc28": widgets},
        site_cards_layout=SimpleNamespace(count=lambda: 1),
        site_status_label=DummyLabel(),
    )
    dummy._render_site_cards = lambda: MainWindowRealtimeMixin._render_site_cards(dummy)
    dummy._update_site_card_widgets = lambda site, info: MainWindowRealtimeMixin._update_site_card_widgets(dummy, site, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)

    MainWindowRealtimeMixin._apply_draw_infos(dummy, {"pc28": DrawInfo("1001", next_period="1002", next_countdown=88)})

    assert widgets["period"].text == "当前: 1001"
    assert widgets["next"].text == "下期: 1002"
    assert widgets["countdown"].text == "倒计时: 01:28"


def test_site_card_uses_expanding_height_instead_of_fixed_short_height() -> None:
    import os
    from types import SimpleNamespace

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QSizePolicy

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    app = QApplication.instance() or QApplication([])
    dummy = SimpleNamespace(
        _format_countdown=lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value),
        _select_site=lambda site: None,
    )

    frame, _widgets = MainWindowRealtimeMixin._build_site_card(
        dummy,
        "pc28",
        DrawInfo(current_period="1001", next_period="1002", next_countdown=88),
    )

    assert frame.minimumHeight() >= 120
    assert frame.maximumHeight() >= 1600
    assert frame.sizePolicy().verticalPolicy() == QSizePolicy.Expanding


def test_chart_window_renders_vertical_stacked_allowed_play_totals() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QListWidget, QTextEdit

    from app.ui.chart_window import ALLOWED_CHART_PLAYS, THEME_COLORS, VerticalStackedBarChartWidget, ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()
    rows = [
        {
            "time": datetime(2026, 6, 13, 19, 36, 22),
            "group": "摩羯座网盘4.28-3.68",
            "username": "TfPISL2u5",
            "bettor": "桂林",
            "period": "1040954",
            "play": "大单",
            "amount": 2800.0,
        },
        {
            "time": datetime(2026, 6, 13, 19, 36, 24),
            "group": "摩羯座网盘4.28-3.68",
            "username": "TfPISL2u5",
            "bettor": "朝阳",
            "period": "1040954",
            "play": "大单",
            "amount": 5000.0,
        },
        {
            "time": datetime(2026, 6, 13, 19, 36, 24),
            "group": "摩羯座网盘4.28-3.68",
            "username": "TfPISL2u5",
            "bettor": "朝阳",
            "period": "1040954",
            "play": "13",
            "amount": 500.0,
        },
    ]

    chart.set_rows(rows)
    chart._append_increment_layer()

    assert isinstance(chart.bar_chart, VerticalStackedBarChartWidget)
    assert chart.bar_chart.categories == list(ALLOWED_CHART_PLAYS)
    assert chart.bar_chart.current_totals == {
        "大单": 7800.0,
        "小单": 0.0,
        "大双": 0.0,
        "小双": 0.0,
        "大": 0.0,
        "小": 0.0,
        "单": 0.0,
        "双": 0.0,
    }
    assert len(chart.bar_chart.layers) == 1
    assert chart.bar_chart.layers[0].color == THEME_COLORS[0]
    assert chart.bar_chart.layers[0].values["大单"] == 7800.0
    assert "13" not in chart.bar_chart.current_totals
    stats_text = chart.stats_text_view.toPlainText()
    assert "2026-06-13 19:36:22 - 摩羯座网盘4.28-3.68 - 桂林 - 大单 - 2,800" in stats_text
    assert "2026-06-13 19:36:24 - 摩羯座网盘4.28-3.68 - 朝阳 - 13 - 500" not in stats_text
    assert "大单: 7,800" not in stats_text
    assert len(chart.findChildren(QTextEdit)) == 1
    assert len(chart.findChildren(QListWidget)) == 1
    assert not hasattr(chart, "activity_view")
    chart.close()


def test_chart_window_keeps_period_layers_when_totals_temporarily_decrease() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()

    chart.set_rows([{"group": "一群", "period": "1040954", "play": "大", "amount": 100.0}])
    chart._append_increment_layer()
    chart.set_rows([{"group": "一群", "period": "1040954", "play": "大", "amount": 80.0}])
    chart._append_increment_layer()

    assert len(chart.bar_chart.layers) == 1
    assert chart.bar_chart.layers[0].values["大"] == 100.0
    assert chart.bar_chart.current_totals["大"] == 100.0
    chart.close()


def test_chart_window_visible_group_filter_does_not_clear_period_layers() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()
    chart.set_rows(
        [
            {"group": "一群", "period": "1040954", "play": "大", "amount": 100.0},
            {"group": "二群", "period": "1040954", "play": "小", "amount": 60.0},
        ]
    )
    chart._append_increment_layer()

    chart.group_list.item(1).setCheckState(Qt.Unchecked)

    assert len(chart.bar_chart.layers) == 1
    assert chart.bar_chart.layers[0].values["大"] == 100.0
    assert chart.bar_chart.layers[0].values["小"] == 0.0
    assert chart._all_layers[0].values["小"] == 60.0
    assert chart.bar_chart.current_totals["大"] == 100.0
    assert chart.bar_chart.current_totals["小"] == 0.0

    chart.group_list.item(1).setCheckState(Qt.Checked)
    assert chart.bar_chart.current_totals["小"] == 60.0
    chart.close()


def test_chart_window_keeps_current_period_history_across_incremental_set_rows() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import THEME_COLORS, ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()

    chart.set_rows(
        [
            {
                "time": datetime(2026, 6, 13, 19, 36, 22),
                "group": "一群",
                "bettor": "桂林",
                "period": "1040954",
                "play": "大",
                "amount": 100.0,
            }
        ]
    )
    chart._append_increment_layer()
    chart.set_rows(
        [
            {
                "time": datetime(2026, 6, 13, 19, 36, 27),
                "group": "一群",
                "bettor": "朝阳",
                "period": "1040954",
                "play": "小",
                "amount": 30.0,
            }
        ]
    )
    chart._append_increment_layer()

    assert [layer.color for layer in chart.bar_chart.layers] == THEME_COLORS[:2]
    assert chart.bar_chart.layers[0].values["大"] == 100.0
    assert chart.bar_chart.layers[1].values["小"] == 30.0
    assert chart.bar_chart.current_totals["大"] == 100.0
    assert chart.bar_chart.current_totals["小"] == 30.0
    stats_text = chart.stats_text_view.toPlainText()
    assert "2026-06-13 19:36:22 - 一群 - 桂林 - 大 - 100" in stats_text
    assert "2026-06-13 19:36:27 - 一群 - 朝阳 - 小 - 30" in stats_text
    chart.close()


def test_chart_window_stats_text_shows_newest_first_and_preserves_scroll_position() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()

    chart.set_rows(
        [
            {
                "time": datetime(2026, 6, 15, 10, 0, 0),
                "group": "一群",
                "bettor": "旧用户",
                "period": "3444965",
                "play": "大",
                "amount": 100.0,
            },
            {
                "time": datetime(2026, 6, 15, 10, 0, 5),
                "group": "一群",
                "bettor": "新用户",
                "period": "3444965",
                "play": "小",
                "amount": 50.0,
            },
        ]
    )
    assert chart.stats_text_view.toPlainText().splitlines()[0] == "2026-06-15 10:00:05 - 一群 - 新用户 - 小 - 50"

    scrollbar = chart.stats_text_view.verticalScrollBar()
    scrollbar.setValue(0)
    chart.set_rows(
        [
            {
                "time": datetime(2026, 6, 15, 10, 0, 10),
                "group": "一群",
                "bettor": "最新用户",
                "period": "3444965",
                "play": "单",
                "amount": 30.0,
            }
        ]
    )

    assert chart.stats_text_view.verticalScrollBar().value() == 0
    assert chart.stats_text_view.toPlainText().splitlines()[0] == "2026-06-15 10:00:10 - 一群 - 最新用户 - 单 - 30"
    chart.close()


def test_chart_window_update_activity_immediately_syncs_bar_chart_with_rows() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import ALLOWED_CHART_PLAYS, ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()

    play_a, play_b = ALLOWED_CHART_PLAYS[0], ALLOWED_CHART_PLAYS[1]
    rows = [
        {"time": datetime(2026, 6, 17, 10, 0, 0), "group": "G1", "bettor": "A", "period": "p1", "play": play_a, "amount": 100.0},
        {"time": datetime(2026, 6, 17, 10, 0, 1), "group": "G2", "bettor": "B", "period": "p1", "play": play_b, "amount": 50.0},
    ]

    chart.set_rows(rows)
    chart.update_activity(rows)

    assert len(chart.bar_chart.layers) == 1
    assert chart.bar_chart.current_totals[play_a] == 100.0
    assert chart.bar_chart.current_totals[play_b] == 50.0
    assert play_a in chart.stats_text_view.toPlainText()
    assert play_b in chart.stats_text_view.toPlainText()
    chart.close()


def test_chart_window_replaces_period_rows_when_filter_returns_empty_for_same_period() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()

    chart.set_rows(
        [
            {
                "time": datetime(2026, 6, 15, 15, 28, 51),
                "group": "摩羯座网盘4.28-3.68",
                "bettor": "旺达",
                "period": "3444965",
                "play": "小单",
                "amount": 700.0,
            }
        ]
    )
    chart.replace_rows([])

    assert "旺达" not in chart.stats_text_view.toPlainText()
    assert chart.bar_chart.current_totals == chart._zero_totals()
    chart.close()


def test_chart_window_appends_increment_layers_with_cycling_colors() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.chart_window import THEME_COLORS, ChartWindow

    app = QApplication.instance() or QApplication([])
    chart = ChartWindow()
    chart._stack_timer.stop()

    chart.set_rows([{"group": "一群", "play": "大", "amount": 100.0}])
    chart._append_increment_layer()
    chart.set_rows([{"group": "一群", "play": "大", "amount": 150.0}, {"group": "一群", "play": "小", "amount": 30.0}])
    chart._append_increment_layer()

    assert [layer.color for layer in chart.bar_chart.layers] == THEME_COLORS[:2]
    assert chart.bar_chart.layers[0].values["大"] == 100.0
    assert chart.bar_chart.layers[1].values["大"] == 50.0
    assert chart.bar_chart.layers[1].values["小"] == 30.0
    assert chart.bar_chart.current_totals["大"] == 150.0
    assert chart.bar_chart.current_totals["小"] == 30.0
    chart.close()


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


def test_settings_service_logs_readable_chinese(caplog, monkeypatch, tmp_path: Path) -> None:
    from app.services.settings_service import SettingsService
    from app.services.storage_service import JsonStore

    monkeypatch.setattr(JsonStore, "__init__", lambda self, filename: setattr(self, "path", tmp_path / filename))
    service = SettingsService()

    with caplog.at_level("DEBUG"):
        data = service.load()
        data["username"] = "tester"
        service.save(data)

    assert "加载设置" in caplog.text
    assert "保存设置: username=tester" in caplog.text


def test_main_window_data_logs_empty_load_diagnostics(caplog) -> None:
    from pathlib import Path
    from types import SimpleNamespace
    from datetime import datetime

    from app.models import ParseOptions, StatsResult
    from app.ui.main_window_data import MainWindowDataMixin

    dummy = SimpleNamespace()
    options = ParseOptions(
        username="tester",
        groups=["GroupA", "GroupB"],
        group_ids=["g1", "g2"],
        period_filter="9001",
        site="pc28",
    )
    options.start_time = datetime(2026, 6, 12, 3, 38, 39)
    options.end_time = datetime(2026, 6, 12, 3, 58, 39)
    options.incremental_cursor_value = 123456
    options.incremental_cursor_rand = 7

    with caplog.at_level("INFO"):
        MainWindowDataMixin._log_load_diagnostics(
            dummy,
            source_path=Path("C:/data/msg_0.db"),
            options=options,
            messages=[],
            visual_rows=[],
            stats=StatsResult(totals={}, matched_messages=0, totals_by_group={}),
        )

    assert "Load diagnostics" in caplog.text
    assert "source=C:\\data\\msg_0.db" in caplog.text or "source=C:/data/msg_0.db" in caplog.text
    assert "site=pc28" in caplog.text
    assert "groups=2" in caplog.text
    assert "group_ids=2" in caplog.text
    assert "selected_group_ids=g1,g2" in caplog.text
    assert "period=9001" in caplog.text
    assert "start=2026-06-12 03:38:39" in caplog.text
    assert "end=2026-06-12 03:58:39" in caplog.text
    assert "cursor=123456/7" in caplog.text
    assert "messages=0" in caplog.text
    assert "matched=0" in caplog.text
    assert "rows=0" in caplog.text
    assert "totals_by_group=0" in caplog.text


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


def test_main_window_actions_save_settings_moves_current_username_to_recent_front() -> None:
    from app.ui.main_window_actions import MainWindowActionsMixin

    saved_payloads: list[dict[str, object]] = []

    class DummyService:
        def save(self, payload):
            saved_payloads.append(payload)

    class DummyCombo:
        def __init__(self) -> None:
            self.items = ["tester", "齐天大圣"]

        def currentText(self):
            return "齐天大圣"

        def count(self):
            return len(self.items)

        def itemText(self, index: int):
            return self.items[index]

    class DummyText:
        def text(self):
            return ""

    class DummyWindow(MainWindowActionsMixin):
        def _current_source_path(self):
            return None

        def _selected_group_ids(self):
            return []

        def _selected_block_group_key(self):
            return ""

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
    dummy._query_period_override = ""
    dummy._manual_period_override = False

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["username"] == "齐天大圣"
    assert payload["recent_usernames"][:2] == ["齐天大圣", "tester"]


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


def test_main_window_actions_save_settings_persists_advanced_time_filter() -> None:
    from datetime import datetime

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

    class DummyFrame:
        def isVisible(self) -> bool:
            return True

    class DummyDateTimeValue:
        def __init__(self, value: datetime) -> None:
            self.value = value

        def toPython(self):
            return self.value

    class DummyDateTimeEdit:
        def __init__(self, value: datetime) -> None:
            self.value = value

        def dateTime(self):
            return DummyDateTimeValue(self.value)

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
    dummy.advanced_time_frame = DummyFrame()
    dummy.start_edit = DummyDateTimeEdit(datetime(2026, 6, 12, 3, 30, 0))
    dummy.end_edit = DummyDateTimeEdit(datetime(2026, 6, 12, 3, 35, 0))
    dummy.settings = {"export_dir": "", "proxy_enabled": False, "proxy_http": "", "proxy_https": ""}
    dummy.group_block_rules = {}
    dummy._lock_threshold_sec = 20
    dummy._is_first_launch = False
    dummy._query_period_overrides_by_site = {}
    dummy._query_period_override = ""
    dummy._manual_period_override = False

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["advanced_time_filter_enabled"] is True
    assert payload["advanced_time_start"] == "2026-06-12T03:30:00"
    assert payload["advanced_time_end"] == "2026-06-12T03:35:00"


def test_main_window_actions_save_settings_drops_legacy_period_override() -> None:
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

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["query_period_overrides_by_site"] == {}
    assert payload["query_period_override"] == ""
    assert payload["manual_period_override"] is False


def test_resolve_database_failure_preserves_saved_data_source(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def currentText(self) -> str:
            return "tester"

    class DummyEdit:
        def __init__(self, value: str) -> None:
            self.value = value
            self.cleared = False

        def clear(self) -> None:
            self.cleared = True

        def text(self) -> str:
            return self.value

    class DummyList:
        def __init__(self) -> None:
            self.cleared = False

        def clear(self) -> None:
            self.cleared = True

    class DummyLabel:
        def __init__(self) -> None:
            self.text = ""

        def setText(self, value: str) -> None:
            self.text = value

    dummy = SimpleNamespace(
        username_combo=DummyCombo(),
        account_resolver=SimpleNamespace(resolve=lambda username: None, get_diagnostic=lambda: None),
        resolved_db=None,
        resolved_path_edit=DummyEdit("D:/last/msg_0.db"),
        group_list=DummyList(),
        db_status_label=DummyLabel(),
        status_label=DummyLabel(),
        fallback_box=SimpleNamespace(setVisible=lambda value: None),
        _refresh_block_rule_group_selector=lambda: None,
    )

    MainWindowDataMixin._resolve_database(dummy, silent=True)

    assert dummy.resolved_path_edit.value == "D:/last/msg_0.db"
    assert dummy.resolved_path_edit.cleared is False
    assert dummy.group_list.cleared is False


def test_resolve_database_failure_still_remembers_typed_username() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def __init__(self) -> None:
            self.items: list[str] = ["Alice"]
            self.current = "齐天大圣"

        def currentText(self) -> str:
            return self.current

        def count(self) -> int:
            return len(self.items)

        def itemText(self, index: int) -> str:
            return self.items[index]

        def clear(self) -> None:
            self.items = []

        def addItems(self, values) -> None:
            self.items.extend(values)

        def setCurrentText(self, value: str) -> None:
            self.current = value

    class DummyEdit:
        def __init__(self) -> None:
            self.value = "D:/last/msg_0.db"

        def clear(self) -> None:
            self.value = ""

        def text(self) -> str:
            return self.value

    class DummyLabel:
        def setText(self, value: str) -> None:
            return None

    saved: list[str] = []

    class DummyWindow(MainWindowDataMixin):
        def _remember_username(self, username: str) -> None:
            self.username_combo.items = [username, "Alice"]
            self.username_combo.current = username

        def _save_settings(self) -> None:
            saved.append(self.username_combo.currentText())

        def _refresh_block_rule_group_selector(self) -> None:
            return None

    dummy = DummyWindow()
    dummy.username_combo = DummyCombo()
    dummy.account_resolver = SimpleNamespace(resolve=lambda username: None, get_diagnostic=lambda: None)
    dummy.resolved_db = None
    dummy.resolved_path_edit = DummyEdit()
    dummy.group_list = SimpleNamespace(clear=lambda: None)
    dummy.db_status_label = DummyLabel()
    dummy.status_label = DummyLabel()
    dummy.fallback_box = SimpleNamespace(setVisible=lambda value: None)

    MainWindowDataMixin._resolve_database(dummy, silent=True)

    assert dummy.username_combo.currentText() == "齐天大圣"
    assert dummy.username_combo.items[0] == "齐天大圣"
    assert saved == ["齐天大圣"]


def test_load_groups_restores_saved_group_selection(tmp_path: Path) -> None:
    import sqlite3
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QListWidget

    from app.ui.main_window_data import MainWindowDataMixin

    msg_db = tmp_path / "msg_0.db"
    con = sqlite3.connect(msg_db)
    con.execute("create table message (sid text)")
    con.executemany("insert into message values (?)", [("g1",), ("g2",)])
    con.commit()
    con.close()

    class DummyService:
        def list_groups_from_db(self, _source_path):
            from app.models import ChatGroup

            return [ChatGroup("g1", "一群"), ChatGroup("g2", "二群")]

    app = QApplication.instance() or QApplication([])
    dummy = SimpleNamespace(
        settings={"selected_group_ids": ["g2"]},
        group_list=QListWidget(),
        chat_service=DummyService(),
        _current_source_path=lambda: msg_db,
        _refresh_block_rule_group_selector=lambda: None,
    )

    MainWindowDataMixin._load_groups_from_current_source(dummy)

    assert dummy.group_list.item(0).text() == "一群"
    assert dummy.group_list.item(0).data(Qt.UserRole) == "g1"
    assert dummy.group_list.item(0).data(Qt.UserRole + 1) == "一群"
    assert dummy.group_list.item(0).checkState() == Qt.Unchecked
    assert dummy.group_list.item(1).text() == "二群"
    assert dummy.group_list.item(1).data(Qt.UserRole) == "g2"
    assert dummy.group_list.item(1).data(Qt.UserRole + 1) == "二群"
    assert dummy.group_list.item(1).checkState() == Qt.Checked


def test_load_groups_restores_explicit_all_selection_even_when_group_ids_changed(tmp_path: Path) -> None:
    import sqlite3
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QListWidget

    from app.ui.main_window_data import MainWindowDataMixin

    msg_db = tmp_path / "msg_0.db"
    con = sqlite3.connect(msg_db)
    con.execute("create table message (sid text)")
    con.executemany("insert into message values (?)", [("new1",), ("new2",)])
    con.commit()
    con.close()

    class DummyService:
        def list_groups_from_db(self, _source_path):
            from app.models import ChatGroup

            return [ChatGroup("new1", "新一群"), ChatGroup("new2", "新二群")]

    app = QApplication.instance() or QApplication([])
    dummy = SimpleNamespace(
        settings={"selected_group_mode": "all", "selected_group_ids": ["old1", "old2"]},
        group_list=QListWidget(),
        chat_service=DummyService(),
        _current_source_path=lambda: msg_db,
        _refresh_block_rule_group_selector=lambda: None,
    )

    MainWindowDataMixin._load_groups_from_current_source(dummy)

    assert dummy.group_list.item(0).checkState() == Qt.Checked
    assert dummy.group_list.item(1).checkState() == Qt.Checked


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


def test_chat_service_receipt_block_list_matches_bettor_and_resolved_nickname() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    play = "大"
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 15, 10, 0, 0),
            group="摩羯座网盘4.28-3.68",
            username="齐天大圣",
            sender_id="user-1",
            content=f"{play}100 3444965",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 15, 10, 0, 5),
            group="摩羯座网盘4.28-3.68",
            username="Robot",
            sender_id="robot-1",
            content=(
                "@猴子 : \n"
                "下注期数: 3444965\n"
                "下注内容: \n"
                "------------\n"
                f"{play}100(1.98赔率)\n"
                "------------\n"
                "余额：1000"
            ),
        ),
    ]

    blocked_by_bettor, stats_by_bettor = service.analyze_bets(
        messages,
        blocked_names=["猴子"],
        blocked_ids=[],
        period_filter="3444965",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=210,
    )
    blocked_by_nickname, stats_by_nickname = service.analyze_bets(
        messages,
        blocked_names=["齐天大圣"],
        blocked_ids=[],
        period_filter="3444965",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=210,
    )

    assert blocked_by_bettor == []
    assert stats_by_bettor.totals == {}
    assert blocked_by_nickname == []
    assert stats_by_nickname.totals == {}


def test_chat_service_group_block_rule_filters_bettor_in_matching_group_only() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    service.set_group_block_rules(
        {
            "摩羯座网盘4.28-3.68": {
                "group_id": "摩羯座网盘4.28-3.68",
                "group_name": "摩羯座网盘4.28-3.68",
                "names": ["旺达"],
            }
        }
    )
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 15, 15, 28, 51),
            group="摩羯座网盘4.28-3.68",
            username="旺达",
            sender_id="wanda-1",
            content="小单700 3444965",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 15, 15, 28, 53),
            group="处女座 4.2 4.6高倍",
            username="神经",
            sender_id="shen-1",
            content="小双30 小单30 3444965",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3444965",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=210,
    )

    assert all(row["bettor"] != "旺达" for row in rows)
    assert stats.totals == {"小单": 30.0, "小双": 30.0}


def test_chat_service_decodes_frontend_aas_ciphertext_from_legacy_exe() -> None:
    from app.services.chat_service import ChatLogService

    service = ChatLogService()

    assert service._decrypt_frontend_aas_text("8KcXXLdrA2KfY084IeVaNA==") == "1"


def test_chat_service_extract_message_text_decodes_frontend_aas_ciphertext() -> None:
    from app.services.chat_service import ChatLogService

    service = ChatLogService()

    assert service._extract_message_text(" 8KcXXLdrA2KfY084IeVaNA==", b"") == "1"


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


def test_raw_chat_dialog_formats_and_filters_messages() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import ChatMessage
    from app.ui.raw_chat_dialog import RawChatDialog

    app = QApplication.instance() or QApplication([])
    dialog = RawChatDialog(
        [
            ChatMessage(
                ts=datetime(2026, 6, 16, 17, 55, 1),
                group="PC28-A",
                username="Alice",
                sender_id="alice-id",
                content="大单100",
            ),
            ChatMessage(
                ts=datetime(2026, 6, 16, 17, 55, 2),
                group="PC28-B",
                username="Bob",
                sender_id="bob-id",
                content="小双200",
            ),
        ],
        page_size=50,
    )

    text = dialog.message_view.toPlainText()
    assert "2026-06-16 17:55:01 | PC28-A | Alice | alice-id" in text
    assert "大单100" in text
    assert "2026-06-16 17:55:02 | PC28-B | Bob | bob-id" in text
    assert "小双200" in text

    dialog.group_filter.setCurrentText("PC28-B")
    app.processEvents()

    filtered_text = dialog.message_view.toPlainText()
    assert "Bob | bob-id" in filtered_text
    assert "小双200" in filtered_text
    assert "Alice | alice-id" not in filtered_text
    assert "大单100" not in filtered_text
    dialog.close()


def test_raw_chat_dialog_preserves_current_page_when_messages_refresh() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import ChatMessage
    from app.ui.raw_chat_dialog import RawChatDialog

    app = QApplication.instance() or QApplication([])
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 16, 17, 55, index),
            group="PC28-A",
            username=f"User{index}",
            sender_id=f"user-{index}",
            content=f"消息{index}",
        )
        for index in range(1, 4)
    ]
    dialog = RawChatDialog(messages, page_size=1)

    dialog._next_page()
    assert dialog.message_page == 1
    assert "消息2" in dialog.message_view.toPlainText()

    dialog.set_messages(
        messages
        + [
            ChatMessage(
                ts=datetime(2026, 6, 16, 17, 55, 4),
                group="PC28-A",
                username="User4",
                sender_id="user-4",
                content="消息4",
            )
        ]
    )
    app.processEvents()

    assert dialog.message_page == 1
    assert "消息2" in dialog.message_view.toPlainText()
    dialog.close()


def test_raw_chat_dialog_preserves_scroll_position_when_messages_refresh() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import ChatMessage
    from app.ui.raw_chat_dialog import RawChatDialog

    app = QApplication.instance() or QApplication([])
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 16, 17, 55, index),
            group="PC28-A",
            username=f"User{index}",
            sender_id=f"user-{index}",
            content="消息" + ("X" * 100),
        )
        for index in range(1, 8)
    ]
    dialog = RawChatDialog(messages, page_size=7)
    dialog.message_view.verticalScrollBar().setValue(dialog.message_view.verticalScrollBar().maximum())
    before = dialog.message_view.verticalScrollBar().value()

    dialog.set_messages(messages + [ChatMessage(
        ts=datetime(2026, 6, 16, 17, 55, 8),
        group="PC28-A",
        username="User8",
        sender_id="user-8",
        content="消息" + ("Y" * 100),
    )])
    app.processEvents()

    after = dialog.message_view.verticalScrollBar().value()
    assert after >= before
    dialog.close()


def test_main_window_opens_and_reuses_raw_chat_dialog() -> None:
    import os
    from datetime import datetime
    from types import SimpleNamespace

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import ChatMessage
    from app.ui.main_window_actions import MainWindowActionsMixin

    app = QApplication.instance() or QApplication([])
    first_message = ChatMessage(
        ts=datetime(2026, 6, 16, 17, 55, 1),
        group="PC28-A",
        username="Alice",
        sender_id="alice-id",
        content="大单100",
    )
    second_message = ChatMessage(
        ts=datetime(2026, 6, 16, 17, 56, 1),
        group="PC28-A",
        username="Alice",
        sender_id="alice-id",
        content="小单200",
    )
    dummy = SimpleNamespace(current_messages=[first_message], raw_chat_dialog=None)

    MainWindowActionsMixin._open_raw_chat_dialog(dummy)
    first_dialog = dummy.raw_chat_dialog
    assert first_dialog is not None
    assert "大单100" in first_dialog.message_view.toPlainText()

    dummy.current_messages = [second_message]
    MainWindowActionsMixin._open_raw_chat_dialog(dummy)
    app.processEvents()

    assert dummy.raw_chat_dialog is first_dialog
    assert "小单200" in first_dialog.message_view.toPlainText()
    assert "大单100" not in first_dialog.message_view.toPlainText()
    first_dialog.close()


def test_main_window_accumulates_raw_chat_history_across_refreshes() -> None:
    import os
    from datetime import datetime
    from types import SimpleNamespace

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import ChatMessage
    from app.ui.main_window_actions import MainWindowActionsMixin

    app = QApplication.instance() or QApplication([])
    first_message = ChatMessage(
        ts=datetime(2026, 6, 16, 17, 55, 1),
        group="PC28-A",
        username="Alice",
        sender_id="alice-id",
        content="大单100",
    )
    second_message = ChatMessage(
        ts=datetime(2026, 6, 16, 17, 56, 1),
        group="PC28-A",
        username="Alice",
        sender_id="alice-id",
        content="小单200",
    )
    dummy = SimpleNamespace(
        current_messages=[first_message],
        raw_chat_messages=[],
        raw_chat_dialog=None,
    )

    MainWindowActionsMixin._record_raw_chat_messages(dummy, dummy.current_messages)
    dummy.current_messages = [second_message]
    MainWindowActionsMixin._record_raw_chat_messages(dummy, dummy.current_messages)

    MainWindowActionsMixin._open_raw_chat_dialog(dummy)
    app.processEvents()
    text = dummy.raw_chat_dialog.message_view.toPlainText()

    assert "大单100" in text
    assert "小单200" in text
    assert len(dummy.raw_chat_messages) == 2
    dummy.raw_chat_dialog.close()


def test_main_window_bound_raw_chat_history_accumulates_across_refreshes() -> None:
    import os
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.models import ChatMessage
    from app.ui.main_window_actions import MainWindowActionsMixin

    class DummyWindow(MainWindowActionsMixin):
        pass

    app = QApplication.instance() or QApplication([])
    dummy = DummyWindow()
    dummy.current_messages = [
        ChatMessage(
            ts=datetime(2026, 6, 16, 17, 55, 1),
            group="PC28-A",
            username="Alice",
            sender_id="alice-id",
            content="大单100",
        )
    ]
    dummy.raw_chat_messages = []
    dummy.raw_chat_dialog = None

    dummy._record_raw_chat_messages(dummy.current_messages)
    dummy.current_messages = [
        ChatMessage(
            ts=datetime(2026, 6, 16, 17, 56, 1),
            group="PC28-A",
            username="Alice",
            sender_id="alice-id",
            content="小单200",
        )
    ]
    dummy._record_raw_chat_messages(dummy.current_messages)
    dummy._open_raw_chat_dialog()
    text = dummy.raw_chat_dialog.message_view.toPlainText()

    assert "大单100" in text
    assert "小单200" in text
    assert len(dummy.raw_chat_messages) == 2
    dummy.raw_chat_dialog.close()
